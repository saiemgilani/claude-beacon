"""Daemon loop: poll state file, dispatch to adapter, handle reconnect."""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from .adapters.base import DeviceAdapter, DeviceError
from .config import DaemonConfig
from .state import State

log = logging.getLogger("claude_beacon.daemon")


def _read_state(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""


async def _reconnect(adapter: DeviceAdapter, backoff_s: tuple[int, ...]) -> bool:
    """Try to reconnect with exponential backoff. Returns True on success,
    False if every attempt failed."""
    await adapter.close()
    for delay in backoff_s:
        await asyncio.sleep(delay)
        try:
            await adapter.connect()
            log.info("reconnected after %ss backoff", delay)
            return True
        except DeviceError as e:
            log.warning("reconnect attempt failed: %s", e)
    return False


async def run_state_machine(
    adapter: DeviceAdapter,
    state_file: Path,
    cfg: DaemonConfig,
    *,
    shutdown: asyncio.Event | None = None,
) -> None:
    """Main loop. Behaviors:
       - Poll state_file every cfg.tick_ms; apply on transition.
       - Suppress WORKING transitions within cfg.debounce_ms of IDLE.
       - Periodically call adapter.health_check; reconnect on False.
       - Exit on State.OFF, idle timeout, or shutdown event.
    """
    shutdown = shutdown or asyncio.Event()
    current = ""
    last_idle_at = 0.0
    last_health = 0.0
    tick_s = cfg.tick_ms / 1000
    debounce_s = cfg.debounce_ms / 1000

    def health_interval() -> int:
        if current == State.WORKING.value:
            return cfg.health_interval_working_s
        return cfg.health_interval_idle_s

    while not shutdown.is_set():
        now = time.monotonic()
        desired = _read_state(state_file)

        # Debounce: ignore idle->working flap within window.
        if (
            desired == State.WORKING.value
            and current == State.IDLE.value
            and (now - last_idle_at) < debounce_s
        ):
            await asyncio.sleep(tick_s)
            continue

        # Apply state change.
        if desired and desired != current:
            try:
                await adapter.apply_state(State(desired))
                current = desired
                if current == State.IDLE.value:
                    last_idle_at = now
                if current == State.OFF.value:
                    break
            except DeviceError as e:
                log.error("apply_state(%s) failed: %s - reconnecting", desired, e)
                if not await _reconnect(adapter, cfg.reconnect_backoff_s):
                    log.error("reconnect exhausted; backoff loop will retry")
            except ValueError:
                log.warning("ignoring unknown state %r", desired)

        # Periodic health check.
        if (now - last_health) >= health_interval():
            try:
                ok = await adapter.health_check()
            except Exception as e:
                log.warning("health_check raised: %s", e)
                ok = False
            last_health = now
            if not ok:
                log.warning("health_check returned False - reconnecting")
                await _reconnect(adapter, cfg.reconnect_backoff_s)

        # Idle timeout.
        if (
            current == State.IDLE.value
            and (now - last_idle_at) >= cfg.idle_timeout_s
        ):
            log.info("idle timeout (%ss) reached, sending OFF and exiting",
                     cfg.idle_timeout_s)
            try:
                await adapter.apply_state(State.OFF)
            except DeviceError:
                pass
            break

        await asyncio.sleep(tick_s)
