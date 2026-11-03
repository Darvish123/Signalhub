import unittest
from unittest.mock import patch

from app.models import Candle
from app.zones import build_zone_context


def candles(n, step):
    return [Candle(i * step, 100.0, 101.0, 99.0, 100.0, 1000.0, 10.0)
            for i in range(n)]


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
            "liquidity_pools": [{
                "kind": "SSL", "level": 99.0, "status": "RESTING",
            }],
            "liquidity_sweeps": [],
        }

    def test_refines_4h_zone_and_requires_nearby_liquidity(self):
        with patch("app.zones.analyse_smc",
                   side_effect=[self.h4_result, self.h1_result]):
            result = build_zone_context(self.h4, self.h1, "LONG")
        self.assertEqual(result["status"], "CONFIRMED")
        self.assertEqual(result["zone"]["lower"], 99.5)
        self.assertEqual(result["zone"]["upper"], 100.5)
        self.assertEqual(result["zone"]["refined_by"], "1H_ORDER_BLOCK")
        self.assertTrue(result["zone"]["liquidity_nearby"])

    def test_rejects_zone_without_nearby_liquidity(self):
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
