from __future__ import annotations

import unittest

from app.services.risk_engine import compute_risk


class RiskEngineTests(unittest.TestCase):
    def test_available_forecast_values_are_scored_without_static_citations(self) -> None:
        report = compute_risk(
            weather={
                "max_temp": 36.0,
                "precipitation_total": 10.0,
                "retrieved_at": "2026-10-31T00:00:00+00:00",
                "daily": [{"date": "2026-10-31"}, {"date": "2026-11-01"}],
            },
            soil={
                "properties": {"clay": 0.4},
                "retrieved_at": "2026-10-30T00:00:00+00:00",
            },
            mandi={},
            crop="wheat",
        )
        self.assertEqual(report.heat_wave, 58)
        self.assertEqual(report.flood, 25)
        self.assertIsNone(report.water_logging)
        self.assertIsNone(report.drought)
        self.assertEqual(report.overall, 58)
        self.assertEqual(report.category, "moderate")
        self.assertIn("2026-10-31 to 2026-11-01", report.assessment_period)
        self.assertTrue(all("2026-10-30T16:12Z" not in source for source in report.sources))
        self.assertTrue(any("not statistically calibrated" in item for item in report.data_quality))
        self.assertTrue(any("not current field-moisture measurements" in item for item in report.data_quality))

    def test_missing_provider_data_does_not_become_a_low_risk_score(self) -> None:
        report = compute_risk(
            weather={"max_temp": None, "precipitation_total": None},
            soil={"properties": {}, "error": "Provider unavailable"},
            mandi={"error": "Market data unavailable"},
        )
        self.assertIsNone(report.heat_wave)
        self.assertIsNone(report.flood)
        self.assertIsNone(report.overall)
        self.assertIsNone(report.category)
        self.assertTrue(any("Soil estimates unavailable" in item for item in report.data_quality))
        self.assertTrue(any("Market data unavailable" in item for item in report.data_quality))

    def test_rain_score_accepts_zero_without_substituting_a_default(self) -> None:
        report = compute_risk(
            weather={
                "max_temp": 25,
                "precipitation_total": 0,
                "retrieved_at": "2026-10-31T00:00:00+00:00",
            },
            soil={},
            mandi={},
        )
        self.assertEqual(report.flood, 0)
        self.assertEqual(report.heat_wave, 0)
        self.assertEqual(report.overall, 0)
        self.assertEqual(report.category, "low")


if __name__ == "__main__":
    unittest.main()
