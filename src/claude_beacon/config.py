"""TOML config loader. Validates and converts to typed dataclasses."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    """Configuration is invalid or cannot be read."""


# ---------------------------------------------------------------------------
# Daemon section (overrides default constants in daemon.py)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DaemonConfig:
    tick_ms: int = 200
    debounce_ms: int = 500
    idle_timeout_s: int = 1800
    health_interval_idle_s: int = 60
    health_interval_working_s: int = 10
    reconnect_backoff_s: tuple[int, ...] = (1, 2, 4, 8, 16)


# ---------------------------------------------------------------------------
# Kasa adapter section
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class KasaColors:
    idle_hsv: tuple[int, int, int] = (30, 80, 70)
    input_hsv: tuple[int, int, int] = (285, 100, 85)
    working_colors: tuple[tuple[int, int, int], tuple[int, int, int]] = (
        (0, 0, 100), (235, 100, 60),
    )
    working_period_ms: int = 1000


@dataclass(frozen=True)
class KasaConfig:
    hosts: list[str]
    username: str | None = None
    password: str | None = None
    colors: KasaColors = field(default_factory=KasaColors)


# ---------------------------------------------------------------------------
# HTTP adapter section
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class HttpEndpoint:
    url: str
    method: str = "POST"
    body: str | None = None
    headers: dict[str, str] | None = None


@dataclass(frozen=True)
class HttpConfig:
    endpoints: dict[str, list[HttpEndpoint]] = field(default_factory=dict)
    timeout_s: float = 5.0


# ---------------------------------------------------------------------------
# Top-level Config
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Config:
    adapter: str
    daemon: DaemonConfig
    kasa: KasaConfig | None = None
    http: HttpConfig | None = None


_KNOWN_ADAPTERS = ("kasa", "http")


def load_config(path: Path) -> Config:
    """Load and validate config.toml. Raises ConfigError on any problem."""
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"could not parse TOML in {path}: {e}") from e

    adapter = raw.get("adapter")
    if adapter not in _KNOWN_ADAPTERS:
        raise ConfigError(
            f"unknown adapter {adapter!r}; choose one of {_KNOWN_ADAPTERS}",
        )

    daemon = _parse_daemon(raw.get("daemon", {}))
    kasa = _parse_kasa(raw.get("kasa", {})) if adapter == "kasa" else None
    http = _parse_http(raw.get("http", {})) if adapter == "http" else None

    return Config(adapter=adapter, daemon=daemon, kasa=kasa, http=http)


def _parse_daemon(raw: dict[str, Any]) -> DaemonConfig:
    defaults = DaemonConfig()
    return DaemonConfig(
        tick_ms=int(raw.get("tick_ms", defaults.tick_ms)),
        debounce_ms=int(raw.get("debounce_ms", defaults.debounce_ms)),
        idle_timeout_s=int(raw.get("idle_timeout_s", defaults.idle_timeout_s)),
        health_interval_idle_s=int(raw.get("health_interval_idle_s",
                                            defaults.health_interval_idle_s)),
        health_interval_working_s=int(raw.get("health_interval_working_s",
                                                defaults.health_interval_working_s)),
        reconnect_backoff_s=tuple(raw.get("reconnect_backoff_s",
                                            defaults.reconnect_backoff_s)),
    )


def _parse_kasa(raw: dict[str, Any]) -> KasaConfig:
    hosts = raw.get("hosts")
    if not isinstance(hosts, list) or not hosts:
        raise ConfigError("[kasa].hosts must be a non-empty list of strings")
    if not all(isinstance(h, str) for h in hosts):
        raise ConfigError("[kasa].hosts entries must all be strings")

    username = raw.get("username")
    password = raw.get("password")
    if (username is None) != (password is None):
        raise ConfigError(
            "[kasa].username and [kasa].password must both be set or both omitted",
        )

    colors = _parse_kasa_colors(raw.get("colors", {}))
    return KasaConfig(
        hosts=list(hosts),
        username=username,
        password=password,
        colors=colors,
    )


def _parse_kasa_colors(raw: dict[str, Any]) -> KasaColors:
    defaults = KasaColors()
    return KasaColors(
        idle_hsv=tuple(raw.get("idle", {}).get("hsv", defaults.idle_hsv)),
        input_hsv=tuple(raw.get("input", {}).get("hsv", defaults.input_hsv)),
        working_colors=tuple(
            tuple(c) for c in raw.get("working", {}).get("colors",
                                                            defaults.working_colors)
        ),
        working_period_ms=int(
            raw.get("working", {}).get("period_ms", defaults.working_period_ms),
        ),
    )


def _parse_http(raw: dict[str, Any]) -> HttpConfig:
    timeout_s = float(raw.get("timeout_s", 5.0))
    if timeout_s < 1:
        raise ConfigError("[http].timeout_s must be >= 1")

    endpoints_raw = raw.get("endpoints", {})
    if not isinstance(endpoints_raw, dict):
        raise ConfigError("[http.endpoints] must be a table")

    valid_states = {"off", "idle", "working", "input"}
    endpoints: dict[str, list[HttpEndpoint]] = {}
    for state, blocks in endpoints_raw.items():
        if state not in valid_states:
            raise ConfigError(
                f"[http.endpoints.{state}] unknown state; valid: {sorted(valid_states)}",
            )
        if not isinstance(blocks, list) or not blocks:
            raise ConfigError(
                f"[http.endpoints.{state}] must be a non-empty list of tables",
            )
        endpoints[state] = [_parse_http_endpoint(state, b) for b in blocks]

    if not endpoints:
        raise ConfigError(
            "[http.endpoints] is empty; configure at least one state's endpoints",
        )

    return HttpConfig(endpoints=endpoints, timeout_s=timeout_s)


def _parse_http_endpoint(state: str, raw: dict[str, Any]) -> HttpEndpoint:
    url = raw.get("url")
    if not isinstance(url, str) or not url:
        raise ConfigError(f"[http.endpoints.{state}] missing url")
    if not (url.startswith("http://") or url.startswith("https://")):
        raise ConfigError(
            f"[http.endpoints.{state}] url must use http or https scheme",
        )

    method = raw.get("method", "POST")
    if method not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
        raise ConfigError(
            f"[http.endpoints.{state}] method {method!r} not allowed",
        )

    headers = raw.get("headers")
    if headers is not None and not isinstance(headers, dict):
        raise ConfigError(
            f"[http.endpoints.{state}] headers must be a table",
        )

    body = raw.get("body")
    if body is not None and not isinstance(body, str):
        raise ConfigError(f"[http.endpoints.{state}] body must be a string")

    return HttpEndpoint(url=url, method=method, body=body, headers=headers)
