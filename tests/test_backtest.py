import unittest
from app.models import Candle
from app.backtest import aggregate,run_backtest,position_fraction_for_risk
from app.funding import FundingRate
class BacktestTests(unittest.TestCase):
 def test_hourly_aggregate(self):
  rows=[Candle(i*3600000,10+i,12+i,9+i,11+i,100,2) for i in range(24)]
  x=aggregate(rows,86400000)
  self.assertEqual(len(x),1); self.assertEqual((x[0].open,x[0].high,x[0].low,x[0].close,x[0].quote_volume),(10,35,9,34,2400))
 def test_risk_budget_position_sizing(self):
  self.assertAlmostEqual(position_fraction_for_risk(100,98,.5,1.),.25)
  self.assertEqual(position_fraction_for_risk(100,99.99,.5,1.),1.)
  with self.assertRaises(ValueError): position_fraction_for_risk(100,100,.5,1.)
 def test_funding_report_tracks_loaded_settlements(self):
  rows=[Candle(i*3600000,100,101,99,100,1000,10) for i in range(1600)]
  rates=[FundingRate(rows[1500].time_ms+1,.001,100)]
  result=run_backtest(rows,"TESTUSDT",rows[1500].time_ms,rows[-1].time_ms,funding_rates=rates)
  self.assertEqual(result["initial_equity"],100.)
  self.assertEqual(result["funding_settlements_in_test_window"],1)
if __name__=="__main__": unittest.main()
