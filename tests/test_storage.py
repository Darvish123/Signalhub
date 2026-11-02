import os
import tempfile
import unittest

from app.models import Signal
from app.storage import SignalStore


class SignalStoreTests(unittest.TestCase):
    def test_health_check_and_signal_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SignalStore(os.path.join(tmp, "signals.db"))
            self.assertTrue(store.check())
            signal = Signal(
                symbol="BTCUSDT", market="FUTURES", side="NONE",
                status="NO_TRADE", score=0, entry=None, stop_loss=None,
                take_profit_1=None, take_profit_2=None, net_rr=None,
                reasons=["test"], risks=["no setup"], created_at_ms=123456,
            )
            signal_id = store.save(signal)
            fetched = store.get(signal_id)
            self.assertEqual(fetched["id"], signal_id)
            self.assertEqual(fetched["symbol"], "BTCUSDT")
            self.assertEqual(fetched["status"], "NO_TRADE")
            self.assertEqual(store.latest(1)[0]["id"], signal_id)

    def test_missing_signal_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SignalStore(os.path.join(tmp, "signals.db"))
            self.assertIsNone(store.get(999))
            self.assertIsNone(store.get(0))


if __name__ == "__main__":
    unittest.main()
