#!/usr/bin/env python3
"""Build a credential-free, hash-pinned hosted relay worker installer.

Only the explicitly named source modules and README enter the package. This
command never reads environment files, credentials, or worker state, and never
installs or launches the worker. Run the resulting installer on its target host.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
MODULE_PATHS = {
    "worker.py": HERE / "worker.py",
    "cognee_transport.py": REPO_ROOT / "backend/bodybrain/cognee_transport.py",
    "relay_protocol.py": REPO_ROOT / "backend/bodybrain/relay_protocol.py",
}


INSTALLER = r'''#!/usr/bin/env python3
"""Install this exact BodyBrain relay bundle and start its detached worker.

The worker inherits COGNEE_API_KEY from this process. No credential is read,
serialized, printed, or passed as an argument by this installer. This is a
single-installation launcher, not a service manager or restart supervisor.
"""
from __future__ import annotations

import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import time

EMBEDDED_FILES = __EMBEDDED_FILES__
SOURCE_HASHES = __SOURCE_HASHES__
KNOWN_FILES = frozenset({"worker.py", "cognee_transport.py", "relay_protocol.py", "config.json", "README.md", "manifest.json"})
STATE_FILES = ("worker.lock", "ledger.sqlite3", "ledger.sqlite3-journal", "ledger.sqlite3-wal", "ledger.sqlite3-shm")


class InstallError(Exception):
    """Fixed, non-sensitive installer errors only."""


def regular(path: Path, *, missing: bool = True):
    try:
        info = path.lstat()
    except FileNotFoundError:
        if missing:
            return
        raise InstallError("A required installation file is missing.") from None
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
        raise InstallError("A controlled file is not an owned, unlinked regular file.")


def directory(path: Path):
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        pass
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise InstallError("A controlled directory is not an owned directory.")


def open_private(path: Path, flags: int) -> int:
    regular(path)
    fd = os.open(path, flags | os.O_NOFOLLOW, 0o600)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
        os.close(fd)
        raise InstallError("A controlled file changed during installation.")
    return fd


def replace_private(path: Path, content: bytes):
    regular(path)
    fd, name = tempfile.mkstemp(prefix=".bodybrain-install-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as target:
            os.fchmod(target.fileno(), 0o600)
            target.write(content)
            target.flush()
            os.fsync(target.fileno())
        regular(path)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def decode_bundle() -> dict[str, bytes]:
    if set(EMBEDDED_FILES) != KNOWN_FILES:
        raise InstallError("The embedded bundle has unexpected files.")
    decoded = {}
    for name, item in EMBEDDED_FILES.items():
        if set(item) != {"base64", "sha256", "bytes"}:
            raise InstallError("The embedded bundle manifest is invalid.")
        try:
            content = base64.b64decode(item["base64"], validate=True)
        except (TypeError, ValueError):
            raise InstallError("The embedded bundle encoding is invalid.") from None
        if len(content) != item["bytes"] or hashlib.sha256(content).hexdigest() != item["sha256"]:
            raise InstallError("The embedded bundle hash check failed.")
        decoded[name] = content
    try:
        manifest = json.loads(decoded["manifest.json"])
        expected = {name: {"sha256": EMBEDDED_FILES[name]["sha256"], "bytes": len(content)}
                    for name, content in decoded.items() if name != "manifest.json"}
        if manifest != {"schema": "bodybrain.clawmax.worker.v1", "files": expected}:
            raise ValueError
        if SOURCE_HASHES != {name: expected[name]["sha256"] for name in ("worker.py", "cognee_transport.py", "relay_protocol.py")}:
            raise ValueError
    except (ValueError, TypeError, KeyError):
        raise InstallError("The embedded source manifest is invalid.") from None
    return decoded


def install() -> tuple[int, bool]:
    decoded = decode_bundle()  # Verify every byte before touching the host.
    os.umask(0o077)
    root = Path.home() / ".bodybrain-clawmax-relay"
    state = root / "state"
    directory(root)
    directory(state)
    for name in KNOWN_FILES | {"worker.log", "worker.pid"}:
        regular(root / name)
    for name in STATE_FILES:
        regular(state / name)

    lock_fd = open_private(state / "worker.lock", os.O_RDWR | os.O_CREAT)
    log_fd = None
    try:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise InstallError("A worker is active; stop it before reinstalling.") from None
        os.fchmod(lock_fd, 0o600)
        os.chmod(root, 0o700, follow_symlinks=False)
        os.chmod(state, 0o700, follow_symlinks=False)
        for name, content in decoded.items():
            replace_private(root / name, content)
        for name in STATE_FILES:
            if (state / name).exists():
                fd = open_private(state / name, os.O_RDWR)
                try:
                    os.fchmod(fd, 0o600)
                finally:
                    os.close(fd)
        # Re-read the installed bytes before launching; no cached modules used.
        for name, content in decoded.items():
            fd = open_private(root / name, os.O_RDONLY)
            with os.fdopen(fd, "rb") as installed:
                if hashlib.sha256(installed.read()).digest() != hashlib.sha256(content).digest():
                    raise InstallError("An installed source failed verification.")
        log_fd = open_private(root / "worker.log", os.O_WRONLY | os.O_CREAT | os.O_APPEND)
        os.fchmod(log_fd, 0o600)
    finally:
        # The worker takes this same lock itself. Never hold it across Popen.
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)
    try:
        worker = subprocess.Popen(
            [sys.executable, "-B", "-X", "pycache_prefix=/dev/null", str(root / "worker.py"),
             "--config", str(root / "config.json"), "--state-dir", str(state)],
            stdin=subprocess.DEVNULL, stdout=log_fd, stderr=log_fd,
            shell=False, close_fds=True, start_new_session=True, cwd=root,
        )  # env=None inherits the existing environment without reading its key.
    finally:
        if log_fd is not None:
            os.close(log_fd)
    replace_private(root / "worker.pid", (str(worker.pid) + "\n").encode("ascii"))
    time.sleep(1)
    return worker.pid, worker.poll() is None


def main() -> int:
    try:
        pid, alive = install()
    except InstallError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception:
        print("Worker installation failed; inspect the target host privately.", file=sys.stderr)
        return 1
    print(json.dumps({"installed": True, "pid": pid, "source_hashes": SOURCE_HASHES, "process_alive": alive}, sort_keys=True))
    return 0 if alive else 1


if __name__ == "__main__":
    raise SystemExit(main())
'''


def encoded_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def metadata(content: bytes) -> dict[str, str | int]:
    return {"sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)}


def build_artifacts(config: dict) -> dict[str, bytes]:
    files = {name: source.read_bytes() for name, source in MODULE_PATHS.items()}
    files["README.md"] = (HERE / "README.md").read_bytes()
    files["config.json"] = encoded_json(config)
    files["manifest.json"] = encoded_json({"schema": "bodybrain.clawmax.worker.v1", "files": {name: metadata(content) for name, content in files.items()}})
    embedded = {name: {"base64": base64.b64encode(content).decode("ascii"), **metadata(content)} for name, content in files.items()}
    source_hashes = {name: metadata(files[name])["sha256"] for name in MODULE_PATHS}
    installer = INSTALLER.replace("__EMBEDDED_FILES__", repr(embedded)).replace("__SOURCE_HASHES__", repr(source_hashes)).encode("utf-8")
    compile(installer, "installer.py", "exec")
    files["installer.py"] = installer
    files["artifact-manifest.json"] = encoded_json({"schema": "bodybrain.clawmax.worker.artifacts.v1", "files": {name: metadata(content) for name, content in files.items()}})
    return files


def write_artifacts(output: Path, files: dict[str, bytes]):
    output = output.absolute()
    # Reject symlinks anywhere in the controlled output path before creating it.
    for directory in [*reversed(output.parents), output]:
        if directory.is_symlink():
            raise ValueError("The output path must not contain symlinks.")
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    for name in files:
        target = output / name
        if target.is_symlink() or target.exists() and not stat.S_ISREG(target.lstat().st_mode):
            raise ValueError("An artifact path is not a regular file.")
    os.chmod(output, 0o700)
    for name, content in files.items():
        fd, temporary = tempfile.mkstemp(prefix=".bodybrain-package-", dir=output)
        try:
            with os.fdopen(fd, "wb") as target:
                os.fchmod(target.fileno(), 0o600)
                target.write(content)
            os.replace(temporary, output / name)
        finally:
            Path(temporary).unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="Cognee HTTPS base URL (no credentials, query, or fragment).")
    parser.add_argument("--inbox", default="bodybrain_clawmax_jobs")
    parser.add_argument("--outbox", default="bodybrain_clawmax_results")
    parser.add_argument("--model", default="lmstudio/gpt-4.1-mini")
    parser.add_argument("--ingestion-agent", default="bodybrain-ingestion")
    parser.add_argument("--evidence-agent", default="bodybrain-evidence")
    parser.add_argument("--output-dir", type=Path, default=REPO_ROOT / ".runtime/clawmax-deploy/relay")
    args = parser.parse_args()
    # Constructor-only validation performs no network calls and reads no keys.
    sys.path.insert(0, str(REPO_ROOT / "backend"))
    from bodybrain.cognee_transport import CogneeFiles, CogneeTransportError
    try:
        CogneeFiles(args.base_url)
        if any(not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", name) for name in (args.inbox, args.outbox)) or args.inbox == args.outbox:
            raise ValueError("Distinct valid relay dataset names are required.")
        if not re.fullmatch(r"[A-Za-z0-9_.:/-]{1,160}", args.model):
            raise ValueError("The model identifier is invalid.")
        if any(not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", value) for value in (args.ingestion_agent, args.evidence_agent)):
            raise ValueError("The registered agent identifiers are invalid.")
        config = {"base_url": args.base_url, "inbox_dataset": args.inbox, "outbox_dataset": args.outbox,
                  "model": args.model, "agents": {"ingestion": args.ingestion_agent, "evidence": args.evidence_agent}}
        artifacts = build_artifacts(config)
        write_artifacts(args.output_dir, artifacts)
    except (ValueError, OSError, CogneeTransportError):
        parser.error("Could not package the worker; check the nonsecret configuration and output paths.")
    print(json.dumps({"output_dir": str(args.output_dir.absolute()), "installer_sha256": metadata(artifacts["installer.py"])["sha256"],
                      "source_hashes": {name: metadata(artifacts[name])["sha256"] for name in MODULE_PATHS}}, sort_keys=True))


if __name__ == "__main__":
    main()
