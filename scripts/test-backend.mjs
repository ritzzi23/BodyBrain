import { spawnSync } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

// main.py creates its default application at import time, before pytest fixtures.
// Keep even that application away from the user's records and provider settings.
const dataDir = mkdtempSync(join(tmpdir(), 'bodybrain-tests-'));
const python = process.platform === 'win32' ? 'backend/.venv/Scripts/python.exe' : 'backend/.venv/bin/python';
try {
  const result = spawnSync(python, ['-m', 'pytest', 'backend/tests', '-q', ...process.argv.slice(2)], {
    stdio: 'inherit',
    env: {
      ...process.env,
      PYTHON_DOTENV_DISABLED: '1',
      BODYBRAIN_DATA_DIR: dataDir,
      BODYBRAIN_API_TOKEN: '', BODYBRAIN_AGENT_TOKEN: '',
      BODYBRAIN_ALLOWED_HOSTS: 'localhost,127.0.0.1,testserver',
      BODYBRAIN_ALLOWED_ORIGINS: 'http://127.0.0.1:3016,http://localhost:3016,http://127.0.0.1:8080,http://localhost:8080',
      COGNEE_MODE: 'disabled', COGNEE_URL: '', COGNEE_API_KEY: '', COGNEE_BEARER_TOKEN: '',
      CLAWMAX_URL: '', CLAWMAX_TOKEN: '', CLAWMAX_INGEST_WORKFLOW_ID: '', CLAWMAX_EVIDENCE_WORKFLOW_ID: '',
      CLAWMAX_TRANSPORT: 'dashboard', CLAWMAX_RELAY_INBOX: 'bodybrain_test_jobs', CLAWMAX_RELAY_OUTBOX: 'bodybrain_test_results',
    },
  });
  if (result.error) console.error(result.error.message);
  process.exitCode = result.status ?? 1;
} finally {
  rmSync(dataDir, { recursive: true, force: true });
}
