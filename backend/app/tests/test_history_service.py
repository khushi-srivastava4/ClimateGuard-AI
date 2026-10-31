from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from app.services.history_service import (
    HistoryProviderError,
    get_weather_history,
)


class WeatherHistoryTests(unittest.IsolatedAsyncioTestCase):
    def make_client_context(self, get: AsyncMock) -> MagicMock:
        client = AsyncMock()
        client.get = get
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=client)
        context.__aexit__ = AsyncMock(return_value=None)
        return context

    async def test_archive_records_are_returned_with_honest_provenance(self) -> None:
        response = MagicMock()
        response.is_error = False
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "timezone": "Europe/London",
            "daily": {
                "time": ["2026-10-29", "2026-10-30"],
                "temperature_2m_max": [12.4, 13.1],
                "temperature_2m_min": [4.1, 5.2],
                "precipitation_sum": [0.0, 2.3],
                "precipitation_hours": [0, 2],
                "wind_speed_10m_max": [20, 25],
            },
        }
        get = AsyncMock(return_value=response)
        with patch(
            "app.services.history_service.httpx.AsyncClient",
            return_value=self.make_client_context(get),
        ):
            result = await get_weather_history(51.5, -0.1, days=2)

        self.assertEqual(result["status"], "available")
        self.assertEqual(result["data_kind"], "historical reanalysis")
        self.assertEqual(len(result["daily"]), 2)
        self.assertEqual(result["daily"][1]["precipitation_sum"], 2.3)
        self.assertEqual(get.await_args.kwargs["params"]["daily"].split(",")[0], "temperature_2m_max")

    async def test_http_status_failure_is_safe_and_preserves_status_code(self) -> None:
        request = httpx.Request("GET", "https://archive-api.open-meteo.com")
        response = httpx.Response(429, request=request)
        get = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "provider error", request=request, response=response
            )
        )
        with patch(
            "app.services.history_service.httpx.AsyncClient",
            return_value=self.make_client_context(get),
        ):
            with self.assertRaises(HistoryProviderError) as raised:
                await get_weather_history(51.5, -0.1, days=2)
        self.assertEqual(raised.exception.status_code, 429)
        self.assertNotIn("https://", str(raised.exception))

    async def test_connection_failure_is_not_returned_as_empty_history(self) -> None:
        get = AsyncMock(side_effect=httpx.ReadTimeout("upstream timeout"))
        with patch(
            "app.services.history_service.httpx.AsyncClient",
            return_value=self.make_client_context(get),
        ):
            with self.assertRaisesRegex(HistoryProviderError, "ReadTimeout"):
                await get_weather_history(51.5, -0.1, days=2)


if __name__ == "__main__":
    unittest.main()
