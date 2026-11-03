import unittest
from unittest.mock import patch

from app.models import Candle
from app.zones import build_zone_context


def candles(n, step, close=100.0):
    return [Candle(i * step, close, close + 1.0, close - 1.0, close,
                   1000.0, 10.0) for i in range(n)]


class ZonePipelineTests(unittest.TestCase):
    def setUp(self):
        self.h4 = candles(60, 14_400_000)
        self.h1 = candles(80, 3_600_000)
        self.h4_result = {
            "order_blocks": [{
                "direction": "BULLISH", "mitigation": "UNMITIGATED",
                "lower": 99.0, "upper": 101.0, "index": 50,
            }],
        }
        self.h1_result = {
            "order_blocks": [{
                "direction": "BULLISH", "mitigation": "UNMITIGATED",
                "lower": 99.5, "upper": 100.5, "index": 65,
            }],
            "fair_value_gaps": [],
            "fvg_lifecycle": [],
            "liquidity_pools": [{
                "kind": "SSL", "level": 99.0, "status": "RESTING",
            }],
            "liquidity_sweeps": [],
            "swings": [],
        }

    def test_refines_4h_zone_with_1h_overlap_and_parent_zone_liquidity(self):
        with patch("app.zones.analyse_smc",
                   side_effect=[self.h4_result, self.h1_result]):
            result = build_zone_context(self.h4, self.h1, "LONG")
        self.assertEqual(result["status"], "CONFIRMED")
        self.assertEqual(result["zone"]["lower"], 99.5)
        self.assertEqual(result["zone"]["upper"], 100.5)
        self.assertEqual(result["zone"]["refined_by"], "1H_ORDER_BLOCK")
        self.assertTrue(result["zone"]["liquidity_nearby"])
        self.assertEqual(result["zone"]["liquidity_evidence"][0]["level"], 99.0)
        self.assertNotIn("distance_atr_4h", result["zone"])
        self.assertNotIn("distance_atr", result["zone"]["liquidity_evidence"][0])

    def test_rejects_liquidity_outside_parent_4h_zone_without_atr_radius(self):
        outside = dict(self.h1_result)
        outside["liquidity_pools"] = [{
            "kind": "SSL", "level": 98.0, "status": "RESTING",
        }]
        with patch("app.zones.analyse_smc",
                   side_effect=[self.h4_result, outside]):
            result = build_zone_context(self.h4, self.h1, "LONG")
        self.assertEqual(result["status"], "NO_ZONE")
        self.assertIsNone(result["zone"])

    def test_accepts_recent_aligned_sweep_level_inside_parent_zone(self):
        sweep_result = dict(self.h1_result)
        sweep_result["liquidity_pools"] = []
        sweep_result["liquidity_sweeps"] = [{
            "direction": "BULLISH", "index": 75,
            "swept_level": 99.2, "wick_extreme": 98.8,
        }]
        with patch("app.zones.analyse_smc",
                   side_effect=[self.h4_result, sweep_result]):
            result = build_zone_context(self.h4, self.h1, "LONG")
        self.assertEqual(result["status"], "CONFIRMED")
        evidence = result["zone"]["liquidity_evidence"][0]
        self.assertEqual(evidence["type"], "RECENT_SWEEP")
        self.assertEqual(evidence["level"], 99.2)

    def test_selects_nearest_structurally_accessible_4h_zone(self):
        h4_result = {
            "order_blocks": [
                {"direction": "BULLISH", "mitigation": "UNMITIGATED",
                 "lower": 90.0, "upper": 92.0, "index": 55},
                {"direction": "BULLISH", "mitigation": "UNMITIGATED",
                 "lower": 99.0, "upper": 101.0, "index": 40},
            ],
        }
        with patch("app.zones.analyse_smc",
                   side_effect=[h4_result, self.h1_result]):
            result = build_zone_context(self.h4, self.h1, "LONG")
        self.assertEqual(result["status"], "CONFIRMED")
        self.assertEqual(result["zone"]["source_4h_index"], 40)


    def test_short_zone_uses_bsl_pool_inside_parent_supply_zone(self):
        h4_result = {
            "order_blocks": [{
                "direction": "BEARISH", "mitigation": "UNMITIGATED",
                "lower": 99.0, "upper": 101.0, "index": 50,
            }],
        }
        h1_result = {
            "order_blocks": [{
                "direction": "BEARISH", "mitigation": "UNMITIGATED",
                "lower": 99.5, "upper": 100.5, "index": 65,
            }],
            "fair_value_gaps": [],
            "fvg_lifecycle": [],
            "liquidity_pools": [{
                "kind": "BSL", "level": 101.0, "status": "RESTING",
            }],
            "liquidity_sweeps": [],
            "swings": [],
        }
        # Make the latest price below the bearish supply zone so it is an
        # accessible short-side pullback candidate.
        h1 = candles(80, 3_600_000, close=98.0)
        with patch("app.zones.analyse_smc",
                   side_effect=[h4_result, h1_result]):
            result = build_zone_context(self.h4, h1, "SHORT")
        self.assertEqual(result["status"], "CONFIRMED")
        self.assertEqual(result["zone"]["direction"], "SHORT")
        self.assertEqual(result["zone"]["liquidity_evidence"][0]["kind"], "BSL")

    def test_rejects_zone_without_aligned_liquidity(self):
        no_liquidity = dict(self.h1_result, liquidity_pools=[], liquidity_sweeps=[])
        with patch("app.zones.analyse_smc",
                   side_effect=[self.h4_result, no_liquidity]):
            result = build_zone_context(self.h4, self.h1, "LONG")
        self.assertEqual(result["status"], "NO_ZONE")
        self.assertIsNone(result["zone"])

    def test_rejects_invalid_direction(self):
        with self.assertRaises(ValueError):
            build_zone_context(self.h4, self.h1, "SIDEWAYS")


if __name__ == "__main__":
    unittest.main()
