import asyncio
from datetime import date, timedelta

import httpx
import pytest

from app.services import live_data as live


class MockClient:
    def __init__(self, handler):
        self.handler = handler

    async def get(self, url, *, params=None, timeout=None):
        request = httpx.Request("GET", url, params=params)
        result = self.handler(request)
        if hasattr(result, "__await__"):
            result = await result
        if result.request is None:
            result.request = request
        return result


@pytest.fixture(autouse=True)
def clear_provider_state(monkeypatch):
    live._cache.clear()
    live._inflight.clear()
    live._blocked_until.clear()
    live.STATUS.clear()
    monkeypatch.setattr(live, "RETRY_BACKOFF_SECONDS", 0)


def forecast_payload(days=46):
    start = date(2026, 10, 1)
    dates = [(start + timedelta(days=index)).isoformat() for index in range(days)]
    return {
        "daily": {
            "time": dates,
            "temperature_2m_max": [30.0] * days,
            "precipitation_sum": [1.0] * days,
            "et0_fao_evapotranspiration": [4.0] * days,
        },
        "hourly": {},
    }


def response(request, status=200, **kwargs):
    return httpx.Response(status, request=request, **kwargs)


def test_forecast_http_200_is_validated_and_cached(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        return response(request, json=forecast_payload())

    monkeypatch.setattr(live, "_http", lambda: MockClient(handler))

    async def run():
        first = await live.forecast(27.1767, 78.0081)
        second = await live.forecast(27.1767, 78.0081)
        return first, second

    first, second = asyncio.run(run())
    assert first == second
    assert len(calls) == 1
    assert calls[0].url.params["past_days"] == "30"
    assert calls[0].url.params["forecast_days"] == "16"


def test_forecast_retries_429_after_retry_after(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return response(request, 429, headers={"Retry-After": "0"}, text="rate limited")
        return response(request, json=forecast_payload())

    monkeypatch.setattr(live, "_http", lambda: MockClient(handler))
    result = asyncio.run(live.forecast(27.1767, 78.0081))
    assert len(calls) == 2
    assert len(result["daily"]["time"]) == 46


def test_invalid_forecast_json_is_not_retried(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        return response(request, text="not JSON")

    monkeypatch.setattr(live, "_http", lambda: MockClient(handler))
    with pytest.raises(live.SourceError, match="forecast"):
        asyncio.run(live.forecast(27.1767, 78.0081))
    assert len(calls) == 1


def test_invalid_forecast_shape_is_not_cached(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        payload = forecast_payload()
        del payload["daily"]["temperature_2m_max"]
        return response(request, json=payload)

    monkeypatch.setattr(live, "_http", lambda: MockClient(handler))
    with pytest.raises(live.SourceError, match="temperature_2m_max"):
        asyncio.run(live.forecast(27.1767, 78.0081))
    assert len(calls) == 1
    assert not live._cache


def test_forecast_shorter_than_assessment_horizon_is_rejected(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        return response(request, json=forecast_payload(days=43))

    monkeypatch.setattr(live, "_http", lambda: MockClient(handler))
    with pytest.raises(live.SourceError, match="incomplete daily date series"):
        asyncio.run(live.forecast(27.1767, 78.0081))
    assert len(calls) == 1


def test_connect_error_is_diagnosed_and_retry_limit_is_bounded(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ConnectError("Connection refused", request=request)

    monkeypatch.setattr(live, "_http", lambda: MockClient(handler))
    with pytest.raises(live.SourceError, match="connection refused"):
        asyncio.run(
            live.fetch(
                "test-provider",
                "https://provider.example/data",
                retries=2,
            )
        )
    assert len(calls) == 3


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (httpx.ConnectTimeout("connect timed out"), "connection timed out"),
        (httpx.ReadTimeout("read timed out"), "response timed out"),
        (httpx.ConnectError("Connection refused"), "connection refused"),
        (httpx.ConnectError("Temporary failure in name resolution"), "DNS resolution failed"),
    ],
)
def test_network_failure_diagnostics(error, expected):
    assert live._connection_error(error) == expected


def test_permanent_client_error_is_not_retried(monkeypatch, caplog):
    calls = []

    def handler(request):
        calls.append(request)
        return response(request, 400, text="invalid parameter")

    monkeypatch.setattr(live, "_http", lambda: MockClient(handler))
    with pytest.raises(live.SourceError, match="HTTP 400"):
        asyncio.run(
            live.fetch(
                "test-provider",
                "https://provider.example/data",
                params={"api-key": "private-key-value"},
                retries=3,
            )
        )
    assert len(calls) == 1


def test_provider_failure_logs_status_without_logging_api_key(monkeypatch, caplog):
    def handler(request):
        return response(
            request,
            403,
            text='{"api-key":"private-key-value","error":"unauthorized"}',
        )

    monkeypatch.setattr(live, "_http", lambda: MockClient(handler))
    with pytest.raises(live.SourceError):
        asyncio.run(
            live.fetch(
                "test-provider",
                "https://provider.example/data",
                params={"api-key": "private-key-value"},
            )
        )
    assert "status=403" in caplog.text
    assert "private-key-value" not in caplog.text


def test_simultaneous_identical_requests_are_coalesced(monkeypatch):
    calls = []

    async def handler(request):
        calls.append(request)
        await asyncio.sleep(0)
        return response(request, json=forecast_payload())

    monkeypatch.setattr(live, "_http", lambda: MockClient(handler))

    async def run():
        return await asyncio.gather(
            live.forecast(27.1767, 78.0081),
            live.forecast(27.1767, 78.0081),
        )

    first, second = asyncio.run(run())
    assert first == second
    assert len(calls) == 1
