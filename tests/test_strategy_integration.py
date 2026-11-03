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
             patch("app.strategy.build_zone_context", return_value={"status":"CONFIRMED","zone":{"direction":"LONG","lower":98.0,"upper":100.0,"invalidation":98.0,"source_4h":"ORDER_BLOCK","source_4h_index":50,"refined_by":"1H_ORDER_BLOCK","liquidity_nearby":True,"liquidity_evidence":[{"type":"EQUAL_LEVEL_POOL"}]},"h1_swings":[{"kind":"LOW","index":45,"price":94.0},{"kind":"LOW","index":50,"price":95.0},{"kind":"LOW","index":55,"price":96.0}]}), \
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
        self.assertEqual(signal.stop_loss, 94.0)
        self.assertGreater(signal.take_profit_1, signal.entry)
        self.assertGreaterEqual(signal.net_rr, 3.0)
        self.assertEqual(signal.score, 100)
        self.assertEqual(signal.analysis_context["zone_1h"]["lower"], 98.0)
        self.assertTrue(signal.analysis_context["liquidity"]["nearby"])
        self.assertEqual(signal.analysis_context["confirmation_15m"]["pattern"], "SWEEP_RECLAIM")
        self.assertTrue(any("15m Price Action" in reason for reason in signal.reasons))
        self.assertTrue(any("1H refined 4H zone" in reason for reason in signal.reasons))
        self.assertTrue(any("15m in-zone Price Action" in reason for reason in signal.reasons))

    def test_full_short_pipeline_builds_candidate_with_structural_risk(self):
        daily_short = candles(70, 86_400_000, self.now - 70 * 86_400_000,
                              lambda i: 150.0 - i * 0.5)
        h4_short_smc = {
            "structure_events": [{"direction": "BEARISH", "kind": "BOS", "index": 60}]
        }
        short_zone = {
            "status": "CONFIRMED",
            "zone": {
                "direction": "SHORT", "lower": 98.0, "upper": 100.0,
                "invalidation": 100.0, "source_4h": "ORDER_BLOCK",
                "source_4h_index": 50, "refined_by": "1H_ORDER_BLOCK",
                "liquidity_nearby": True,
                "liquidity_evidence": [{"type": "EQUAL_LEVEL_POOL"}],
            },
            "h1_swings": [
                {"kind": "HIGH", "index": 45, "price": 104.0},
                {"kind": "HIGH", "index": 50, "price": 105.0},
                {"kind": "HIGH", "index": 55, "price": 106.0},
            ],
        }
        short_pa = {
            "status": "TRIGGER_CONFIRMED",
            "trigger": {
                "direction": "SHORT", "pattern": "BEARISH_ENGULFING",
                "invalidation": 101.0, "trigger_level": 100.0,
            },
        }
        with patch("app.strategy.analyse_smc", return_value=h4_short_smc), \
             patch("app.strategy.build_zone_context", return_value=short_zone), \
             patch("app.strategy.analyse_price_action", return_value=short_pa):
            signal = analyse(
                "BTCUSDT", "USDT_PERP", daily_short, self.h4, self.h1,
                min_score=70, min_rr=3.0, min_quote_volume=1_000_000,
                round_trip_cost_bps=14.0, now_ms=self.now, lower_tf=self.m15,
            )
        self.assertEqual(signal.status, "CANDIDATE", signal.risks)
        self.assertEqual(signal.side, "SHORT")
        self.assertEqual(signal.entry, self.m15[-1].close)
        self.assertEqual(signal.stop_loss, 106.0)
        self.assertLess(signal.take_profit_1, signal.entry)
        self.assertGreaterEqual(signal.net_rr, 3.0)
        self.assertEqual(signal.analysis_context["directional_bias"]["direction"], "SHORT")

    def test_pipeline_rejects_higher_timeframe_candles_not_fully_closed(self):
        cases = (
            ("1D", self.daily, 86_400_000),
            ("4H", self.h4, 14_400_000),
            ("1H", self.h1, 3_600_000),
        )
        for label, source, duration in cases:
            with self.subTest(timeframe=label):
                rows = list(source)
                last = rows[-1]
                # The candle opened before decision time, but its interval has not ended.
                rows[-1] = Candle(self.now - 1, last.open, last.high, last.low,
                                  last.close, last.quote_volume, last.base_volume)
                inputs = {
                    "1D": (rows, self.h4, self.h1),
                    "4H": (self.daily, rows, self.h1),
                    "1H": (self.daily, self.h4, rows),
                }[label]
                signal = analyse(
                    "BTCUSDT", "USDT_PERP", *inputs,
                    min_score=70, min_rr=3.0, min_quote_volume=1_000_000,
                    round_trip_cost_bps=14.0, now_ms=self.now,
                    lower_tf=self.m15,
                )
                self.assertEqual(signal.status, "NO_TRADE")
                self.assertIn("not fully closed", signal.risks[0])

    def test_pipeline_fails_closed_when_no_refined_zone_or_liquidity(self):
        with patch("app.strategy.analyse_smc", return_value=self.h4_smc), \
             patch("app.strategy.build_zone_context", return_value={"status":"NO_ZONE","zone":None,"reason":"No 1H liquidity near the 4H zone"}):
            signal = analyse("BTCUSDT", "USDT_PERP", self.daily, self.h4, self.h1,
                min_score=70, min_rr=3.0, min_quote_volume=1_000_000,
                round_trip_cost_bps=14.0, now_ms=self.now, lower_tf=self.m15)
        self.assertEqual(signal.status, "NO_TRADE")
        self.assertIn("No 1H liquidity", signal.risks[0])

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
