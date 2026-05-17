"""Claude Code hook entrypoint: atomic state write + daemon spawn."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def write_state_atomic(state_file: Path, value: str) -> None:
    """Write `value` to state_file atomically via tmp+rename."""
    state_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = state_file.with_name(state_file.name + ".tmp")
    tmp.write_text(value, encoding="utf-8")
    os.replace(tmp, state_file)


def daemon_alive(pid_file: Path) -> bool:
    """True if pid_file exists and the recorded PID points to a live process."""
    if not pid_file.exists():
        return False
    try:
        pid = int(pid_file.read_text().strip())
    except (ValueError, OSError):
        return False
    return _pid_alive(pid)


if sys.platform == "win32":
    def _pid_alive(pid: int) -> bool:
        # On Windows, OpenProcess can be used to test liveness, but for the
        # cost of a subprocess call here we use tasklist for simplicity.
        try:
            r = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}"],
                capture_output=True, text=True, check=False, timeout=2,
            )
        except Exception:
            return False
        return str(pid) in r.stdout
else:
    def _pid_alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False


def spawn_daemon_detached(*, log_file: Path, pid_file: Path) -> int:
    """Spawn `python -m claude_beacon daemon` fully detached. Returns the new PID.

    Writes pid_file unconditionally; the daemon will overwrite it once it
    acquires its own lock (so a crash-before-lock is detectable)."""
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_fp = open(log_file, "ab")

    try:
        if sys.platform == "win32":
            creationflags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            proc = subprocess.Popen(
                [sys.executable, "-m", "claude_beacon", "daemon"],
                creationflags=creationflags,
                stdin=subprocess.DEVNULL,
                stdout=log_fp, stderr=subprocess.STDOUT,
                close_fds=True,
            )
        else:
            proc = subprocess.Popen(
                [sys.executable, "-m", "claude_beacon", "daemon"],
                start_new_session=True,
                stdin=subprocess.DEVNULL,
                stdout=log_fp, stderr=subprocess.STDOUT,
                close_fds=True,
            )
    finally:
        # Subprocess has its own dup of the fd; parent must close to avoid leak.
        log_fp.close()

    pid_file.write_text(str(proc.pid))
    return proc.pid
