"""State machine: detect state changes via state file, call adapter.apply_state."""

import asyncio
from pathlib import Path

import pytest

from claude_beacon.config import DaemonConfig
from claude_beacon.daemon import run_state_machine
from claude_beacon.state import State


async def _drive(adapter, state_file: Path, *, transitions: list[str],
                  tick_ms: int = 20, cfg: DaemonConfig | None = None) -> None:
    """Helper: write each transition to state_file, with tick_ms*3 between
    writes so the daemon polls each value. After the last transition, write
    "off" to trigger clean exit."""
    cfg = cfg or DaemonConfig(tick_ms=tick_ms, debounce_ms=0, idle_timeout_s=10_000)
    state_file.write_text("idle")

    async def write_sequence():
        await asyncio.sleep(tick_ms * 2 / 1000)
        for t in transitions:
            state_file.write_text(t)
            await asyncio.sleep(tick_ms * 3 / 1000)
        state_file.write_text("off")

    await asyncio.gather(
        run_state_machine(adapter, state_file, cfg),
        write_sequence(),
    )


# ----- T5a tests -----

@pytest.mark.asyncio
async def test_initial_state_triggers_apply(fake_adapter, tmp_path):
    state_file = tmp_path / "state"
    await _drive(fake_adapter, state_file, transitions=[])
    states = [s for op, s in fake_adapter.calls if op == "apply"]
    assert State.IDLE in states
    assert State.OFF in states


@pytest.mark.asyncio
async def test_state_change_triggers_apply(fake_adapter, tmp_path):
    state_file = tmp_path / "state"
    await _drive(fake_adapter, state_file, transitions=["working", "idle", "input"])
    states = [s for op, s in fake_adapter.calls if op == "apply"]
    assert State.WORKING in states
    assert State.INPUT in states


@pytest.mark.asyncio
async def test_same_state_does_not_re_apply(fake_adapter, tmp_path):
    state_file = tmp_path / "state"
    await _drive(fake_adapter, state_file, transitions=["idle", "idle", "idle"])
    apply_count = sum(1 for op, _ in fake_adapter.calls if op == "apply")
    assert apply_count == 2


@pytest.mark.asyncio
async def test_off_state_exits_loop(fake_adapter, tmp_path):
    state_file = tmp_path / "state"
    state_file.write_text("off")
    cfg = DaemonConfig(tick_ms=20, debounce_ms=0, idle_timeout_s=10_000)
    await asyncio.wait_for(
        run_state_machine(fake_adapter, state_file, cfg),
        timeout=1.0,
    )


# ----- T5b tests: debounce, reconnect, health_check, idle timeout -----

@pytest.mark.asyncio
async def test_idle_to_working_debounce_filters_phantom(fake_adapter, tmp_path):
    """idle -> working transition within debounce_ms is suppressed."""
    state_file = tmp_path / "state"
    state_file.write_text("idle")
    cfg = DaemonConfig(tick_ms=20, debounce_ms=200, idle_timeout_s=10_000)

    async def writer():
        # Tick 0: daemon sees idle, applies it.
        await asyncio.sleep(0.05)
        # Tick 1: phantom 'working' within debounce window - should be ignored.
        state_file.write_text("working")
        await asyncio.sleep(0.08)
        # Now write OFF to terminate.
        state_file.write_text("off")

    await asyncio.gather(
        run_state_machine(fake_adapter, state_file, cfg),
        writer(),
    )
    states = [s for op, s in fake_adapter.calls if op == "apply"]
    assert State.WORKING not in states, f"working leaked through debounce: {states}"


@pytest.mark.asyncio
async def test_idle_to_working_after_debounce_window_succeeds(fake_adapter, tmp_path):
    """working transition AFTER debounce window applies normally."""
    state_file = tmp_path / "state"
    state_file.write_text("idle")
    cfg = DaemonConfig(tick_ms=20, debounce_ms=100, idle_timeout_s=10_000)

    async def writer():
        await asyncio.sleep(0.25)  # well past debounce
        state_file.write_text("working")
        await asyncio.sleep(0.1)
        state_file.write_text("off")

    await asyncio.gather(
        run_state_machine(fake_adapter, state_file, cfg),
        writer(),
    )
    states = [s for op, s in fake_adapter.calls if op == "apply"]
    assert State.WORKING in states


@pytest.mark.asyncio
async def test_apply_failure_triggers_reconnect(fake_adapter, tmp_path):
    """DeviceError from apply_state triggers close + connect."""
    state_file = tmp_path / "state"
    state_file.write_text("idle")
    cfg = DaemonConfig(
        tick_ms=20, debounce_ms=0, idle_timeout_s=10_000,
        reconnect_backoff_s=(0,),  # no sleep in test
    )

    fake_adapter.fail_next_apply = True

    async def writer():
        await asyncio.sleep(0.15)
        state_file.write_text("off")

    await asyncio.gather(
        run_state_machine(fake_adapter, state_file, cfg),
        writer(),
    )
    ops = [op for op, _ in fake_adapter.calls]
    assert "close" in ops, f"expected close after failure, got {ops}"
    assert "connect" in ops, f"expected connect after failure, got {ops}"


@pytest.mark.asyncio
async def test_health_check_called_periodically(fake_adapter, tmp_path):
    state_file = tmp_path / "state"
    state_file.write_text("idle")
    cfg = DaemonConfig(
        tick_ms=20, debounce_ms=0, idle_timeout_s=10_000,
        health_interval_idle_s=0,  # fire every tick during idle
    )

    async def writer():
        await asyncio.sleep(0.15)
        state_file.write_text("off")

    await asyncio.gather(
        run_state_machine(fake_adapter, state_file, cfg),
        writer(),
    )
    health_calls = [op for op, _ in fake_adapter.calls if op == "health"]
    assert len(health_calls) >= 2


@pytest.mark.asyncio
async def test_health_check_failure_triggers_reconnect(fake_adapter, tmp_path):
    state_file = tmp_path / "state"
    state_file.write_text("idle")
    cfg = DaemonConfig(
        tick_ms=20, debounce_ms=0, idle_timeout_s=10_000,
        health_interval_idle_s=0,
        reconnect_backoff_s=(0,),  # no backoff sleep in test
    )
    fake_adapter.health_ok = False

    async def writer():
        await asyncio.sleep(0.10)
        state_file.write_text("off")

    await asyncio.gather(
        run_state_machine(fake_adapter, state_file, cfg),
        writer(),
    )
    ops = [op for op, _ in fake_adapter.calls]
    assert ops.count("close") >= 1
    assert ops.count("connect") >= 1


@pytest.mark.asyncio
async def test_idle_timeout_sends_off_and_exits(fake_adapter, tmp_path):
    state_file = tmp_path / "state"
    state_file.write_text("idle")
    cfg = DaemonConfig(
        tick_ms=20, debounce_ms=0,
        idle_timeout_s=0,  # immediate timeout
    )

    # Don't write OFF - daemon should self-exit via timeout.
    await asyncio.wait_for(
        run_state_machine(fake_adapter, state_file, cfg),
        timeout=1.0,
    )
    states = [s for op, s in fake_adapter.calls if op == "apply"]
    assert State.OFF in states, f"expected OFF on timeout, got {states}"
