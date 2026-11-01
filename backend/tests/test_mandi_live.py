import asyncio

import httpx
import pytest

from app.config import settings
from app.services import live_data, mandi_live, mandi_service


class MockClient:
    def __init__(self, handler):
        self.handler = handler

    async def get(self, url, *, params=None, timeout=None):
        request = httpx.Request("GET", url, params=params)
        result = self.handler(request)
        if hasattr(result, "__await__"):
            result = await result
        return result


def response(request, payload):
    return httpx.Response(200, request=request, json=payload)


@pytest.fixture(autouse=True)
def clear_provider_state(monkeypatch, tmp_path):
    live_data._cache.clear()
    live_data._inflight.clear()
    live_data._blocked_until.clear()
    live_data.STATUS.clear()
    monkeypatch.setattr(settings, "MANDI_API_KEY", "test-mandi-key")
    monkeypatch.setattr(mandi_live, "CACHE", tmp_path / "mandi-cache.json")


def test_empty_mandi_response_is_reported_without_inventing_prices(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        return response(request, {"records": []})

    monkeypatch.setattr(live_data, "_http", lambda: MockClient(handler))
    with pytest.raises(live_data.SourceError, match="no current mandi records"):
        asyncio.run(mandi_live.get_mandi("Uttar Pradesh", "Wheat"))

    assert len(calls) == 2  # selected state first, then the documented all-India fallback
    assert "api-key" in calls[0].url.params
    assert calls[0].url.params["filters[commodity]"] == "Wheat"
    assert calls[0].url.params["filters[state.keyword]"] == "Uttar Pradesh"


def test_successful_mandi_response_is_cached_by_query(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        return response(
            request,
            {
                "records": [
                    {
                        "modal_price": "2400",
                        "arrival_date": "01/11/2026",
                        "market": "Agra",
                        "district": "Agra",
                    }
                ]
            },
        )

    monkeypatch.setattr(live_data, "_http", lambda: MockClient(handler))

    async def run():
        return (
            await mandi_live.get_mandi("Uttar Pradesh", "Wheat"),
            await mandi_live.get_mandi("Uttar Pradesh", "Wheat"),
        )

    first, second = asyncio.run(run())
    assert first == second
    assert first["median_modal"] == 2400
    assert len(calls) == 1


def test_mandi_connection_failure_reports_network_cause(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ConnectError("Temporary failure in name resolution", request=request)

    monkeypatch.setattr(live_data, "_http", lambda: MockClient(handler))
    with pytest.raises(live_data.SourceError, match="DNS resolution failed"):
        asyncio.run(mandi_live.get_mandi("Uttar Pradesh", "Wheat"))
    assert len(calls) == 3


def test_agent_mandi_fetch_uses_same_official_resource_and_query_auth(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        return response(request, {"records": []})

    monkeypatch.setattr(live_data, "_http", lambda: MockClient(handler))
    records = asyncio.run(mandi_service._fetch("Wheat", "Uttar Pradesh", None))
    assert records == []
    assert len(calls) == 1
    assert calls[0].url.host == "api.data.gov.in"
    assert calls[0].url.path.endswith(settings.MANDI_RESOURCE_ID)
    assert calls[0].url.params["api-key"] == settings.MANDI_API_KEY
    assert calls[0].url.params["filters[commodity]"] == "Wheat"
