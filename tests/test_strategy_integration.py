"""Integration tests for the complete multi-timeframe strategy orchestration.

The SMC/ICT/PA detectors are isolated with deterministic fixtures here so these
tests verify that the real strategy function wires every stage and risk gate
together. Detector algorithms retain their own unit tests.
"""
import unittest
from unittest.mock import patch

from app.models import Candle
from app.strategy import analyse, meets_minimum_rr


def candles(count, interval_ms, start_ms, close_fn=None, quote_volume=100_000):
    rows = []
    for i in range(count):
        close = close_fn(i) if close_fn else 100.0
        rows.append(Candle(
            start_ms + i * interval_ms,
            close - 0.2, close + 1.0, close - 1.0, close,
            quote_volume, 1000.0,
        ))
    return rows


class StrategyIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.now = 20_000_000_000
        self.daily = candles(70, 86_400_000, self.now - 70 * 86_400_000,
                             lambda i: 80.0 + i * 0.5)
        self.h4 = candles(70, 14_400_000, self.now - 70 * 14_400_000)
        self.h1 = candles(70, 3_600_000, self.now - 70 * 3_600_000)
        self.m15 = candles(24, 900_000, self.now - 24 * 900_000)
        self.h4_smc = {
            "structure_events": [{"direction": "BULLISH", "kind": "BOS", "index": 60}]
        }
        self.h1_smc = {
            "structure_events": [{"direction": "BULLISH", "kind": "CHoCH", "index": 60}],
            "liquidity_sweeps": [{"direction": "BULLISH", "index": 58}],
            "fair_value_gaps": [{"direction": "BULLISH", "index": 60}],
            "order_blocks": [{
                "direction": "BULLISH", "mitigation": "UNMITIGATED",
                "index": 55, "lower": 98.0, "upper": 100.0,
            }],
            "swings": [
                {"kind": "LOW", "index": 45, "price": 94.0},
                {"kind": "LOW", "index": 50, "price": 95.0},
                {"kind": "LOW", "index": 55, "price": 96.0},
            ],
        }
        self.ict = {
            "status": "ICT_CONFIRMED",
            "setup": {
                "direction": "LONG", "tap_index": 69,
                "sweep_extreme": 95.0, "fvg_low": 98.5, "fvg_high": 99.5,
                "in_ote": True, "premium_discount": "DISCOUNT",
                "killzone": "NEW_YORK_AM",
            },
        }
        self.pa = {
            "status": "TRIGGER_CONFIRMED",
            "trigger": {
                "direction": "LONG", "pattern": "SWEEP_RECLAIM",
                "invalidation": 97.0, "trigger_level": 98.0,
            },
        }

    def run_pipeline(self, pa_result=None, lower_tf=None):
        with patch("app.strategy.analyse_smc",
                   side_effect=[self.h4_smc, self.h1_smc]), \
             patch("app.strategy.analyse_ict", return_value=self.ict), \
             patch("app.strategy.analyse_price_action",
                   return_value=pa_result or self.pa):
            return analyse(
                "BTCUSDT", "USDT_PERP", self.daily, self.h4, self.h1,
                min_score=70, min_rr=3.0, min_quote_volume=1_000_000,
                round_trip_cost_bps=14.0, now_ms=self.now,
                lower_tf=lower_tf if lower_tf is not None else self.m15,
            )

    def test_full_long_pipeline_builds_candidate_with_structural_risk(self):
        signal = self.run_pipeline()
        self.assertEqual(signal.status, "CANDIDATE", signal.risks)
        self.assertEqual(signal.side, "LONG")
        self.assertEqual(signal.entry, self.m15[-1].close)
        self.assertLess(signal.stop_loss, 94.0)
        self.assertGreater(signal.take_profit_1, signal.entry)
        self.assertGreaterEqual(signal.net_rr, 3.0)
        self.assertEqual(signal.score, 100)
        self.assertTrue(any("15m Price Action" in reason for reason in signal.reasons))
        self.assertTrue(any("ICT sequence confirmed" in reason for reason in signal.reasons))

    def test_pipeline_fails_closed_when_15m_trigger_is_missing(self):
        no_pa = {"status": "NO_TRIGGER", "trigger": None,
                 "reason": "No aligned 15m trigger"}
        signal = self.run_pipeline(pa_result=no_pa)
        self.assertEqual(signal.status, "NO_TRADE")
        self.assertEqual(signal.side, "NONE")
        self.assertIn("No aligned 15m trigger", signal.risks[0])
        self.assertIsNone(signal.entry)

    def test_pipeline_rejects_unclosed_15m_candle(self):
        future_rows = list(self.m15)
        last = future_rows[-1]
        future_rows[-1] = Candle(self.now - 800_000, last.open, last.high,
                                 last.low, last.close, last.quote_volume,
                                 last.base_volume)
        signal = self.run_pipeline(lower_tf=future_rows)
        self.assertEqual(signal.status, "NO_TRADE")
        self.assertIn("not fully closed", signal.risks[0])

    def test_pipeline_rejects_invalid_15m_ohlc(self):
        bad_rows = list(self.m15)
        last = bad_rows[-1]
        bad_rows[-1] = Candle(last.time_ms, last.open, last.high,
                              last.low, last.high + 5, last.quote_volume,
                              last.base_volume)
        signal = self.run_pipeline(lower_tf=bad_rows)
        self.assertEqual(signal.status, "NO_TRADE")
        self.assertIn("invalid", signal.risks[0])

    def test_minimum_rr_accepts_boundary_with_float_noise(self):
        self.assertTrue(meets_minimum_rr(2.9999999999, 3.0))
        self.assertTrue(meets_minimum_rr(3.0, 3.0))
        self.assertFalse(meets_minimum_rr(2.99999, 3.0))


if __name__ == "__main__":
    unittest.main()
