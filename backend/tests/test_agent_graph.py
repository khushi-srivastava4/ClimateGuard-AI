from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from app.agent.graph import fetch_provider_data_node


class ProviderFanoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_weather_soil_and_market_fetches_run_concurrently(self) -> None:
        ready = asyncio.Event()
        arrivals = 0

        async def branch_result(key: str) -> dict[str, str]:
            nonlocal arrivals
            arrivals += 1
            if arrivals == 3:
                ready.set()
            await asyncio.wait_for(ready.wait(), timeout=0.5)
            return {key: key}

        async def weather(_state):
            return await branch_result("weather")

        async def soil(_state):
            return await branch_result("soil")

        async def mandi(_state):
            return await branch_result("mandi")

        with (
            patch("app.agent.graph.fetch_weather_node", side_effect=weather),
            patch("app.agent.graph.fetch_soil_node", side_effect=soil),
            patch("app.agent.graph.fetch_mandi_node", side_effect=mandi),
        ):
            result = await fetch_provider_data_node(
                {"latitude": 1.0, "longitude": 2.0, "mandicriteria": "price"}
            )

        self.assertEqual(
            result,
            {"weather": "weather", "soil": "soil", "mandi": "mandi"},
        )


if __name__ == "__main__":
    unittest.main()
