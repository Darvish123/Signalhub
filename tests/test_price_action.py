import unittest
from app.models import Candle
from app.price_action import analyse_price_action

def row(i,o,h,l,c): return Candle(i*900000,o,h,l,c,1000,10)
class PriceActionTests(unittest.TestCase):
    def test_bullish_sweep_reclaim(self):
        rows=[row(i,100,101,99,100) for i in range(12)]; rows[-1]=row(11,99.5,101,97,100.8)
        r=analyse_price_action(rows,"LONG"); self.assertEqual(r["status"],"TRIGGER_CONFIRMED"); self.assertEqual(r["trigger"]["pattern"],"SWEEP_RECLAIM")
    def test_bearish_sweep_reclaim(self):
        rows=[row(i,100,101,99,100) for i in range(12)]; rows[-1]=row(11,100.5,103,99,99.2)
        self.assertEqual(analyse_price_action(rows,"SHORT")["status"],"TRIGGER_CONFIRMED")
    def test_no_trigger(self):
        rows=[row(i,100,101,99,100) for i in range(12)]; self.assertEqual(analyse_price_action(rows)["status"],"NO_TRIGGER")
    def test_bad_chronology(self):
        rows=[row(i,100,101,99,100) for i in range(12)]; rows[-1]=row(10,100,101,99,100)
        with self.assertRaises(ValueError): analyse_price_action(rows)
    def test_direction_filter(self):
        rows=[row(i,100,101,99,100) for i in range(12)]; rows[-1]=row(11,99.5,101,97,100.8)
        self.assertEqual(analyse_price_action(rows,"SHORT")["status"],"NO_TRIGGER")
if __name__=="__main__": unittest.main()
