"""KasaAdapter: tested with python-kasa fully mocked via MagicMock."""

import asyncio
from collections import namedtuple
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from claude_beacon.adapters.base import DeviceError
from claude_beacon.adapters.kasa import KasaAdapter
from claude_beacon.config import KasaColors, KasaConfig
from claude_beacon.state import State

# Lightweight HSV namedtuple mimicking python-kasa's HSV type.
HSV = namedtuple("HSV", ["hue", "saturation", "value"])


def make_bulb(host: str, *, fail_set_hsv: bool = False, fail_update: bool = False,
              snap_is_on: bool = True, snap_hsv: tuple = (0, 0, 100),
              snap_color_temp: int = 2700, snap_brightness: int = 100) -> MagicMock:
    """Build a mock python-kasa Device with a Light module. Configurable
    snapshot values so tests can exercise restore behavior."""
    bulb = MagicMock()
    bulb.host = host
    bulb.is_on = snap_is_on
    bulb.update = AsyncMock(side_effect=Exception("dead") if fail_update else None)
    bulb.turn_on = AsyncMock()
    bulb.turn_off = AsyncMock()
    bulb.disconnect = AsyncMock()

    light = MagicMock()
    light.set_hsv = AsyncMock(side_effect=Exception("nope") if fail_set_hsv else None)
    light.set_color_temp = AsyncMock()
    light.set_brightness = AsyncMock()
    light.hsv = HSV(*snap_hsv)
    light.color_temp = snap_color_temp
    light.brightness = snap_brightness

    bulb.modules = MagicMock()
    bulb.modules.__getitem__ = MagicMock(return_value=light)
    bulb.light = light  # convenience pointer for assertions

    return bulb


@pytest.fixture
def cfg_single() -> KasaConfig:
    return KasaConfig(hosts=["192.168.1.42"], colors=KasaColors())


@pytest.fixture
def cfg_three() -> KasaConfig:
    return KasaConfig(
        hosts=["192.168.1.42", "192.168.1.43", "192.168.1.44"],
        colors=KasaColors(working_period_ms=100),
    )


@pytest.mark.asyncio
async def test_connect_single_bulb(cfg_single):
    bulb = make_bulb("192.168.1.42")
    with patch("claude_beacon.adapters.kasa.Device.connect",
               AsyncMock(return_value=bulb)):
        a = KasaAdapter(cfg_single)
        await a.connect()
        assert len(a.bulbs) == 1
        assert a.bulbs[0].host == "192.168.1.42"


@pytest.mark.asyncio
async def test_connect_all_fail_raises(cfg_single):
    with patch("claude_beacon.adapters.kasa.Device.connect",
               AsyncMock(side_effect=Exception("dead"))):
        a = KasaAdapter(cfg_single)
        with pytest.raises(DeviceError, match="no bulbs reachable"):
            await a.connect()


@pytest.mark.asyncio
async def test_connect_snapshots_original_state(cfg_single):
    """connect() should capture the bulb's pre-claude state for restore."""
    bulb = make_bulb("192.168.1.42", snap_is_on=True, snap_hsv=(120, 50, 80),
                      snap_color_temp=0, snap_brightness=80)
    with patch("claude_beacon.adapters.kasa.Device.connect",
               AsyncMock(return_value=bulb)):
        a = KasaAdapter(cfg_single)
        await a.connect()
        snap = a._snapshots["192.168.1.42"]
        assert snap["is_on"] is True
        assert snap["hsv"] == (120, 50, 80)
        assert snap["color_temp"] == 0


@pytest.mark.asyncio
async def test_apply_idle_calls_turn_on_then_set_hsv(cfg_single):
    bulb = make_bulb("192.168.1.42")
    with patch("claude_beacon.adapters.kasa.Device.connect",
               AsyncMock(return_value=bulb)):
        a = KasaAdapter(cfg_single)
        await a.connect()
        await a.apply_state(State.IDLE)
        bulb.turn_on.assert_awaited()
        bulb.light.set_hsv.assert_awaited_with(*cfg_single.colors.idle_hsv)


