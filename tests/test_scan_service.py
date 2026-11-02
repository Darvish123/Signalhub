"""Tests for application-level scan orchestration and risk gating."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.models import Candle, Signal
from app.services.scan_service import ScanService


class FakeClient:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    async def futures_klines(self, symbol, interval, limit):
        self.calls.append((symbol, interval, limit))
        return self.rows[interval]


class FakeStore:
    def __init__(self):
        self.saved = []

    def save(self, signal):
        self.saved.append(signal)
        return len(self.saved)


def make_candles(now_ms, step_ms, count=70):
    latest_closed_open = (now_ms // step_ms) * step_ms - step_ms
    start = latest_closed_open - (count - 1) * step_ms
    return [
        Candle(start + i * step_ms, 99.0, 101.0, 98.0, 100.0, 10_000.0, 100.0)
        for i in range(count)
    ]


def sample_signal():
    return Signal(
        symbol="BTCUSDT", market="FUTURES", side="LONG", status="CANDIDATE",
        score=90, entry=100.0, stop_loss=98.0, take_profit_1=106.0,
        take_profit_2=106.0, net_rr=3.0, reasons=["fixture"], risks=[],
        created_at_ms=1,
    )


class ScanServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.now_ms = 2_000_000_000_000
        self.steps = {
            "1d": 86_400_000,
            "4h": 14_400_000,
            "1h": 3_600_000,
            "15m": 900_000,
        }
        rows = {
            interval: make_candles(self.now_ms, step)
            for interval, step in self.steps.items()
        }
        self.client = FakeClient(rows)
        self.store = FakeStore()
        self.settings = SimpleNamespace(
            paper_equity_quote=1000.0,
            risk_per_trade_pct=0.5,
            max_leverage=1.0,
            max_notional_quote=0.0,
            round_trip_cost_bps=14.0,
            min_score=70,
            min_net_rr=3.0,
            min_quote_volume_24h=1_000_000.0,
        )
        self.service = ScanService(self.client, self.store, self.settings)

    async def test_scan_fetches_all_strategy_timeframes_and_persists_risk_gated_signal(self):
        risk_plan = SimpleNamespace(
            allowed=True,
            to_dict=lambda: {"allowed": True, "mode": "paper"},
        )
        with patch("app.services.scan_service.time.time_ns", return_value=self.now_ms * 1_000_000), \
             patch("app.services.scan_service.analyse", return_value=sample_signal()) as strategy, \
             patch("app.services.scan_service.evaluate_signal_risk", return_value=risk_plan):
            result = await self.service.scan_one("btcusdt")

        self.assertEqual(result["id"], 1)
        self.assertEqual(result["status"], "CANDIDATE")
        self.assertEqual(result["risk_plan"]["mode"], "paper")
        self.assertEqual(
            {call[1] for call in self.client.calls},
            {"1d", "4h", "1h", "15m"},
        )
        strategy.assert_called_once()
        self.assertEqual(len(self.store.saved), 1)

    async def test_risk_rejection_is_persisted_as_no_trade(self):
        risk_plan = SimpleNamespace(
            allowed=False,
            reason="paper risk limit",
            to_dict=lambda: {"allowed": False, "reason": "paper risk limit"},
        )
        with patch("app.services.scan_service.time.time_ns", return_value=self.now_ms * 1_000_000), \
             patch("app.services.scan_service.analyse", return_value=sample_signal()), \
             patch("app.services.scan_service.evaluate_signal_risk", return_value=risk_plan):
            result = await self.service.scan_one("BTCUSDT")

        self.assertEqual(result["status"], "NO_TRADE")
        self.assertTrue(any("paper risk limit" in reason for reason in result["risks"]))
        self.assertEqual(self.store.saved[0].status, "NO_TRADE")


if __name__ == "__main__":
    unittest.main()
