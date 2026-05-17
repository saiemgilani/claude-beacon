"""CLI: click subcommands. Smoke-level for skeleton; per-subcommand
behavior tested as those features land."""

from click.testing import CliRunner

from claude_beacon.cli import main


def test_help_lists_all_subcommands():
    r = CliRunner().invoke(main, ["--help"])
    assert r.exit_code == 0
    for sub in ("hook", "daemon", "scan", "status", "setup"):
        assert sub in r.output


def test_hook_writes_state_and_exits_zero(tmp_path, monkeypatch):
    # Redirect runtime_paths to tmp_path for isolation.
    import claude_beacon.runtime_paths as rp
    monkeypatch.setattr(rp, "STATE_FILE", tmp_path / "state")
    monkeypatch.setattr(rp, "PID_FILE", tmp_path / "pid")
    monkeypatch.setattr(rp, "LOG_FILE", tmp_path / "log")

    # daemon_alive returns False -> hook tries to spawn. Mock that.
    monkeypatch.setattr("claude_beacon.hook.spawn_daemon_detached",
                        lambda **k: 99999)

    r = CliRunner().invoke(main, ["hook", "working"])
    assert r.exit_code == 0
    assert (tmp_path / "state").read_text() == "working"


def test_hook_rejects_unknown_state():
    r = CliRunner().invoke(main, ["hook", "blinking"])
    assert r.exit_code != 0
    assert "blinking" in r.output or "invalid" in r.output.lower()


def test_status_shows_pid_when_running(tmp_path, monkeypatch):
    import claude_beacon.runtime_paths as rp
    pid_file = tmp_path / "pid"
    pid_file.write_text("12345")
    monkeypatch.setattr(rp, "PID_FILE", pid_file)
    monkeypatch.setattr("claude_beacon.hook.daemon_alive", lambda p: True)

    r = CliRunner().invoke(main, ["status"])
    assert r.exit_code == 0
    assert "12345" in r.output
    assert "running" in r.output.lower()


def test_status_reports_not_running(tmp_path, monkeypatch):
    import claude_beacon.runtime_paths as rp
    monkeypatch.setattr(rp, "PID_FILE", tmp_path / "nope")
    monkeypatch.setattr("claude_beacon.hook.daemon_alive", lambda p: False)

    r = CliRunner().invoke(main, ["status"])
    assert r.exit_code == 0
    assert "not running" in r.output.lower()
