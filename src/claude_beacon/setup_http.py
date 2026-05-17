"""HTTP setup wizard helpers - separated from cli.py for unit testability."""

from __future__ import annotations

import secrets
import string
from typing import Any


def generate_ntfy_channel(length: int = 8) -> str:
    """Return a random ntfy channel name with the claude-beacon- prefix."""
    alphabet = string.ascii_lowercase + string.digits
    suffix = "".join(secrets.choice(alphabet) for _ in range(length))
    return f"claude-beacon-{suffix}"


def ntfy_endpoint(channel: str, *, state_label: str, priority: str,
                    tags: str) -> dict[str, Any]:
    return {
        "url": f"https://ntfy.sh/{channel}",
        "method": "POST",
        "body": f"Claude: {state_label}",
        "headers": {
            "Title": "Claude Beacon",
            "Priority": priority,
            "Tags": tags,
        },
    }


PLATFORM_TEMPLATES = {
    "ntfy": {"label": "ntfy.sh (free, no account, random-name privacy)"},
    "discord": {"label": "Discord webhook"},
    "slack": {"label": "Slack incoming webhook"},
    "homeassistant": {"label": "Home Assistant webhook"},
    "custom": {"label": "Custom (paste a URL and body)"},
}


def build_http_config_text(*, endpoints: dict[str, list[dict[str, Any]]],
                              timeout_s: float = 5.0) -> str:
    """Render config.toml content for the HTTP adapter."""
    lines = [
        'adapter = "http"',
        "",
        "[http]",
        f"timeout_s = {timeout_s}",
    ]
    for state in ("working", "idle", "input", "off"):
        for ep in endpoints.get(state, []):
            lines.append("")
            lines.append(f"[[http.endpoints.{state}]]")
            lines.append(f'url = "{ep["url"]}"')
            lines.append(f'method = "{ep.get("method", "POST")}"')
            if ep.get("body") is not None:
                escaped = ep["body"].replace('"', '\\"')
                lines.append(f'body = "{escaped}"')
            if ep.get("headers"):
                items = ", ".join(
                    f'"{k}" = "{v}"' for k, v in ep["headers"].items()
                )
                lines.append(f"headers = {{ {items} }}")
    return "\n".join(lines) + "\n"
