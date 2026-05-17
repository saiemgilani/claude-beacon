"""Kasa/Tapo IP bulb adapter via python-kasa."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from kasa import Credentials, Device, DeviceConfig, Module

from ..adapters.base import DeviceError
from ..config import KasaConfig
from ..state import State

log = logging.getLogger("claude_beacon.kasa")


def _snapshot_state(bulb) -> dict:
    """Capture the bulb's current state so we can restore it on shutdown.

    Returns a dict with `is_on` plus enough info to reconstruct whichever
    mode the bulb was in (color vs. white-temp).
    """
    light = bulb.modules[Module.Light]
    snap: dict[str, Any] = {"is_on": bool(bulb.is_on)}
    # `hsv` is HSV(hue, saturation, value); `color_temp` is Kelvin (0 if in color mode).
    try:
        hsv = light.hsv
        snap["hsv"] = (hsv.hue, hsv.saturation, hsv.value)
    except Exception:
        snap["hsv"] = None
    try:
        snap["color_temp"] = int(light.color_temp or 0)
    except Exception:
        snap["color_temp"] = 0
    try:
        snap["brightness"] = int(light.brightness or 0)
    except Exception:
        snap["brightness"] = 0
    return snap


async def _restore_state(bulb, snap: dict) -> None:
    """Reapply a snapshot. Picks white-temp mode if color_temp > 0 AND
    saturation was 0; otherwise picks color (HSV) mode."""
    light = bulb.modules[Module.Light]
    if not snap.get("is_on"):
        await bulb.turn_off()
        return
    await bulb.turn_on()
    hsv = snap.get("hsv")
    ct = snap.get("color_temp", 0)
    if ct and (hsv is None or hsv[1] == 0):
        # White-temp mode: set color temp + brightness.
        await light.set_color_temp(ct)
        if snap.get("brightness"):
            await light.set_brightness(snap["brightness"])
    elif hsv is not None:
        # Color mode.
        await light.set_hsv(*hsv)


class KasaAdapter:
    name = "kasa"

    def __init__(self, cfg: KasaConfig) -> None:
        self.cfg = cfg
        self.bulbs: list[Any] = []
        self._snapshots: dict[str, dict] = {}   # keyed by bulb.host
        self._animator: asyncio.Task | None = None

    # ----- lifecycle -----

    async def connect(self) -> None:
        creds = (
            Credentials(self.cfg.username, self.cfg.password)
            if self.cfg.username
            else None
        )

        async def one(host: str):
            try:
                if creds is not None:
                    config = DeviceConfig(host=host, credentials=creds)
                    d = await Device.connect(config=config)
                else:
                    d = await Device.connect(host=host)
                return d
            except Exception as e:
                log.warning("kasa connect %s failed: %s", host, e)
                return None

        results = await asyncio.gather(*(one(h) for h in self.cfg.hosts))
        self.bulbs = [b for b in results if b is not None]
        if not self.bulbs:
            raise DeviceError(f"no bulbs reachable in {self.cfg.hosts}")

        # Snapshot original state per bulb so close() / State.OFF can restore.
        # If a bulb wasn't snapshotted on a previous connect (rare reconnect
        # case), capture now. Don't overwrite an existing snapshot - the
        # FIRST connection's view of the user's pre-claude state is the
        # authoritative one.
        for b in self.bulbs:
            if b.host not in self._snapshots:
                try:
                    self._snapshots[b.host] = _snapshot_state(b)
                    log.info("snapshot %s: %s", b.host, self._snapshots[b.host])
                except Exception as e:
                    log.warning("snapshot %s failed: %s", b.host, e)

    async def close(self) -> None:
        await self._cancel_animator()
        # Restore each bulb to its pre-claude state.
        await self._restore_originals()
        for b in self.bulbs:
            try:
                await b.disconnect()
            except Exception:
                pass
        self.bulbs = []

    async def _restore_originals(self) -> None:
        """Best-effort restore of each bulb to its pre-claude snapshot.
        Failures are logged but never raise (this runs during shutdown)."""
        async def one(b):
            snap = self._snapshots.get(b.host)
            if snap is None:
                return
            try:
                await _restore_state(b, snap)
            except Exception as e:
                log.warning("restore %s failed: %s", b.host, e)
        if self.bulbs:
            await asyncio.gather(*(one(b) for b in self.bulbs),
                                 return_exceptions=True)

    # ----- state application -----

    @staticmethod
    def _light_of(bulb):
        return bulb.modules[Module.Light]

    async def apply_state(self, state: State) -> None:
        await self._cancel_animator()
        if not self.bulbs:
            raise DeviceError("not connected")
        try:
            if state == State.WORKING:
                self._animator = asyncio.create_task(self._working_loop())
            elif state == State.IDLE:
                await self._fanout(
                    lambda b: self._set_color(b, on=True,
                                                hsv=self.cfg.colors.idle_hsv),
                )
            elif state == State.INPUT:
                await self._fanout(
                    lambda b: self._set_color(b, on=True,
                                                hsv=self.cfg.colors.input_hsv),
                )
            elif state == State.OFF:
                # State.OFF means "claude is done — give the bulbs back."
                # We restore each bulb to its snapshotted pre-claude state
                # instead of unconditionally turning them off.
                await self._restore_originals()
        except DeviceError:
            raise
        except Exception as e:
            raise DeviceError(f"apply {state.value}: {e}") from e

    async def _set_color(self, bulb, *, on: bool, hsv) -> None:
        if on:
            await bulb.turn_on()
        await self._light_of(bulb).set_hsv(*hsv)

    async def _fanout(self, op) -> None:
        """Run op(bulb) on every bulb. Fail-soft: log per-bulb errors, raise
        DeviceError only when every bulb fails."""
        results = await asyncio.gather(
            *(op(b) for b in self.bulbs), return_exceptions=True,
        )
        failures = [(b, r) for b, r in zip(self.bulbs, results)
                    if isinstance(r, Exception)]
        for bulb, exc in failures:
            log.warning("kasa op failed on %s: %s", bulb.host, exc)
        if len(failures) == len(self.bulbs):
            raise DeviceError(
                f"all bulbs failed: {[str(e) for _, e in failures]}",
            )

    # ----- health -----

    async def health_check(self) -> bool:
        """True if at least one bulb's update() succeeds."""
        if not self.bulbs:
            return False
        results = await asyncio.gather(
            *(b.update() for b in self.bulbs), return_exceptions=True,
        )
        return any(not isinstance(r, Exception) for r in results)

    # ----- animator -----

    async def _cancel_animator(self) -> None:
        if self._animator and not self._animator.done():
            self._animator.cancel()
            try:
                await self._animator
            except asyncio.CancelledError:
                pass
        self._animator = None

    async def _working_loop(self) -> None:
        a, b = self.cfg.colors.working_colors
        half = self.cfg.colors.working_period_ms / 2000
        try:
            while True:
                await self._fanout(lambda bulb: self._light_of(bulb).set_hsv(*a))
                await asyncio.sleep(half)
                await self._fanout(lambda bulb: self._light_of(bulb).set_hsv(*b))
                await asyncio.sleep(half)
        except asyncio.CancelledError:
            return
