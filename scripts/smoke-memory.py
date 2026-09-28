"""Verify Cognee indexing, source-linked retrieval, and scoped synthetic cleanup."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from bodybrain.config import Settings
from bodybrain.cognee_memory import CogneeMemory


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cleanup-only', type=Path)
    args = parser.parse_args()
    settings = Settings()
    if settings.cognee_mode != 'rest':
        parser.error('This check requires configured Cognee REST memory')
    parent = ROOT / '.runtime/clawmax-deploy'
    parent.mkdir(parents=True, exist_ok=True)
    os.umask(0o077)
    if args.cleanup_only:
        state = args.cleanup_only.resolve()
        checks = json.loads((state / 'memory-smoke.json').read_text())
    else:
        state = Path(tempfile.mkdtemp(prefix='memory-smoke-', dir=parent))
        checks = {'dataset': 'bodybrain_smoke_' + uuid.uuid4().hex[:16],
                  'document_id': 'smoke_' + uuid.uuid4().hex, 'status': 'running'}
    memory = CogneeMemory('rest', base_url=settings.cognee_url, api_key=settings.cognee_api_key,
                          bearer_token=settings.cognee_token, dataset=checks['dataset'])
    if args.cleanup_only and checks.get('target') != memory.target_identity:
        parser.error('The configured Cognee target has changed; cleanup was not attempted')
    checks.update(target=memory.target_identity, state_dir=str(state))

    def save(stage, **values):
        checks.update(stage=stage, **values)
        (state / 'memory-smoke.json').write_text(json.dumps(checks, indent=2) + '\n')
        print(json.dumps({'stage': stage, **values}), flush=True)

    save('starting')
    try:
        if not args.cleanup_only:
            result = await memory.remember(checks['document_id'], 'Synthetic test: No fracture of the left femur.', {'synthetic': True})
            save('indexed', indexed=result['status'] == 'indexed')
            recalled = await memory.recall('What does the synthetic source document about the left femur?')
            if checks['document_id'] not in recalled['document_ids']:
                raise RuntimeError('Cognee did not return the synthetic source identity')
            save('validated', status='validated', source_retrieved=True)
    except Exception as exc:
        save('failed', status='failed', error_type=type(exc).__name__, error_code=getattr(exc, 'code', None))
    finally:
        try:
            result = await memory.forget(checks['document_id'])
            confirmed = await memory.forget(checks['document_id'])
            if confirmed['status'] != 'not_found':
                raise RuntimeError('The synthetic file still appears in Cognee after deletion')
            save('cleanup_complete', cleanup=result['status'], cleanup_confirmed=True,
                 status='passed' if checks['status'] == 'validated' else checks['status'])
        except Exception as exc:
            save('cleanup_pending', cleanup_error_type=type(exc).__name__, cleanup_error_code=getattr(exc, 'code', None))
    return 0 if checks['status'] == 'passed' and checks['stage'] == 'cleanup_complete' else 1


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
