import unittest
from app.models import Candle
from app.backtest import aggregate,run_backtest,load_csv
import tempfile, pathlib
class BacktestTests(unittest.TestCase):
 def test_aggregate_ohlcv(self):
  rows=[Candle(i*900000,10+i,12+i,9+i,11+i,100,2) for i in range(4)]
  x=aggregate(rows,3600000)
  self.assertEqual(len(x),1); self.assertEqual((x[0].open,x[0].high,x[0].low,x[0].close,x[0].quote_volume),(10,15,9,14,400))
 def test_stop_first_same_bar_policy_documented(self):
  rows=[Candle(i*900000,100,101,99,100,1000,10) for i in range(600)]
  result=run_backtest(rows,"TESTUSDT",rows[500].time_ms,rows[-1].time_ms)
  self.assertEqual(result["timeframe"],"15m")
  self.assertIn("stop wins",result["execution"])
 def test_csv_validation(self):
  with tempfile.TemporaryDirectory() as d:
   p=pathlib.Path(d)/"x.csv"; p.write_text("timestamp_ms,open,high,low,close\n1,10,11,9,10\n",encoding="utf8")
   with self.assertRaises(ValueError): load_csv(str(p))
if __name__=="__main__": unittest.main()
