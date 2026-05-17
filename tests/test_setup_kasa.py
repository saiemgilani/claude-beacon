"""Kasa setup wizard."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from claude_beacon.setup_kasa import (
    build_kasa_config_text,
    discover_or_manual,
)


def fake_bulb(host, alias, model):
    b = MagicMock()
    b.host = host
    b.alias = alias
    b.model = model
    return b


@pytest.mark.asyncio
async def test_discover_returns_devices():
    devs = {
        "192.168.1.42": fake_bulb("192.168.1.42", "Desk lamp", "KL130"),
        "192.168.1.43": fake_bulb("192.168.1.43", "Floor lamp", "L530"),
    }
    with patch("claude_beacon.setup_kasa.Discover.discover",
               AsyncMock(return_value=devs)):
        result = await discover_or_manual()
        assert len(result) == 2
        assert any(d["host"] == "192.168.1.42" for d in result)


@pytest.mark.asyncio
async def test_discover_empty_returns_empty_list():
    with patch("claude_beacon.setup_kasa.Discover.discover",
               AsyncMock(return_value={})):
        result = await discover_or_manual()
        assert result == []


def test_build_config_text_kasa_no_creds():
    out = build_kasa_config_text(hosts=["192.168.1.42"],
                                    username=None, password=None)
    assert 'adapter = "kasa"' in out
    assert 'hosts = ["192.168.1.42"]' in out
    assert "username" not in out
    assert "password" not in out


def test_build_config_text_with_credentials():
    out = build_kasa_config_text(
        hosts=["192.168.1.42", "192.168.1.43"],
        username="you@example.com",
        password="s3cret",
    )
    assert 'hosts = ["192.168.1.42", "192.168.1.43"]' in out
    assert 'username = "you@example.com"' in out
    assert 'password = "s3cret"' in out
