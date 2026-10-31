from __future__ import annotations

import asyncio
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


class FarmApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "api.sqlite3"
        self.database_patch = patch(
            "app.persistence.database.DEFAULT_DATABASE_PATH", self.database_path
        )
        self.database_patch.start()
        self.addCleanup(self.database_patch.stop)
        self.addCleanup(self.temp_dir.cleanup)
        self.client = TestClient(app)

    def test_farm_profile_preferences_and_actions_are_persistent(self) -> None:
        response = self.client.post(
            "/farms",
            json={
                "name": "North plot",
                "location": "Punjab",
                "latitude": 30.7,
                "longitude": 76.8,
                "crop": "wheat",
                "growth_stage": "vegetative",
                "sowing_date": "2026-10-01",
                "irrigation_method": "drip",
            },
        )
        self.assertEqual(response.status_code, 201)
        farm = response.json()

        updated_farm = self.client.patch(
            f"/farms/{farm['id']}",
            json={"state": "Haryana", "variety": "HD-2967"},
        )
        self.assertEqual(updated_farm.status_code, 200)
        self.assertEqual(updated_farm.json()["state"], "Haryana")
        self.assertEqual(updated_farm.json()["variety"], "HD-2967")

        preferences = self.client.put(
            f"/farms/{farm['id']}/alert-preferences",
            json={"enabled": True, "threshold": 82},
        )
        self.assertEqual(preferences.status_code, 200)
        self.assertEqual(preferences.json()["threshold"], 82)

        actions = self.client.get(f"/farms/{farm['id']}/actions")
        self.assertEqual(actions.status_code, 200)
        self.assertEqual(actions.json(), [])

        deleted = self.client.delete(f"/farms/{farm['id']}")
        self.assertEqual(deleted.status_code, 204)
        self.assertEqual(self.client.get(f"/farms/{farm['id']}").status_code, 404)

    def test_health_endpoint(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_assistant_chat_route_is_registered(self) -> None:
        response = self.client.post("/assistant/chat", json={})
        self.assertEqual(response.status_code, 422)

    def test_advice_uses_farm_coordinates_and_persists_conditional_outputs(self) -> None:
        farm_response = self.client.post(
            "/farms",
            json={
                "name": "Test field",
                "location": "Punjab",
                "latitude": 30.7,
                "longitude": 76.8,
                "crop": "wheat",
                "farming_preferences": {
                    "risk_alerts": {"enabled": True, "threshold": 70}
                },
            },
        )
        farm = farm_response.json()
        graph = MagicMock()
        graph.ainvoke = AsyncMock(
            return_value={
                "advice": "Review the observed field conditions.",
                "advice_status": "generated",
                "risk": {
                    "overall": 84,
                    "category": "high",
                    "reasons": ["Elevated forecast risk"],
                    "sources": [],
                },
                "sources": [],
                "mandi": {"prices": [], "error": "Provider unavailable"},
                "weather": {
                    "retrieved_at": "2026-10-31T00:00:00+00:00",
                    "daily": [
                        {
                            "date": date.today().isoformat(),
                            "temperature_2m_max": 38,
                            "precipitation_sum": 0,
                            "precipitation_probability_max": 10,
                        }
                    ],
                },
                "soil": {"properties": {}, "error": "Provider unavailable"},
            }
        )
        with patch("app.main.build_graph", return_value=graph):
            response = self.client.post(
                "/advise",
                json={
                    "farm_id": farm["id"],
                    "latitude": 1,
                    "longitude": 1,
                    "language": "en",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(graph.ainvoke.await_args.args[0]["latitude"], 30.7)
        result = response.json()
        self.assertEqual(result["advice_status"], "generated")
        self.assertTrue(result["field_plan"])
        self.assertEqual(
            self.client.get(f"/farms/{farm['id']}/actions").json(),
            result["field_plan"],
        )
        action = result["field_plan"][0]
        completed = self.client.patch(
            f"/actions/{action['id']}",
            json={"status": "completed"},
        )
        self.assertEqual(completed.status_code, 200)
        self.assertEqual(completed.json()["status"], "completed")
        alerts = self.client.get(f"/alerts?farm_id={farm['id']}").json()
        self.assertEqual(len(alerts), 1)
        self.assertFalse(alerts[0]["is_read"])
        updated_alert = self.client.patch(
            f"/alerts/{alerts[0]['id']}",
            json={"is_read": True},
        )
        self.assertTrue(updated_alert.json()["is_read"])

    def test_advice_without_farm_returns_validated_location_context(self) -> None:
        graph = MagicMock()
        graph.ainvoke = AsyncMock(
            return_value={
                "advice": "AI-generated advisory is unavailable.",
                "advice_status": "unavailable",
                "risk": {},
                "sources": [],
                "mandi": {"prices": [], "error": "Provider unavailable"},
                "weather": {"daily": []},
                "soil": {"properties": {}},
            }
        )
        with patch("app.main.build_graph", return_value=graph):
            response = self.client.post(
                "/advise",
                json={
                    "latitude": 27.1767,
                    "longitude": 78.0081,
                    "language": "en",
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(
            result["location"],
            {"latitude": 27.1767, "longitude": 78.0081},
        )
        self.assertEqual(result["weather"]["latitude"], 27.1767)
        self.assertEqual(result["weather"]["longitude"], 78.0081)
        self.assertEqual(result["soil"]["latitude"], 27.1767)
        self.assertEqual(result["soil"]["longitude"], 78.0081)
        self.assertEqual(result["advice_status"], "unavailable")

    def test_advice_graph_timeout_returns_gateway_timeout(self) -> None:
        graph = MagicMock()

        async def slow_graph(_state):
            await asyncio.sleep(0.2)

        graph.ainvoke = AsyncMock(side_effect=slow_graph)
        with (
            patch("app.main.build_graph", return_value=graph),
            patch.object(settings, "ADVISE_TIMEOUT", 0.01),
        ):
            response = self.client.post(
                "/advise",
                json={"latitude": 27.1767, "longitude": 78.0081},
            )

        self.assertEqual(response.status_code, 504)
        self.assertIn("timed out", response.json()["detail"].lower())

    def test_missing_farm_and_incomplete_coordinates_are_explicit(self) -> None:
        missing_farm = self.client.get("/farms/not-found")
        self.assertEqual(missing_farm.status_code, 404)
        missing_location = self.client.post(
            "/advise",
            json={"latitude": 1, "language": "en"},
        )
        self.assertEqual(missing_location.status_code, 422)
        incomplete_farm = self.client.post(
            "/farms",
            json={
                "name": "Incomplete profile",
                "location": "Punjab",
                "latitude": 30.7,
            },
        )
        self.assertEqual(incomplete_farm.status_code, 201)
        incomplete_advice = self.client.post(
            "/advise",
            json={
                "farm_id": incomplete_farm.json()["id"],
                "latitude": 31,
                "longitude": 77,
            },
        )
        self.assertEqual(incomplete_advice.status_code, 422)


if __name__ == "__main__":
    unittest.main()