@pytest.mark.asyncio
async def test_apply_input_uses_input_hsv(cfg_single):
    bulb = make_bulb("192.168.1.42")
    with patch("claude_beacon.adapters.kasa.Device.connect",
               AsyncMock(return_value=bulb)):
        a = KasaAdapter(cfg_single)
        await a.connect()
        await a.apply_state(State.INPUT)
        bulb.light.set_hsv.assert_awaited_with(*cfg_single.colors.input_hsv)


@pytest.mark.asyncio
async def test_apply_off_restores_original_state_when_was_on(cfg_single):
    """OFF should restore the pre-claude state, not blackhole the bulb."""
    bulb = make_bulb("192.168.1.42", snap_is_on=True, snap_hsv=(0, 0, 100),
                      snap_color_temp=2700, snap_brightness=100)
    with patch("claude_beacon.adapters.kasa.Device.connect",
               AsyncMock(return_value=bulb)):
        a = KasaAdapter(cfg_single)
        await a.connect()
        await a.apply_state(State.OFF)
        # White-temp mode restoration path: set_color_temp + set_brightness
        bulb.turn_on.assert_awaited()
        bulb.light.set_color_temp.assert_awaited_with(2700)
        bulb.light.set_brightness.assert_awaited_with(100)
        # And critically NOT turned off
        bulb.turn_off.assert_not_awaited()


@pytest.mark.asyncio
async def test_apply_off_turns_off_when_was_off(cfg_single):
    """OFF on a bulb that was already off should leave it off."""
    bulb = make_bulb("192.168.1.42", snap_is_on=False)
    with patch("claude_beacon.adapters.kasa.Device.connect",
               AsyncMock(return_value=bulb)):
        a = KasaAdapter(cfg_single)
        await a.connect()
        await a.apply_state(State.OFF)
        bulb.turn_off.assert_awaited()


@pytest.mark.asyncio
async def test_apply_off_restores_color_mode_via_hsv(cfg_single):
    """OFF on a bulb that was in color mode (saturation > 0) should restore via set_hsv."""
    bulb = make_bulb("192.168.1.42", snap_is_on=True, snap_hsv=(180, 80, 60),
                      snap_color_temp=0, snap_brightness=60)
    with patch("claude_beacon.adapters.kasa.Device.connect",
               AsyncMock(return_value=bulb)):
        a = KasaAdapter(cfg_single)
        await a.connect()
        await a.apply_state(State.OFF)
        bulb.turn_on.assert_awaited()
        bulb.light.set_hsv.assert_awaited_with(180, 80, 60)


@pytest.mark.asyncio
async def test_close_restores_originals(cfg_single):
    """close() should also restore (covers daemon-shutdown-without-OFF cases)."""
    bulb = make_bulb("192.168.1.42", snap_is_on=True, snap_hsv=(60, 100, 100),
                      snap_color_temp=0)
    with patch("claude_beacon.adapters.kasa.Device.connect",
               AsyncMock(return_value=bulb)):
        a = KasaAdapter(cfg_single)
        await a.connect()
        await a.close()
        bulb.light.set_hsv.assert_awaited_with(60, 100, 100)


@pytest.mark.asyncio
async def test_apply_working_starts_animator(cfg_single):
    bulb = make_bulb("192.168.1.42")
    cfg = KasaConfig(hosts=cfg_single.hosts,
                      colors=KasaColors(working_period_ms=100))
    with patch("claude_beacon.adapters.kasa.Device.connect",
               AsyncMock(return_value=bulb)):
        a = KasaAdapter(cfg)
        await a.connect()
        await a.apply_state(State.WORKING)
        await asyncio.sleep(0.15)
        assert bulb.light.set_hsv.await_count >= 1
        await a.close()


