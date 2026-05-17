"""HTTP setup wizard helpers."""

import re

from claude_beacon.setup_http import (
    PLATFORM_TEMPLATES,
    build_http_config_text,
    generate_ntfy_channel,
)


def test_generate_ntfy_channel_is_random():
    a = generate_ntfy_channel()
    b = generate_ntfy_channel()
    assert a != b
    assert a.startswith("claude-beacon-")
    assert re.match(r"^claude-beacon-[a-z0-9]{8,16}$", a)


def test_platform_templates_includes_expected_platforms():
    for key in ("ntfy", "discord", "slack", "homeassistant"):
        assert key in PLATFORM_TEMPLATES


def test_build_config_text_ntfy_input_only():
    out = build_http_config_text(
        endpoints={
            "input": [{
                "url": "https://ntfy.sh/abc",
                "method": "POST",
                "body": "Claude needs your input",
                "headers": {"Title": "Claude", "Priority": "high"},
            }],
        },
        timeout_s=5,
    )
    assert 'adapter = "http"' in out
    assert "[[http.endpoints.input]]" in out
    assert 'url = "https://ntfy.sh/abc"' in out
    assert '"Title" = "Claude"' in out


def test_build_config_text_multi_state():
    out = build_http_config_text(
        endpoints={
            "input": [{"url": "https://x.example/i"}],
            "off": [{"url": "https://x.example/o"}],
        },
        timeout_s=5,
    )
    assert out.count("[[http.endpoints.input]]") == 1
    assert out.count("[[http.endpoints.off]]") == 1
