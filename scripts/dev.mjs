import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';

const python = process.platform === 'win32' ? 'backend/.venv/Scripts/python.exe' : 'backend/.venv/bin/python';
if (!existsSync(python)) {
  console.error('Install the backend first: uv sync --project backend --python 3.12');
  process.exit(1);
}
const children = [
  spawn(python, ['-m', 'uvicorn', 'bodybrain.main:app', '--app-dir', 'backend', '--host', '127.0.0.1', '--port', '8080'], { stdio: 'inherit' }),
  spawn(process.execPath, ['node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', '3016', '--strictPort'], { stdio: 'inherit' }),
];
let stopping = false;
function stop(code = 0) {
  if (stopping) return;
  stopping = true;
  for (const child of children) child.kill('SIGTERM');
  setTimeout(() => process.exit(code), 300).unref();
}
for (const child of children) {
  child.on('error', error => { console.error(error.message); stop(1); });
  child.on('exit', code => { if (!stopping) stop(code ?? 1); });
}
process.on('SIGINT', () => stop());
process.on('SIGTERM', () => stop());