@pytest.mark.asyncio
async def test_apply_state_change_cancels_animator(cfg_single):
    bulb = make_bulb("192.168.1.42")
    cfg = KasaConfig(hosts=cfg_single.hosts,
                      colors=KasaColors(working_period_ms=100))
    with patch("claude_beacon.adapters.kasa.Device.connect",
               AsyncMock(return_value=bulb)):
        a = KasaAdapter(cfg)
        await a.connect()
        await a.apply_state(State.WORKING)
        await asyncio.sleep(0.05)
        await a.apply_state(State.IDLE)
        await asyncio.sleep(0.15)
        assert a._animator is None or a._animator.done()


@pytest.mark.asyncio
async def test_multi_bulb_fanout_calls_each(cfg_three):
    b1 = make_bulb("192.168.1.42")
    b2 = make_bulb("192.168.1.43")
    b3 = make_bulb("192.168.1.44")
    bulbs = {b.host: b for b in (b1, b2, b3)}

    async def fake_connect(*, host, **_):
        return bulbs[host]

    with patch("claude_beacon.adapters.kasa.Device.connect",
               AsyncMock(side_effect=fake_connect)):
        a = KasaAdapter(cfg_three)
        await a.connect()
        assert len(a.bulbs) == 3
        await a.apply_state(State.IDLE)
        b1.light.set_hsv.assert_awaited()
        b2.light.set_hsv.assert_awaited()
        b3.light.set_hsv.assert_awaited()


@pytest.mark.asyncio
async def test_one_bulb_fails_does_not_raise(cfg_three):
    b1 = make_bulb("192.168.1.42")
    b2 = make_bulb("192.168.1.43", fail_set_hsv=True)
    b3 = make_bulb("192.168.1.44")
    bulbs = {b.host: b for b in (b1, b2, b3)}

    async def fake_connect(*, host, **_):
        return bulbs[host]

    with patch("claude_beacon.adapters.kasa.Device.connect",
               AsyncMock(side_effect=fake_connect)):
        a = KasaAdapter(cfg_three)
        await a.connect()
        await a.apply_state(State.IDLE)


@pytest.mark.asyncio
async def test_all_bulbs_fail_raises_device_error(cfg_three):
    bulbs_by_host = {
        "192.168.1.42": make_bulb("192.168.1.42", fail_set_hsv=True),
        "192.168.1.43": make_bulb("192.168.1.43", fail_set_hsv=True),
        "192.168.1.44": make_bulb("192.168.1.44", fail_set_hsv=True),
    }

    async def fake_connect(*, host, **_):
        return bulbs_by_host[host]

    with patch("claude_beacon.adapters.kasa.Device.connect",
               AsyncMock(side_effect=fake_connect)):
        a = KasaAdapter(cfg_three)
        await a.connect()
        with pytest.raises(DeviceError, match="all"):
            await a.apply_state(State.IDLE)


@pytest.mark.asyncio
async def test_health_check_true_if_any_bulb_up(cfg_three):
    b1 = make_bulb("192.168.1.42")
    b2 = make_bulb("192.168.1.43")
    b3 = make_bulb("192.168.1.44")
    bulbs = {b.host: b for b in (b1, b2, b3)}

    async def fake_connect(*, host, **_):
        return bulbs[host]

    with patch("claude_beacon.adapters.kasa.Device.connect",
               AsyncMock(side_effect=fake_connect)):
        a = KasaAdapter(cfg_three)
        await a.connect()
        b1.update.side_effect = Exception("still dead")
        b2.update.side_effect = None
        b3.update.side_effect = Exception("still dead")
        assert await a.health_check() is True


@pytest.mark.asyncio
async def test_health_check_false_if_all_bulbs_down(cfg_three):
    bulbs_by_host = {
        h: make_bulb(h) for h in cfg_three.hosts
    }

    async def fake_connect(*, host, **_):
        return bulbs_by_host[host]

    with patch("claude_beacon.adapters.kasa.Device.connect",
               AsyncMock(side_effect=fake_connect)):
        a = KasaAdapter(cfg_three)
        await a.connect()
        for b in bulbs_by_host.values():
            b.update.side_effect = Exception("dead")
        assert await a.health_check() is False
