"""Run the local UI and API, restarting a crashed child with bounded backoff."""
import os
import fcntl
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
state_dir = ROOT / '.runtime/local-service'
state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
lock = os.fdopen(os.open(state_dir / 'supervisor.lock', os.O_CREAT | os.O_RDWR, 0o600), 'w')
try:
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    raise SystemExit('A BodyBrain local supervisor is already running.')
node = shutil.which('node')
if not node or not (ROOT / 'dist/index.html').is_file():
    raise SystemExit('Install Node and run npm run build before starting the local service.')
commands = [
    [str(ROOT / 'backend/.venv/bin/python'), '-m', 'uvicorn', 'bodybrain.main:app', '--app-dir', 'backend', '--host', '127.0.0.1', '--port', '8080', '--no-access-log'],
    [node, str(ROOT / 'node_modules/vite/bin/vite.js'), 'preview', '--host', '127.0.0.1', '--port', '3016', '--strictPort'],
]
stopping = False
children = []
def stop(*_):
    global stopping
    stopping = True
signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
try:
    failures = 0
    while not stopping:
        start = time.monotonic()
        children = [subprocess.Popen(command) for command in commands]
        while not stopping and all(child.poll() is None for child in children):
            time.sleep(1)
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try: child.wait(timeout=15)
            except subprocess.TimeoutExpired: child.kill(); child.wait()
        if not stopping:
            failures = 0 if time.monotonic() - start > 60 else min(failures + 1, 5)
            delay = min(2 ** failures, 30)
            print(f'Local service child exited; retrying in {delay}s.', flush=True)
            for _ in range(delay):
                if stopping: break
                time.sleep(1)
finally:
    for child in children:
        if child.poll() is None:
            child.terminate()
