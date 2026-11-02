"""Tests for SQLite signal persistence and API-facing lookup methods."""
import tempfile
import unittest
from pathlib import Path

from app.models import Signal
from app.storage import SignalStore


def sample_signal(symbol="BTCUSDT", created_at_ms=123456789):
    return Signal(
        symbol=symbol,
        market="FUTURES",
        side="LONG",
        status="CANDIDATE",
        score=85,
        entry=100.0,
        stop_loss=98.0,
        take_profit_1=106.0,
        take_profit_2=108.0,
        net_rr=3.0,
        reasons=["test candidate"],
        risks=[],
        created_at_ms=created_at_ms,
    )


class SignalStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "signals.sqlite3")
        self.store = SignalStore(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_health_check(self):
        self.assertIsNone(self.store.check())

    def test_save_and_get_round_trip(self):
        signal_id = self.store.save(sample_signal())
        row = self.store.get(signal_id)
        self.assertIsNotNone(row)
        self.assertEqual(row["id"], signal_id)
        self.assertEqual(row["symbol"], "BTCUSDT")
        self.assertEqual(row["risk_plan"], {})

    def test_missing_or_invalid_id_returns_none(self):
        self.assertIsNone(self.store.get(999))
        self.assertIsNone(self.store.get(0))
        self.assertIsNone(self.store.get(-1))

    def test_latest_is_newest_first_and_respects_limit(self):
        first = self.store.save(sample_signal("BTCUSDT", 1))
        second = self.store.save(sample_signal("ETHUSDT", 2))
        rows = self.store.latest(1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], second)
        self.assertEqual(self.store.latest(2)[1]["id"], first)

    def test_latest_rejects_non_positive_limit(self):
        with self.assertRaises(ValueError):
            self.store.latest(0)


if __name__ == "__main__":
    unittest.main()
