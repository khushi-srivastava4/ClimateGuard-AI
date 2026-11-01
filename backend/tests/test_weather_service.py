import asyncio
from unittest.mock import patch
import httpx, pytest
from app.services import weather_service as W


class FakeCache(dict):
    def get(self, k): return dict.get(self, k)
    def set(self, k, v, ttl_seconds=None): self[k] = v
    def delete(self, k): self.pop(k, None)


def payload(): return {"latitude": 27.18, "longitude": 78.0, "timezone": "Asia/Kolkata", "daily": {"time": ["2026-11-01"], "temperature_2m_max": [31.0], "temperature_2m_min": [18.0], "precipitation_probability_max": [10], "precipitation_sum": [0.0], "wind_speed_10m_max": [12.0]}}


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
