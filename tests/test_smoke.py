"""Smoke test: package imports cleanly."""

import claude_beacon


def test_version_string():
    assert isinstance(claude_beacon.__version__, str)
    assert claude_beacon.__version__.count(".") >= 1
