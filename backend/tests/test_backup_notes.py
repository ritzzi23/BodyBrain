import hashlib
import json
import sqlite3
from dataclasses import replace
from pathlib import Path
from uuid import uuid4
import zipfile

from fastapi.testclient import TestClient
import pytest

from bodybrain.backup import create_backup, restore_backup
from bodybrain.config import Settings
from bodybrain.db import Store, StateConflict
from bodybrain.main import create_app


def app_at(path):
    return create_app(replace(Settings(), data_dir=path, cognee_mode='disabled', clawmax_transport='dashboard', api_token='', agent_token=''))


def test_note_is_retryable_exact_and_needs_review(tmp_path):
    app = app_at(tmp_path / 'data')
    concept = next(iter(app.state.service.anatomy.by_id.values()))
    with TestClient(app) as client:
        payload = {'client_id': str(uuid4()), 'text': 'My own observation.', 'concept_id': concept['id'], 'event_date': '2026-09-27'}
        first = client.post('/api/notes', json=payload)
        assert first.status_code == 201
        record = first.json()
        assert record['status'] == 'pending_review'
        assert record['text'] == payload['text']
        assert all(f['concept']['id'] == concept['id'] for f in record['findings'])
        assert client.post('/api/notes', json=payload).json()['id'] == record['id']
        assert client.get('/api/health').json()['counts']['records'] == 1
        assert not client.post('/api/chat', json={'question': 'observation'}).json()['citations']
        client.post(f"/api/records/{record['id']}/approve", json={})
        assert client.post('/api/chat', json={'question': 'observation'}).json()['citations']
        payload['concept_id'] = 'nonexistent'
        assert client.post('/api/notes', json=payload).status_code == 422


def test_backup_roundtrip_retains_sources_and_review_but_never_replays_jobs(tmp_path):
    data, restored = tmp_path / 'data', tmp_path / 'restored'
    with TestClient(app_at(data)) as client:
        record = client.post('/api/records/text', json={'title': 'Test', 'text': 'No fracture of the left femur.'}).json()
        client.post(f"/api/records/{record['id']}/approve", json={})
        exported = client.get('/api/backup')
        assert exported.status_code == 200 and exported.headers['content-type'] == 'application/zip'
        archive = tmp_path / 'backup.zip'
        archive.write_bytes(exported.content)
    assert restore_backup(archive, restored)['records'] == 1
    with TestClient(app_at(restored)) as client:
        assert client.get(f"/api/records/{record['id']}/source").text == record['text']
        assert client.get('/api/records').json()['records'][0]['status'] == 'approved'
        assert client.get('/api/records').json()['records'][0]['memory_status'] == 'not_indexed'
    with pytest.raises(ValueError, match='new, nonexistent'):
        restore_backup(archive, restored)


@pytest.mark.parametrize('kind', ['corrupt', 'traversal', 'extra'])
def test_restore_rejects_tampering_without_publishing_directory(tmp_path, kind):
    data = tmp_path / 'data'
    Store(data / 'bodybrain.sqlite3')
    archive = tmp_path / 'backup.zip'
    create_backup(data, archive)
    with zipfile.ZipFile(archive) as z:
        files = {name: z.read(name) for name in z.namelist()}
    if kind == 'corrupt':
        files['bodybrain.sqlite3'] += b'changed'
    elif kind == 'extra':
        files['extra'] = b'extra'
    else:
        name, raw = '../escape', b'escape'
        files[name] = raw
        manifest = json.loads(files['manifest.json'])
        manifest['files'][name] = {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
        files['manifest.json'] = json.dumps(manifest).encode()
    with zipfile.ZipFile(archive, 'w') as z:
        for name, raw in files.items():
            z.writestr(name, raw)
    with pytest.raises(ValueError):
        restore_backup(archive, tmp_path / 'restored')
    assert not (tmp_path / 'restored').exists()
    assert not (tmp_path / 'escape').exists()


def test_schema_upgrade_and_future_version_rejection(tmp_path):
    path = tmp_path / 'data.sqlite3'
    Store(path)
    with sqlite3.connect(path) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 1
        db.execute('PRAGMA user_version=99')
    with pytest.raises(StateConflict, match='newer'):
        Store(path)


def test_retention_previews_and_preserves_records_pending_tasks_and_cleanup(tmp_path):
    from bodybrain.retention import prune_history
    app = app_at(tmp_path / 'data')
    store = app.state.service.store
    tasks = [('done', 'completed'), ('running', 'pending'), ('cleanup', 'completed')]
    with store.connect() as db:
        for task_id, status in tasks:
            db.execute('INSERT INTO tasks VALUES (?, ?)', (task_id, json.dumps({'id': task_id, 'status': status, 'created_at': '2020-01-01T00:00:00+00:00'})))
        db.execute('INSERT INTO relay_jobs VALUES (?, ?)', ('cleanup', '{}'))
    preview = prune_history(store, 30)
    assert preview['tasks'] == 1 and not preview['applied']
    assert store.task('done')
    assert prune_history(store, 30, True)['tasks'] == 1
    assert not store.task('done')
    assert store.task('running') and store.task('cleanup')
