"""State enum and helpers shared across hook, daemon, and adapters."""

from enum import Enum


class State(str, Enum):
    """The four states a Claude Code session can be in."""

    OFF = "off"
    IDLE = "idle"
    WORKING = "working"
    INPUT = "input"


import sys
from typing import IO


class LockHeldError(RuntimeError):
    """Another process holds the lock."""


if sys.platform == "win32":
    import msvcrt

    def acquire_lock(fp: IO) -> None:
        """Acquire exclusive non-blocking lock on the first byte of fp."""
        try:
            msvcrt.locking(fp.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as e:
            raise LockHeldError(str(e)) from e
else:
    import fcntl

    def acquire_lock(fp: IO) -> None:
        """Acquire exclusive non-blocking lock on fp."""
        try:
            fcntl.flock(fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            raise LockHeldError(str(e)) from e
