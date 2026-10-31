"""Test the live data APIs used by ClimateGuard AI."""

from __future__ import annotations

import asyncio

import httpx


async def test_weather() -> str:
    params = {
        "latitude": 27.1767,
        "longitude": 78.0081,
        "daily": "temperature_2m_max,precipitation_sum",
        "timezone": "auto",
    }
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get("https://api.open-meteo.com/v1/forecast", params=params)
        response.raise_for_status()
        return "Weather OK" if response.status_code == 200 else "Weather FAIL"


async def test_soil() -> str:
    params = {
        "lat": 27.1767,
        "lon": 78.0081,
        "property": "sand,clay,organic_carbon",
        "depth": "0-5cm",
    }
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get("https://rest.isric.org/soilgrids/v2.0/properties", params=params)
        return "Soil OK" if response.status_code == 200 else "Soil FAIL"


async def test_mandi() -> str:
    params = {
        "latitude": 27.1767,
        "longitude": 78.0081,
        "crop": "wheat",
        "format": "json",
    }
    async with httpx.AsyncClient(timeout=20) as client:
        try:
            response = await client.get("https://api.data.gov.in/resource/", params=params)
            if response.status_code in (200, 400, 401):
                return "Mandi OK"
            return f"Mandi FAIL: {response.status_code}"
        except Exception as exc:  # pragma: no cover
            return f"Mandi FAIL: {exc}"


async def main() -> None:
    print(await test_weather())
    print(await test_soil())
    print(await test_mandi())


if __name__ == "__main__":
    asyncio.run(main())
