"""Install/uninstall the user's macOS login service. Does not require root."""
import argparse
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
LABEL = 'local.bodybrain.app'
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--uninstall', action='store_true')
args = parser.parse_args()
path = Path.home() / 'Library/LaunchAgents' / f'{LABEL}.plist'
domain = f'gui/{os.getuid()}'
if args.uninstall:
    subprocess.run(['launchctl', 'bootout', f'{domain}/{LABEL}'], check=False, capture_output=True)
    path.unlink(missing_ok=True)
    print('BodyBrain login service removed. Records and backups retained.')
else:
    node = shutil.which('node')
    if not node or not (ROOT / 'dist/index.html').exists():
        parser.error('Install Node and run npm run build first')
    # launchd opens log paths and enters WorkingDirectory before Python runs.
    # macOS can deny launchd access to Documents even when Python itself has
    # permission to read this project. Start outside Documents; the supervisor
    # enters ROOT after Python starts, and records remain in their original place.
    logs = Path.home() / 'Library/Logs/BodyBrain'
    logs.mkdir(parents=True, exist_ok=True, mode=0o700)
    for name in ('stdout.log', 'stderr.log'):
        log = logs / name
        if not log.exists(): log.touch(mode=0o600)
        log.chmod(0o600)
    payload = {
        'Label': LABEL, 'ProgramArguments': [str(ROOT / 'backend/.venv/bin/python'), str(ROOT / 'scripts/local-service.py')],
        'WorkingDirectory': '/private/tmp', 'RunAtLoad': True, 'KeepAlive': True,
        'ThrottleInterval': 10, 'ExitTimeOut': 35,
        'StandardOutPath': str(logs / 'stdout.log'), 'StandardErrorPath': str(logs / 'stderr.log'),
        'EnvironmentVariables': {'PATH': f'{Path(node).parent}:/usr/bin:/bin:/usr/sbin:/sbin', 'PYTHONUNBUFFERED': '1'},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('wb') as stream: plistlib.dump(payload, stream)
    path.chmod(0o600)
    subprocess.run(['launchctl', 'bootout', f'{domain}/{LABEL}'], check=False, capture_output=True)
    try:
        subprocess.run(['launchctl', 'bootstrap', domain, str(path)], check=True)
        # Registration can succeed even when macOS refuses to execute Python.
        # Require the same supervisor PID to remain running before reporting success.
        previous_pid, stable_checks = None, 0
        for _ in range(15):
            time.sleep(1)
            state = subprocess.run(['launchctl', 'print', f'{domain}/{LABEL}'], capture_output=True, text=True)
            pid = re.search(r'^\s*pid = (\d+)\s*$', state.stdout, re.MULTILINE)
            running = re.search(r'^\s*state = running\s*$', state.stdout, re.MULTILINE)
            current_pid = pid.group(1) if pid and running and state.returncode == 0 else None
            stable_checks = stable_checks + 1 if current_pid and current_pid == previous_pid else 0
            previous_pid = current_pid
            if stable_checks >= 3:
                try:
                    # Process registration alone can hide broken child startup.
                    for url in ('http://127.0.0.1:8080/api/health', 'http://127.0.0.1:3016/'):
                        with urlopen(url, timeout=1) as response:
                            if response.status != 200:
                                raise OSError('Local endpoint is not ready')
                    break
                except OSError:
                    continue
        else:
            raise RuntimeError('The registered service did not remain running')
    except (subprocess.CalledProcessError, RuntimeError):
        subprocess.run(['launchctl', 'bootout', f'{domain}/{LABEL}'], check=False, capture_output=True)
        path.unlink(missing_ok=True)
        parser.exit(1, f'Login startup could not be verified; the failed registration was removed. Check macOS launch permissions and {logs}. You can still run scripts/local-service.py in a terminal.\n')
    print('BodyBrain login supervisor, UI and API are running. A login/reboot recovery check is still required.')
