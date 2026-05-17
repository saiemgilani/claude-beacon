"""Config loader: parses TOML into validated dataclasses, raises ConfigError
on bad input."""

from pathlib import Path

import pytest

from claude_beacon.config import (
    Config,
    ConfigError,
    HttpConfig,
    HttpEndpoint,
    KasaConfig,
    load_config,
)


def write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "config.toml"
    p.write_text(body, encoding="utf-8")
    return p


# ----------- Kasa -----------

def test_kasa_minimal_single_host(tmp_path):
    p = write(tmp_path, '''
        adapter = "kasa"
        [kasa]
        hosts = ["192.168.1.42"]
    ''')
    cfg = load_config(p)
    assert isinstance(cfg, Config)
    assert cfg.adapter == "kasa"
    assert isinstance(cfg.kasa, KasaConfig)
    assert cfg.kasa.hosts == ["192.168.1.42"]
    assert cfg.kasa.username is None
    assert cfg.kasa.password is None


def test_kasa_multiple_hosts(tmp_path):
    p = write(tmp_path, '''
        adapter = "kasa"
        [kasa]
        hosts = ["192.168.1.42", "192.168.1.43"]
    ''')
    cfg = load_config(p)
    assert cfg.kasa.hosts == ["192.168.1.42", "192.168.1.43"]


def test_kasa_with_credentials_for_tapo(tmp_path):
    p = write(tmp_path, '''
        adapter = "kasa"
        [kasa]
        hosts = ["192.168.1.42"]
        username = "you@example.com"
        password = "s3cret"
    ''')
    cfg = load_config(p)
    assert cfg.kasa.username == "you@example.com"
    assert cfg.kasa.password == "s3cret"


def test_kasa_password_without_username_rejected(tmp_path):
    p = write(tmp_path, '''
        adapter = "kasa"
        [kasa]
        hosts = ["192.168.1.42"]
        password = "s3cret"
    ''')
    with pytest.raises(ConfigError, match="username"):
        load_config(p)


def test_kasa_username_without_password_rejected(tmp_path):
    p = write(tmp_path, '''
        adapter = "kasa"
        [kasa]
        hosts = ["192.168.1.42"]
        username = "you@example.com"
    ''')
    with pytest.raises(ConfigError, match="password"):
        load_config(p)


def test_kasa_empty_hosts_rejected(tmp_path):
    p = write(tmp_path, '''
        adapter = "kasa"
        [kasa]
        hosts = []
    ''')
    with pytest.raises(ConfigError, match="empty"):
        load_config(p)


def test_unknown_adapter_rejected(tmp_path):
    p = write(tmp_path, '''
        adapter = "philips_hue"
        [philips_hue]
        host = "..."
    ''')
    with pytest.raises(ConfigError, match="adapter"):
        load_config(p)


def test_missing_file_raises(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.toml")


# ----------- HTTP -----------

def test_http_minimal_input_only(tmp_path):
    p = write(tmp_path, '''
        adapter = "http"
        [[http.endpoints.input]]
        url = "https://ntfy.sh/test-channel"
    ''')
    cfg = load_config(p)
    assert cfg.adapter == "http"
    assert isinstance(cfg.http, HttpConfig)
    assert list(cfg.http.endpoints.keys()) == ["input"]
    eps = cfg.http.endpoints["input"]
    assert len(eps) == 1
    assert eps[0].url == "https://ntfy.sh/test-channel"
    assert eps[0].method == "POST"
    assert eps[0].body is None
    assert eps[0].headers is None


def test_http_multi_endpoint_per_state(tmp_path):
    p = write(tmp_path, '''
        adapter = "http"
        [[http.endpoints.input]]
        url = "https://ntfy.sh/c1"
        [[http.endpoints.input]]
        url = "https://discord.com/api/webhooks/abc"
        method = "POST"
        body = "{\\"content\\": \\"hi\\"}"
        headers = { "Content-Type" = "application/json" }
    ''')
    cfg = load_config(p)
    eps = cfg.http.endpoints["input"]
    assert len(eps) == 2
    assert eps[1].headers == {"Content-Type": "application/json"}
    assert eps[1].body == '{"content": "hi"}'


def test_http_empty_endpoints_rejected(tmp_path):
    p = write(tmp_path, '''
        adapter = "http"
        [http]
        timeout_s = 5
    ''')
    with pytest.raises(ConfigError, match="empty"):
        load_config(p)


def test_http_unknown_state_rejected(tmp_path):
    p = write(tmp_path, '''
        adapter = "http"
        [[http.endpoints.blinking]]
        url = "https://x.example/"
    ''')
    with pytest.raises(ConfigError, match="unknown state"):
        load_config(p)


def test_http_endpoint_missing_url(tmp_path):
    p = write(tmp_path, '''
        adapter = "http"
        [[http.endpoints.input]]
        method = "POST"
    ''')
    with pytest.raises(ConfigError, match="missing url"):
        load_config(p)


def test_http_endpoint_bad_url_scheme(tmp_path):
    p = write(tmp_path, '''
        adapter = "http"
        [[http.endpoints.input]]
        url = "ftp://x.example/"
    ''')
    with pytest.raises(ConfigError, match="scheme"):
        load_config(p)


def test_http_endpoint_bad_method(tmp_path):
    p = write(tmp_path, '''
        adapter = "http"
        [[http.endpoints.input]]
        url = "https://x.example/"
        method = "BREW"
    ''')
    with pytest.raises(ConfigError, match="method"):
        load_config(p)


def test_http_timeout_must_be_at_least_one(tmp_path):
    p = write(tmp_path, '''
        adapter = "http"
        [http]
        timeout_s = 0.5
        [[http.endpoints.input]]
        url = "https://x.example/"
    ''')
    with pytest.raises(ConfigError, match="timeout"):
        load_config(p)


# ----------- Daemon overrides -----------

def test_daemon_defaults_applied(tmp_path):
    p = write(tmp_path, '''
        adapter = "kasa"
        [kasa]
        hosts = ["192.168.1.42"]
    ''')
    cfg = load_config(p)
    assert cfg.daemon.tick_ms == 200
    assert cfg.daemon.debounce_ms == 500
    assert cfg.daemon.idle_timeout_s == 1800
    assert cfg.daemon.reconnect_backoff_s == (1, 2, 4, 8, 16)


def test_daemon_overrides_respected(tmp_path):
    p = write(tmp_path, '''
        adapter = "kasa"
        [kasa]
        hosts = ["192.168.1.42"]
        [daemon]
        tick_ms = 500
        idle_timeout_s = 60
        reconnect_backoff_s = [2, 4]
    ''')
    cfg = load_config(p)
    assert cfg.daemon.tick_ms == 500
    assert cfg.daemon.idle_timeout_s == 60
    assert cfg.daemon.reconnect_backoff_s == (2, 4)
