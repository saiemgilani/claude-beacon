"""DeviceAdapter Protocol and shared exceptions."""

from typing import Protocol, runtime_checkable

from ..state import State


class DeviceError(Exception):
    """Adapter could not apply the requested state. Daemon will retry/reconnect."""


@runtime_checkable
class DeviceAdapter(Protocol):
    """Contract for a device that displays Claude Code's state.

    Lifecycle (owned by the daemon, not the adapter):
        1. await adapter.connect() once at startup.
        2. Loop: on state change, await adapter.apply_state(new_state).
        3. On DeviceError: log -> adapter.close() -> adapter.connect() with backoff.
        4. Periodic health_check; on False, schedule reconnect.
        5. On idle timeout or State.OFF: apply_state(OFF) -> close() -> exit.
    """

    name: str

    async def connect(self) -> None:
        """Open the device connection. Raises DeviceError on failure."""
        ...

    async def apply_state(self, state: State) -> None:
        """Apply the new state. Raises DeviceError on failure."""
        ...

    async def health_check(self) -> bool:
        """Cheap (sub-100ms) check that the connection is still good.
        MAY do a network probe. Returning False triggers daemon reconnect."""
        ...

    async def close(self) -> None:
        """Tear down the connection. Idempotent. Never raises."""
        ...
