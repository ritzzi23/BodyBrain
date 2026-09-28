"""Versioned local backups. Restore only into a new directory; never overwrite data."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import zipfile

FORMAT = 'bodybrain.backup.v1'
MAX_BYTES = 2 * 1024 * 1024 * 1024


def create_backup(data_dir: Path, destination: Path) -> dict:
    data_dir, destination = data_dir.resolve(), destination.resolve()
    if destination.exists():
        raise ValueError('Choose a new backup filename; existing backups are never overwritten')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='bodybrain-backup-') as temporary:
        stage = Path(temporary)
        db_file = stage / 'bodybrain.sqlite3'
        with sqlite3.connect(f'{(data_dir / "bodybrain.sqlite3").as_uri()}?mode=ro', uri=True) as source:
            with sqlite3.connect(db_file) as copy:
                source.backup(copy)
        with sqlite3.connect(db_file) as db:
            if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise ValueError('Database integrity check failed')
            ids = [row[0] for row in db.execute('SELECT id FROM records')]
        (stage / 'sources').mkdir(mode=0o700)
        for record_id in ids:
            from uuid import UUID
            if str(UUID(record_id)) != record_id:
                raise ValueError('Invalid source identifier')
            source = data_dir / 'sources' / record_id
            if source.is_symlink() or not source.is_file():
                raise ValueError('A source changed during backup; retry while record edits are idle')
            shutil.copyfile(source, stage / 'sources' / record_id)
        files = [db_file, *sorted((stage / 'sources').iterdir())]
        if sum(p.stat().st_size for p in files) > MAX_BYTES:
            raise ValueError('Backup exceeds the 2 GB local archive limit')
        manifest = {'format': FORMAT, 'records': len(ids), 'files': {
            str(p.relative_to(stage)): {'bytes': p.stat().st_size, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
            for p in files}}
        fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            with os.fdopen(fd, 'wb') as output, zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
                archive.writestr('manifest.json', json.dumps(manifest))
                for p in files:
                    archive.write(p, p.relative_to(stage))
        except BaseException:
            destination.unlink(missing_ok=True)
            raise
        return manifest


def restore_backup(archive_path: Path, destination: Path) -> dict:
    destination = destination.absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError('Restore requires a new, nonexistent data directory')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.bodybrain-restore-', dir=destination.parent) as temporary:
        stage = Path(temporary)
        with zipfile.ZipFile(archive_path) as archive:
            entries = archive.infolist()
            names = [item.filename for item in entries]
            if len(names) != len(set(names)) or sum(item.file_size for item in entries) > MAX_BYTES:
                raise ValueError('Duplicate entries or oversized backup')
            if 'manifest.json' not in names or archive.getinfo('manifest.json').file_size > 10_000_000:
                raise ValueError('Missing or oversized backup manifest')
            manifest = json.loads(archive.read('manifest.json'))
            if manifest.get('format') != FORMAT or not isinstance(manifest.get('files'), dict):
                raise ValueError('Unsupported backup format')
            if set(names) != {'manifest.json', *manifest['files']} or 'bodybrain.sqlite3' not in names:
                raise ValueError('Backup file inventory mismatch')
            for name, expected in manifest['files'].items():
                from uuid import UUID
                if name != 'bodybrain.sqlite3':
                    if not name.startswith('sources/') or str(UUID(name[8:])) != name[8:]:
                        raise ValueError('Invalid backup path')
                raw = archive.read(name)
                if len(raw) != expected['bytes'] or hashlib.sha256(raw).hexdigest() != expected['sha256']:
                    raise ValueError('Backup integrity check failed')
                target = stage / name
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                with os.fdopen(os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'wb') as stream:
                    stream.write(raw)
        with sqlite3.connect(stage / 'bodybrain.sqlite3') as db:
            if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise ValueError('Database integrity check failed')
            if db.execute('PRAGMA user_version').fetchone()[0] > 1:
                raise ValueError('This backup requires a newer BodyBrain version')
            records = db.execute('SELECT id, data FROM records').fetchall()
            if set(manifest['files']) != {'bodybrain.sqlite3', *(f'sources/{r[0]}' for r in records)}:
                raise ValueError('Backup sources do not match database records')
            # A historical backup must not replay hosted jobs or implicitly upload
            # records. Keep original remote cleanup identities for explicit deletes.
            for record_id, serialized in records:
                record = json.loads(serialized)
                if record['status'] == 'approved' or record['memory_status'] == 'pending':
                    record['memory_status'] = 'not_indexed'
                db.execute('UPDATE records SET memory_status=?, data=? WHERE id=?', (record['memory_status'], json.dumps(record), record_id))
            db.execute('DELETE FROM tasks')
            for job_id, serialized in db.execute('SELECT id, data FROM relay_jobs').fetchall():
                job = json.loads(serialized)
                job['task'] = {k: job['task'][k] for k in ('task_id', 'digest', 'expires_at')}
                db.execute('UPDATE relay_jobs SET data=? WHERE id=?', (json.dumps(job), job_id))
            for run_id, serialized in db.execute('SELECT id, data FROM runs').fetchall():
                run = json.loads(serialized)
                if run.get('status') in {'running', 'submitted', 'pending'}:
                    run.update(status='interrupted', steps=[{'name': 'Restored snapshot', 'status': 'interrupted', 'detail': 'Retry explicitly after checking provider state.'}])
                    db.execute('UPDATE runs SET data=? WHERE id=?', (json.dumps(run), run_id))
            db.commit()
            db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        # rename is atomic on the same filesystem; publish only a verified result.
        os.rename(stage, destination)
        return {'status': 'restored', 'records': len(records), 'data_dir': str(destination)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    backup = sub.add_parser('create')
    backup.add_argument('--data-dir', type=Path, required=True)
    backup.add_argument('--output', type=Path, required=True)
    restore = sub.add_parser('restore')
    restore.add_argument('archive', type=Path)
    restore.add_argument('--data-dir', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = create_backup(args.data_dir, args.output) if args.command == 'create' else restore_backup(args.archive, args.data_dir)
        print(json.dumps({k: v for k, v in result.items() if k != 'files'}, indent=2))
    except (ValueError, OSError, sqlite3.Error, zipfile.BadZipFile, KeyError) as exc:
        parser.exit(1, f'Backup operation failed: {type(exc).__name__}. Check the archive and destination.\n')


if __name__ == '__main__':
    main()
