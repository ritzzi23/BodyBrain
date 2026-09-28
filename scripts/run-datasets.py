"""Run two isolated dataset sample apps, without touching the normal workspace."""
import fcntl
import json
import os
import shutil
import signal
import socket
import subprocess
import time

from dataset_env import ROOT, LABS, local_environment


def main():
    node = shutil.which('node')
    if not node or not (ROOT / 'dist/index.html').is_file():
        raise SystemExit('Run npm install and npm run build first.')
    for dataset in ('synthea', 'fitbit'):
        marker = LABS / dataset / 'dataset.json'
        if not marker.is_file() or json.loads(marker.read_text())['dataset'] != dataset:
            raise SystemExit('Run npm run datasets:prepare first.')
    lock_path = ROOT / '.runtime/datasets/server.lock'
    with os.fdopen(os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600), 'w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('The dataset apps are already running.')
        for port in (3018, 3019, 8083, 8084):
            with socket.socket() as probe:
                try: probe.bind(('127.0.0.1', port))
                except OSError: raise SystemExit(f'Port {port} is occupied; stop its existing server before starting the dataset apps.')
        children, stopping = [], False
        def stop(*_):
            nonlocal stopping
            stopping = True
        signal.signal(signal.SIGINT, stop)
        signal.signal(signal.SIGTERM, stop)
        try:
            for dataset, api, ui in [('synthea', 8083, 3018), ('fitbit', 8084, 3019)]:
                env = local_environment(dataset, api, ui)
                commands = [
                    [str(ROOT / 'backend/.venv/bin/python'), '-m', 'uvicorn', 'bodybrain.main:app', '--app-dir', 'backend', '--host', '127.0.0.1', '--port', str(api), '--no-access-log'],
                    [node, str(ROOT / 'node_modules/vite/bin/vite.js'), 'preview', '--host', '127.0.0.1', '--port', str(ui), '--strictPort'],
                ]
                for command in commands:
                    children.append(subprocess.Popen(command, cwd=ROOT, env=env))
                print(f'{dataset.title()} sample: http://127.0.0.1:{ui} — human review required; providers disabled.', flush=True)
            while not stopping and all(child.poll() is None for child in children):
                time.sleep(0.5)
            if not stopping:
                raise SystemExit('A dataset server exited. All sample servers were stopped; inspect the error above.')
        finally:
            for child in children:
                if child.poll() is None: child.terminate()
            for child in children:
                try: child.wait(timeout=15)
                except subprocess.TimeoutExpired: child.kill(); child.wait()


if __name__ == '__main__':
    main()
