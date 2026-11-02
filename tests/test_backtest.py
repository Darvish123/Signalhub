import unittest
from unittest.mock import patch
from app.models import Candle,Signal
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

 def test_funding_is_applied_to_a_position_open_at_settlement(self):
  rows=[Candle(i*3600000,100,100.5,99.5,100,1000,10) for i in range(1700)]
  start=rows[1500].time_ms
  signal=Signal(symbol="TESTUSDT",market="FUTURES",side="LONG",status="CANDIDATE",
      score=90,entry=100,stop_loss=98,take_profit_1=107,take_profit_2=107,
      net_rr=3.1,reasons=[],risks=[],created_at_ms=start)
  rate=FundingRate(rows[1508].time_ms+1,.001,100)
  no_trade=Signal(symbol="TESTUSDT",market="FUTURES",side="NONE",status="NO_TRADE",
      score=0,entry=None,stop_loss=None,take_profit_1=None,take_profit_2=None,
      net_rr=None,reasons=[],risks=[],created_at_ms=start)
  with patch("app.backtest.analyse",side_effect=[signal]+[no_trade for _ in range(1000)]):
   result=run_backtest(rows,"TESTUSDT",start,rows[-1].time_ms,
                       funding_rates=[rate],max_hold_bars=24)
  self.assertGreaterEqual(len(result["trades"]),1)
  self.assertLess(result["trades"][0]["funding_pnl_pct_equity"],0)
  self.assertEqual(result["trades"][0]["exit_reason"],"TIME")

 def test_no_trade_reasons_are_counted_for_diagnostics(self):
  rows=[Candle(i*3600000,100,101,99,100,1000,10) for i in range(1700)]
  start=rows[1500].time_ms
  no_trade=Signal(symbol="TESTUSDT",market="FUTURES",side="NONE",status="NO_TRADE",
      score=0,entry=None,stop_loss=None,take_profit_1=None,take_profit_2=None,
      net_rr=None,reasons=[],risks=["1D trend is not aligned"],created_at_ms=start)
  with patch("app.backtest.analyse",return_value=no_trade):
   result=run_backtest(rows,"TESTUSDT",start,rows[-1].time_ms)
  self.assertGreater(result["signal_diagnostics"].get("1D trend is not aligned",0),0)

if __name__=="__main__": unittest.main()
