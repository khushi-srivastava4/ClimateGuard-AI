from __future__ import annotations

import unittest
from datetime import date

from app.services.field_planner import build_field_plan


class FieldPlannerTests(unittest.TestCase):
    def test_heavy_rain_avoids_irrigation_and_checks_drainage(self) -> None:
        plan = build_field_plan(
            {
                "daily": [
                    {
                        "date": date.today().isoformat(),
                        "precipitation_sum": 28.0,
                        "precipitation_probability_max": 90,
                    }
                ]
            },
            crop="rice",
        )
        self.assertEqual(len(plan), 1)
        self.assertIn("drain", plan[0]["action"].lower())
        self.assertNotIn("irrigat", plan[0]["action"].lower())

    def test_heat_and_dry_day_generate_conditional_checks(self) -> None:
        plan = build_field_plan(
            {
                "daily": [
                    {
                        "date": date.today().isoformat(),
                        "temperature_2m_max": 38,
                        "precipitation_sum": 0.0,
                        "precipitation_probability_max": 10,
                    }
                ]
            },
            crop="wheat",
        )
        self.assertEqual(len(plan), 2)
        self.assertTrue(any("heat stress" in item["action"] for item in plan))
        irrigation_check = next(item for item in plan if "irrigate" in item["action"])
        self.assertIn("only if", irrigation_check["condition"])
        self.assertIn("no current soil-moisture measurement", irrigation_check["precaution"])

    def test_missing_forecast_produces_no_invented_actions(self) -> None:
        self.assertEqual(build_field_plan({}, crop="wheat"), [])


if __name__ == "__main__":
    unittest.main()
