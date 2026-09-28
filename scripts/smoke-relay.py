"""Synthetic hosted relay check; leaves private state available for cleanup retries."""
import argparse
import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--cleanup-only', type=Path)
parser.add_argument('--with-memory', action='store_true', help='Also verify real Cognee indexing and source-linked retrieval in a new synthetic-only dataset.')
args = parser.parse_args()
if args.cleanup_only and args.with_memory:
    parser.error('Cleanup uses the memory setting saved in its existing state')
state_root = ROOT / '.runtime/clawmax-deploy'
state_root.mkdir(parents=True, exist_ok=True)
state = args.cleanup_only.resolve() if args.cleanup_only else Path(tempfile.mkdtemp(prefix='relay-smoke-', dir=state_root))
if args.cleanup_only and not (state / 'smoke-state.json').is_file():
    parser.error('Cleanup requires an existing smoke state directory')
os.environ['BODYBRAIN_DATA_DIR'] = str(state)
sys.path.insert(0, str(ROOT / 'backend'))

import httpx
from bodybrain.config import Settings
from bodybrain.cognee_memory import CogneeMemory
from bodybrain.main import create_app

checks = json.loads((state / 'smoke-state.json').read_text()) if args.cleanup_only else {'status': 'running', 'state_dir': str(state)}
checks['state_dir'] = str(state)
if args.with_memory:
    checks['memory_dataset'] = 'bodybrain_smoke_' + uuid.uuid4().hex[:16]
result_path = state_root / ('full-smoke-result.json' if checks.get('memory_dataset') else 'relay-smoke-result.json')

def save(stage, **values):
    checks.update(stage=stage, **values)
    raw = json.dumps(checks, indent=2) + '\n'
    for path in (state / 'smoke-state.json', result_path):
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write(raw)
    print(json.dumps({'stage': stage, **values}), flush=True)

async def main():
    settings = replace(Settings(), data_dir=state, clawmax_transport='cognee_relay', agent_token='', api_token='', allowed_hosts=('testserver', 'localhost', '127.0.0.1'))
    if checks.get('memory_dataset'):
        if settings.cognee_mode != 'rest':
            raise RuntimeError('The full smoke requires configured Cognee REST memory')
        settings = replace(settings, cognee_dataset=checks['memory_dataset'])
    app = create_app(settings, memory=None if checks.get('memory_dataset') else CogneeMemory('disabled'))
    service = app.state.service
    save('starting')
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver', timeout=120) as client:
            async def wait_task(task_id):
                deadline = time.monotonic() + 420
                while time.monotonic() < deadline:
                    task = service.store.task(task_id)
                    if task and task['status'] != 'pending':
                        return task
                    await asyncio.sleep(5)
                raise TimeoutError('Hosted task timed out')
            try:
                if not args.cleanup_only:
                    heartbeat = await service.relay.health()
                    save('heartbeat', worker_online=heartbeat.get('worker_online', False))
                    if not heartbeat.get('worker_online'):
                        raise RuntimeError('No recent hosted worker heartbeat')
                    response = await client.post('/api/records/text', json={'title': 'Synthetic automatic relay check', 'text': 'No fracture of the left femur.', 'allow_agent': True})
                    response.raise_for_status()
                    record = response.json()
                    checks['record_id'] = record['id']
                    await asyncio.gather(*list(service.jobs))
                    task = service.store.ingestion_task(record['id'])
                    if not task:
                        raise RuntimeError('Synthetic ingestion not dispatched')
                    save('ingestion_submitted', ingestion_task=task['id'])
                    ingested = await wait_task(task['id'])
                    save('ingestion_result', ingestion={'status': ingested['status'], 'execution': ingested.get('worker_execution')})
                    assert ingested['status'] == 'completed', 'Hosted ingestion did not complete'
                    current = service.store.get(record['id'])
                    assert current['status'] == 'pending_review' and current['extraction_mode'] == 'clawmax_agent'
                    assert any(f['quote'] == 'No fracture of the left femur.' for f in current['findings'])
                    approved = await client.post(f"/api/records/{record['id']}/approve", json={})
                    approved.raise_for_status()
                    if checks.get('memory_dataset'):
                        deadline = time.monotonic() + 300
                        while time.monotonic() < deadline:
                            indexed = service.store.get(record['id'])
                            if indexed['memory_status'] == 'indexed':
                                break
                            if indexed['memory_status'] in {'failed', 'unconfigured'}:
                                raise RuntimeError('Cognee indexing did not complete')
                            await asyncio.sleep(2)
                        else:
                            raise TimeoutError('Cognee indexing timed out')
                        recalled = await service.memory.recall('What does the source say about the left femur?')
                        assert record['id'] in recalled['document_ids'], 'Cognee recall did not return the synthetic document identity'
                        save('memory_validated', cognee_indexed=True, cognee_source_retrieved=True)
                    answer = await client.post('/api/chat', json={'question': 'What does this report document about the left femur?', 'allow_agent': True})
                    answer.raise_for_status()
                    if checks.get('memory_dataset'):
                        assert answer.json()['retrieval_mode'] == 'cognee', 'Chat fell back instead of using Cognee retrieval'
                    evidence_id = answer.json()['agent_task_id']
                    assert evidence_id, 'No evidence task dispatched'
                    save('evidence_submitted', evidence_task=evidence_id)
                    answered = await wait_task(evidence_id)
                    save('evidence_result', evidence={'status': answered['status'], 'execution': answered.get('worker_execution')})
                    assert answered['status'] == 'completed', 'Hosted evidence did not complete'
                    result = answered['result']
                    assert result['verification'] == 'exact_source_quotes'
                    assert result['citations'] and result['citations'][0]['quote'] == 'No fracture of the left femur.', 'Expected exact citation missing'
                    save('validated', status='validated', human_review_preserved=True, exact_citations=True)
            except Exception as exc:
                save('failed', status='failed', error_type=type(exc).__name__)
            finally:
                try:
                    for record in service.store.records():
                        await service.delete_record(record['id'])
                    await service.relay_tick()
                    for job in service.store.relay_jobs():
                        # Cleanup verifies scoped remote removal; tombstones remain
                        # until expiry so cleanup-only can remove late uploads too.
                        await service.relay.cleanup(job['task'])
                    assert not service.store.records()
                    save('cleanup_complete', synthetic_records_removed=True, status='passed' if checks['status'] == 'validated' else checks['status'])
                except Exception as exc:
                    save('cleanup_pending', cleanup_error_type=type(exc).__name__)
                    if checks.get('memory_dataset') and checks.get('record_id'):
                        try:
                            await service.memory.forget(checks['record_id'])
                            save('cleanup_pending', cognee_document_cleanup=True)
                        except Exception as memory_exc:
                            save('cleanup_pending', cognee_document_cleanup=False, memory_cleanup_error_type=type(memory_exc).__name__)
    return 0 if checks['status'] == 'passed' and checks['stage'] == 'cleanup_complete' else 1

if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
