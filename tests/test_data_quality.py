import unittest
from app.models import Candle
from app.exchange import validate_fresh_candles, ExchangeError
class FreshnessTests(unittest.TestCase):
    def rows(self,step=900000):
        return [Candle(1_800_000_000_000+i*step,10,11,9,10,100,1) for i in range(4)]
    def test_accepts_recent_regular_series(self):
        rows=self.rows()
        validate_fresh_candles(rows,"15m",now_ms=rows[-1].time_ms+1000)
    def test_rejects_stale_series(self):
        rows=self.rows()
        with self.assertRaises(ExchangeError): validate_fresh_candles(rows,"15m",now_ms=rows[-1].time_ms+3_000_000)
    def test_rejects_large_gap(self):
        rows=self.rows(); rows[2]=Candle(rows[1].time_ms+2_000_000,10,11,9,10,100,1)
        with self.assertRaises(ExchangeError): validate_fresh_candles(rows,"15m",now_ms=rows[-1].time_ms)
    def test_rejects_unaligned_timestamps(self):
        rows=self.rows(); rows[1]=Candle(rows[1].time_ms+1,10,11,9,10,100,1)
        with self.assertRaises(ExchangeError): validate_fresh_candles(rows,"15m",now_ms=rows[-1].time_ms)
    def test_rejects_future_series(self):
        rows=self.rows()
        with self.assertRaises(ExchangeError): validate_fresh_candles(rows,"15m",now_ms=rows[-1].time_ms-2_000_000)
if __name__=="__main__": unittest.main()
