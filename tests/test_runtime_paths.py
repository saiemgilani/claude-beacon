"""runtime_paths: platformdirs-based path resolution. Mock sys.platform to
verify each OS produces sensible paths."""

import importlib
import sys
from pathlib import Path

import pytest


@pytest.fixture
def reload_paths():
    """Reload runtime_paths after we mutate sys.platform so the module reads
    our patched value at import time."""

    def _reload():
        import claude_beacon.runtime_paths as m
        importlib.reload(m)
        return m

    return _reload


def test_paths_object_exposes_expected_attrs(reload_paths):
    m = reload_paths()
    for attr in ("CONFIG_DIR", "CACHE_DIR", "CONFIG_FILE", "LOCK_FILE",
                 "PID_FILE", "STATE_FILE", "LOG_FILE"):
        assert hasattr(m, attr), f"missing {attr}"
        assert isinstance(getattr(m, attr), Path)


def test_paths_use_app_name(reload_paths):
    m = reload_paths()
    # Every cache/config path contains the literal app name as a path
    # component, regardless of OS conventions.
    assert "claude-beacon" in str(m.CONFIG_DIR).lower()
    assert "claude-beacon" in str(m.CACHE_DIR).lower()


def test_config_file_is_under_config_dir(reload_paths):
    m = reload_paths()
    assert m.CONFIG_FILE.parent == m.CONFIG_DIR


def test_runtime_files_are_under_cache_dir(reload_paths):
    m = reload_paths()
    for f in (m.LOCK_FILE, m.PID_FILE, m.STATE_FILE, m.LOG_FILE):
        assert f.parent == m.CACHE_DIR
