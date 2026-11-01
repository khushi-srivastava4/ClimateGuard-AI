import asyncio
from datetime import date, timedelta
from unittest.mock import patch
import httpx, pytest
from app.services import weather_service as W


class FakeCache(dict):
    def get(self, k): return dict.get(self, k)
    def set(self, k, v, ttl_seconds=None): self[k] = v
    def delete(self, k): self.pop(k, None)


def payload():
    dates = [(date(2026, 11, 1) + timedelta(days=index)).isoformat() for index in range(14)]
    return {
        "latitude": 27.18,
        "longitude": 78.0,
        "timezone": "Asia/Kolkata",
        "daily": {
            "time": dates,
            "temperature_2m_max": [31.0] * len(dates),
            "temperature_2m_min": [18.0] * len(dates),
            "precipitation_probability_max": [10] * len(dates),
            "precipitation_sum": [0.0] * len(dates),
            "wind_speed_10m_max": [12.0] * len(dates),
        },
    }


def client_returning(responses, calls):
    it = iter(responses)
    class C(httpx.AsyncClient):
        def __init__(self, *a, **k):
            k["transport"] = httpx.MockTransport(lambda req: (calls.append(req.url.params["latitude"]) or next(it)))
            super().__init__(*a, **k)
    return C


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.setattr(W, "_blocked_until", 0.0)
    monkeypatch.setattr(W, "cache", FakeCache())


def test_nearby_clicks_share_one_cache_entry():
    calls = []
    with patch.object(W.httpx, "AsyncClient", client_returning([httpx.Response(200, json=payload())], calls)):
        a = asyncio.run(W.get_weather(27.1767, 78.0081))
        b = asyncio.run(W.get_weather(27.1801, 78.0129))      # a different click a few hundred metres away
    assert len(calls) == 1 and a.retrieved_at == b.retrieved_at and calls == ["27.18"]


def test_429_is_not_retried_and_blocks_further_calls():
    calls = []
    with patch.object(W.httpx, "AsyncClient", client_returning([httpx.Response(429, headers={"retry-after": "45"})] * 5, calls)):
        with pytest.raises(W.RateLimited):
            asyncio.run(W.get_weather(10.0, 10.0))
        with pytest.raises(W.RateLimited):
            asyncio.run(W.get_weather(11.0, 11.0))             # other location, still inside the block window
    assert len(calls) == 1


def test_returns_last_real_forecast_when_live_call_fails(monkeypatch):
    calls = []
    with patch.object(W.httpx, "AsyncClient", client_returning([httpx.Response(200, json=payload())], calls)):
        first = asyncio.run(W.get_weather(27.18, 78.0))
    W.cache.pop("weather:27.18:78.0")                              # fresh entry expired, stale copy remains
    with patch.object(W.httpx, "AsyncClient", client_returning([httpx.Response(429)], [])):
        again = asyncio.run(W.get_weather(27.18, 78.0))
    assert again.retrieved_at == first.retrieved_at and "cached copy" in again.source and again.daily[0].temperature_2m_max == 31.0


def test_no_cached_copy_means_the_error_is_raised_not_invented():
    with patch.object(W.httpx, "AsyncClient", client_returning([httpx.Response(503)] * 2, [])):
        with pytest.raises(httpx.HTTPStatusError):
            asyncio.run(W.get_weather(5.0, 5.0))


def test_short_retry_after_is_honoured_then_forecast_retried():
    calls = []
    responses = [
        httpx.Response(429, headers={"retry-after": "0"}),
        httpx.Response(200, json=payload()),
    ]
    with patch.object(W.httpx, "AsyncClient", client_returning(responses, calls)):
        weather = asyncio.run(W.get_weather(27.18, 78.0))
    assert weather.daily and len(calls) == 2


def test_simultaneous_forecast_requests_for_same_location_are_coalesced():
    calls = []
    with patch.object(
        W.httpx,
        "AsyncClient",
        client_returning([httpx.Response(200, json=payload())], calls),
    ):
        async def run():
            return await asyncio.gather(W.get_weather(27.18, 78.0), W.get_weather(27.18, 78.0))

        first, second = asyncio.run(run())
    assert first == second
    assert len(calls) == 1


def test_invalid_weather_json_is_rejected_without_caching():
    calls = []
    with patch.object(
        W.httpx,
        "AsyncClient",
        client_returning([httpx.Response(200, text="not JSON")], calls),
    ):
        with pytest.raises(ValueError, match="invalid forecast JSON"):
            asyncio.run(W.get_weather(27.18, 78.0))
    assert len(calls) == 1
