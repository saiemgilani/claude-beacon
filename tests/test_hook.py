"""Hook: atomic state write, daemon-alive check, detached spawn."""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from claude_beacon import hook


def test_write_state_atomic_creates_file(tmp_path):
    state = tmp_path / "state"
    hook.write_state_atomic(state, "working")
    assert state.read_text() == "working"


def test_write_state_atomic_overwrites_existing(tmp_path):
    state = tmp_path / "state"
    state.write_text("old")
    hook.write_state_atomic(state, "input")
    assert state.read_text() == "input"


def test_write_state_atomic_leaves_no_tmp(tmp_path):
    state = tmp_path / "state"
    hook.write_state_atomic(state, "idle")
    siblings = list(tmp_path.iterdir())
    # Exactly one file: the state file itself.
    assert len(siblings) == 1, f"leftover files: {siblings}"


def test_daemon_alive_returns_false_when_no_pid_file(tmp_path):
    assert hook.daemon_alive(tmp_path / "no-pid") is False


def test_daemon_alive_returns_false_for_dead_pid(tmp_path):
    pid_file = tmp_path / "pid"
    pid_file.write_text("99999999")  # unlikely to exist
    assert hook.daemon_alive(pid_file) is False


def test_daemon_alive_returns_true_for_self_pid(tmp_path):
    pid_file = tmp_path / "pid"
    pid_file.write_text(str(os.getpid()))
    assert hook.daemon_alive(pid_file) is True


@patch("claude_beacon.hook.subprocess.Popen")
def test_spawn_daemon_uses_python_module_invocation(mock_popen, tmp_path):
    mock_popen.return_value = MagicMock(pid=12345)
    log_file = tmp_path / "daemon.log"
    pid_file = tmp_path / "daemon.pid"

    pid = hook.spawn_daemon_detached(log_file=log_file, pid_file=pid_file)

    assert pid == 12345
    assert pid_file.read_text().strip() == "12345"
    args, _ = mock_popen.call_args
    cmd = args[0]
    # First arg is sys.executable; remaining args are ["-m", "claude_beacon", "daemon"]
    assert cmd[1:] == ["-m", "claude_beacon", "daemon"]
