"""HttpAdapter: tested with pytest-httpx's mocked transport."""

import pytest
from pytest_httpx import HTTPXMock

from claude_beacon.adapters.base import DeviceError
from claude_beacon.adapters.http import HttpAdapter
from claude_beacon.config import HttpConfig, HttpEndpoint
from claude_beacon.state import State


def make_cfg(endpoints: dict) -> HttpConfig:
    return HttpConfig(endpoints=endpoints, timeout_s=5.0)


@pytest.mark.asyncio
async def test_apply_state_with_no_endpoints_is_noop(httpx_mock: HTTPXMock):
    cfg = make_cfg({})  # nothing configured
    a = HttpAdapter(cfg)
    await a.connect()
    await a.apply_state(State.WORKING)  # should NOT make any request
    await a.apply_state(State.IDLE)
    assert httpx_mock.get_requests() == []
    await a.close()


@pytest.mark.asyncio
async def test_apply_state_with_state_unconfigured_is_noop(httpx_mock: HTTPXMock):
    cfg = make_cfg({
        "input": [HttpEndpoint(url="https://ntfy.sh/test")],
    })
    a = HttpAdapter(cfg)
    await a.connect()
    await a.apply_state(State.WORKING)  # no working endpoints
    assert httpx_mock.get_requests() == []
    await a.close()


@pytest.mark.asyncio
async def test_apply_input_fires_request(httpx_mock: HTTPXMock):
    cfg = make_cfg({
        "input": [HttpEndpoint(url="https://ntfy.sh/test", body="hi")],
    })
    httpx_mock.add_response(url="https://ntfy.sh/test", method="POST",
                             status_code=200)
    a = HttpAdapter(cfg)
    await a.connect()
    await a.apply_state(State.INPUT)
    reqs = httpx_mock.get_requests()
    assert len(reqs) == 1
    assert reqs[0].method == "POST"
    assert str(reqs[0].url) == "https://ntfy.sh/test"
    assert reqs[0].content == b"hi"
    await a.close()


@pytest.mark.asyncio
async def test_headers_passed_through(httpx_mock: HTTPXMock):
    cfg = make_cfg({
        "input": [HttpEndpoint(
            url="https://ntfy.sh/test", body="hi",
            headers={"Title": "Claude", "Priority": "high"},
        )],
    })
    httpx_mock.add_response(url="https://ntfy.sh/test", status_code=200)
    a = HttpAdapter(cfg)
    await a.connect()
    await a.apply_state(State.INPUT)
    req = httpx_mock.get_requests()[0]
    assert req.headers["Title"] == "Claude"
    assert req.headers["Priority"] == "high"
    await a.close()


@pytest.mark.asyncio
async def test_multi_endpoint_fanout_fires_each(httpx_mock: HTTPXMock):
    cfg = make_cfg({
        "input": [
            HttpEndpoint(url="https://ntfy.sh/a"),
            HttpEndpoint(url="https://discord.com/api/webhooks/b",
                          headers={"Content-Type": "application/json"}),
        ],
    })
    httpx_mock.add_response(url="https://ntfy.sh/a", status_code=200)
    httpx_mock.add_response(url="https://discord.com/api/webhooks/b",
                              status_code=200)
    a = HttpAdapter(cfg)
    await a.connect()
    await a.apply_state(State.INPUT)
    reqs = httpx_mock.get_requests()
    assert len(reqs) == 2
    await a.close()


@pytest.mark.asyncio
async def test_one_endpoint_500_is_fail_soft(httpx_mock: HTTPXMock):
    cfg = make_cfg({
        "input": [
            HttpEndpoint(url="https://ntfy.sh/a"),
            HttpEndpoint(url="https://discord.com/api/webhooks/b"),
        ],
    })
    httpx_mock.add_response(url="https://ntfy.sh/a", status_code=200)
    httpx_mock.add_response(url="https://discord.com/api/webhooks/b",
                              status_code=500)
    a = HttpAdapter(cfg)
    await a.connect()
    # Should NOT raise - one endpoint working is enough.
    await a.apply_state(State.INPUT)
    await a.close()


@pytest.mark.asyncio
async def test_all_endpoints_fail_raises_device_error(httpx_mock: HTTPXMock):
    cfg = make_cfg({
        "input": [
            HttpEndpoint(url="https://ntfy.sh/a"),
            HttpEndpoint(url="https://discord.com/api/webhooks/b"),
        ],
    })
    httpx_mock.add_response(url="https://ntfy.sh/a", status_code=500)
    httpx_mock.add_response(url="https://discord.com/api/webhooks/b",
                              status_code=404)
    a = HttpAdapter(cfg)
    await a.connect()
    with pytest.raises(DeviceError, match="all"):
        await a.apply_state(State.INPUT)
    await a.close()


@pytest.mark.asyncio
async def test_health_check_returns_true_after_connect(httpx_mock: HTTPXMock):
    cfg = make_cfg({"input": [HttpEndpoint(url="https://x.example/")]})
    a = HttpAdapter(cfg)
    await a.connect()
    assert await a.health_check() is True
    await a.close()
    assert await a.health_check() is False
