"""Shared pytest fixtures."""

from typing import Any

import pytest

from claude_beacon.adapters.base import DeviceError
from claude_beacon.state import State


class FakeAdapter:
    """In-memory DeviceAdapter for testing the daemon and integration code.

    - Records every connect/apply_state/health_check/close call in `calls`.
    - `fail_next_apply` makes the NEXT apply_state raise DeviceError.
    - `fail_next_connect` similar.
    - `health_ok` controls health_check return value (default True).
    """

    name = "fake"

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.fail_next_apply = False
        self.fail_next_connect = False
        self.health_ok = True
        self.connected = False

    async def connect(self) -> None:
        self.calls.append(("connect", None))
        if self.fail_next_connect:
            self.fail_next_connect = False
            raise DeviceError("synthetic connect failure")
        self.connected = True

    async def apply_state(self, state: State) -> None:
        self.calls.append(("apply", state))
        if self.fail_next_apply:
            self.fail_next_apply = False
            raise DeviceError("synthetic apply failure")

    async def health_check(self) -> bool:
        self.calls.append(("health", None))
        return self.health_ok

    async def close(self) -> None:
        self.calls.append(("close", None))
        self.connected = False


@pytest.fixture
def fake_adapter() -> FakeAdapter:
    return FakeAdapter()
