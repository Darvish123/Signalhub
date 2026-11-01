import unittest
from app.models import Candle
from app.data_quality import audit_candles,validated_candles
class DataQualityTests(unittest.TestCase):
 def test_valid_continuous_series(self):
  rows=[Candle(i*60000,10,11,9,10,100,1) for i in range(3)]
  self.assertEqual(audit_candles(rows,60000)["accepted_count"],3)
  self.assertEqual(len(validated_candles(rows,60000)),3)
 def test_invalid_ohlc_quarantined(self):
  rows=[Candle(0,10,8,9,10,100,1)]
  self.assertIn("high_below_ohlc_component",audit_candles(rows,60000)["invalid"][0]["reasons"])
  with self.assertRaises(ValueError): validated_candles(rows,60000)
 def test_duplicate_and_gap_detected(self):
  rows=[Candle(0,10,11,9,10),Candle(0,10,11,9,10),Candle(120000,10,11,9,10)]
  report=audit_candles(rows,60000)
  self.assertEqual(len(report["duplicate_timestamps_ms"]),1)
  self.assertTrue(report["discontinuities"])
if __name__=="__main__": unittest.main()
