"""HTTP webhook adapter - generic POST/PUT/etc. to one or more URLs per state."""

from __future__ import annotations

import asyncio
import logging
from typing import Iterable

import httpx

from ..adapters.base import DeviceError
from ..config import HttpConfig, HttpEndpoint
from ..state import State

log = logging.getLogger("claude_beacon.http")


class HttpAdapter:
    name = "http"

    def __init__(self, cfg: HttpConfig) -> None:
        self.cfg = cfg
        self.client: httpx.AsyncClient | None = None

    async def connect(self) -> None:
        self.client = httpx.AsyncClient(timeout=self.cfg.timeout_s)

    async def apply_state(self, state: State) -> None:
        endpoints = self.cfg.endpoints.get(state.value, [])
        if not endpoints:
            log.debug("http: no endpoints for state=%s; skipping", state.value)
            return
        if self.client is None:
            raise DeviceError("not connected")
        await self._fanout(endpoints)

    async def _fanout(self, endpoints: Iterable[HttpEndpoint]) -> None:
        endpoints = list(endpoints)

        async def one(ep: HttpEndpoint):
            try:
                resp = await self.client.request(
                    ep.method,
                    ep.url,
                    headers=ep.headers or None,
                    content=ep.body.encode("utf-8") if ep.body is not None else None,
                )
                if resp.status_code >= 400:
                    raise httpx.HTTPStatusError(
                        f"HTTP {resp.status_code}",
                        request=resp.request, response=resp,
                    )
                return None
            except Exception as e:
                return e

        results = await asyncio.gather(*(one(ep) for ep in endpoints))
        failures = [(ep, r) for ep, r in zip(endpoints, results) if r is not None]
        for ep, exc in failures:
            log.warning("http %s %s failed: %s", ep.method, ep.url, exc)
        if len(failures) == len(endpoints):
            raise DeviceError(
                f"all {len(endpoints)} endpoints failed for this state",
            )

    async def health_check(self) -> bool:
        return self.client is not None and not self.client.is_closed

    async def close(self) -> None:
        if self.client is not None:
            try:
                await self.client.aclose()
            except Exception:
                pass
            self.client = None
