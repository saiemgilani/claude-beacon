"""Kasa setup wizard helpers - separated from cli.py for unit testability."""

from __future__ import annotations

from kasa import Credentials, Device, DeviceConfig, Discover


async def discover_or_manual() -> list[dict[str, str]]:
    """Run Kasa discovery on the local subnet. Returns list of dicts
    {host, alias, model}. Empty if nothing found."""
    try:
        devs = await Discover.discover(timeout=5)
    except Exception:
        return []
    return [
        {
            "host": host,
            "alias": getattr(d, "alias", "") or "",
            "model": getattr(d, "model", "") or "",
        }
        for host, d in devs.items()
    ]


async def test_connect(host: str, username: str | None, password: str | None) -> bool:
    """Try to connect to host with optional creds; return True on success.
    Uses Device.connect which auto-detects legacy Kasa vs Tapo protocol."""
    try:
        if username:
            creds = Credentials(username, password)
            d = await Device.connect(config=DeviceConfig(host=host, credentials=creds))
        else:
            d = await Device.connect(host=host)
        await d.disconnect()
        return True
    except Exception:
        return False


def build_kasa_config_text(*, hosts: list[str], username: str | None,
                             password: str | None) -> str:
    """Render config.toml content for the Kasa adapter."""
    hosts_str = "[" + ", ".join(f'"{h}"' for h in hosts) + "]"
    lines = [
        'adapter = "kasa"',
        "",
        "[kasa]",
        f"hosts = {hosts_str}",
    ]
    if username:
        lines += [f'username = "{username}"', f'password = "{password}"']
    return "\n".join(lines) + "\n"
