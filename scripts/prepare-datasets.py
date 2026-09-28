"""Download pinned public samples and load bounded, separate review workspaces."""
import argparse
from dataclasses import replace
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from urllib.request import urlopen

from dataset_env import ROOT, LABS, local_environment


def download(spec: dict, directory: Path, offline: bool):
    path = directory / spec['filename']
    if path.exists():
        if path.stat().st_size == spec['bytes'] and hashlib.sha256(path.read_bytes()).hexdigest() == spec['sha256']:
            return path
        raise ValueError(f'Existing {path.name} failed checksum verification; preserve or remove it before retrying')
    if offline:
        raise ValueError(f'{path.name} is missing; run once without --offline to download it')
    with urlopen(spec['url'], timeout=60) as response:
        raw = response.read(spec['bytes'] + 1)
    if len(raw) != spec['bytes'] or hashlib.sha256(raw).hexdigest() != spec['sha256']:
        raise ValueError(f'{path.name} failed download size/hash verification')
    with tempfile.NamedTemporaryFile(dir=directory, delete=False) as stream:
        stage = Path(stream.name)
        stream.write(raw)
    try:
        # Avoid overwriting a concurrent download.
        os.link(stage, path)
    finally:
        stage.unlink()
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--synthea-subject')
    parser.add_argument('--fitbit-subject')
    parser.add_argument('--per-kind', type=int, default=4)
    parser.add_argument('--days', type=int, default=7)
    args = parser.parse_args()
    environment = local_environment('synthea', 8083, 3018)
    for key in list(os.environ):
        if key.startswith(('BODYBRAIN_', 'COGNEE_', 'CLAWMAX_')):
            del os.environ[key]
    os.environ.update(environment)
    sys.path.insert(0, str(ROOT / 'backend'))
    from bodybrain.clawmax import ClawMaxClient
    from bodybrain.cognee_memory import CogneeMemory
    from bodybrain.config import Settings
    from bodybrain.datasets import synthea_drafts, fitbit_drafts, import_batch
    from bodybrain.service import Service

    directory = ROOT / '.runtime/datasets/raw'
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = os.fdopen(os.open(directory.parent / 'server.lock', os.O_CREAT | os.O_RDWR, 0o600), 'w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise ValueError('Stop the dataset apps before preparing their records')
    manifest = json.loads((ROOT / 'datasets/sources.json').read_text())
    files = {key: download(spec, directory, args.offline) for key, spec in manifest['archives'].items()}
    # Parse both completely before modifying either workspace.
    batches = [synthea_drafts(files['synthea'], args.synthea_subject, args.per_kind),
               fitbit_drafts(files['fitbit'], args.fitbit_subject, args.days)]
    results = []
    for batch in batches:
        settings = replace(Settings(), data_dir=LABS / batch['dataset'], cognee_mode='disabled', clawmax_transport='dashboard')
        service = Service(settings, CogneeMemory('disabled'), ClawMaxClient(), ClawMaxClient())
        results.append(import_batch(service, batch))
    result_path = ROOT / '.runtime/datasets/prepared.json'
    with os.fdopen(os.open(result_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w') as stream:
        json.dump(results, stream, indent=2)
        stream.write('\n')
    print(json.dumps([dict(dataset=r['dataset'], subject_id=r['subject_id'], records=r['records'], review_required=True) for r in results], indent=2))
    print('Ready. Run npm run datasets:run, then review records in the separate sample apps.')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError) as exc:
        raise SystemExit(f'Dataset preparation failed: {exc}')
