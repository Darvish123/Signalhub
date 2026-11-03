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
    def test_zone_gate_rejects_price_close_outside_zone(self):
        rows=[row(i,100,101,99,100) for i in range(12)]
        rows[-1]=row(11,99.5,101,97,100.8)
        zone={"direction":"LONG","lower":101.0,"upper":102.0}
        result=analyse_price_action(rows,"LONG",zone=zone)
        self.assertEqual(result["status"],"NO_TRIGGER")
        self.assertIn("did not close inside",result["reason"])

    def test_zone_gate_accepts_pattern_inside_zone(self):
        rows=[row(i,100,101,99,100) for i in range(12)]
        rows[-1]=row(11,99.5,101,97,100.8)
        zone={"direction":"LONG","lower":100.0,"upper":101.0}
        result=analyse_price_action(rows,"LONG",zone=zone)
        self.assertEqual(result["status"],"TRIGGER_CONFIRMED")

    def test_bullish_pin_bar_added(self):
        rows=[row(i,100,101,96,100) for i in range(12)]
        rows[-1]=row(11,100.2,100.5,97,100.3)
        result=analyse_price_action(rows,"LONG")
        self.assertEqual(result["status"],"TRIGGER_CONFIRMED")
        self.assertEqual(result["trigger"]["pattern"],"BULLISH_PIN_BAR")

    def test_morning_star_added(self):
        rows=[row(i,100,101,99,100) for i in range(12)]
        rows[-3]=row(9,100,101,97,97.5)
        rows[-2]=row(10,97.4,98.0,97.0,97.5)
        rows[-1]=row(11,97.5,101.0,97.2,100.5)
        result=analyse_price_action(rows,"LONG")
        self.assertEqual(result["status"],"TRIGGER_CONFIRMED")
        self.assertEqual(result["trigger"]["pattern"],"MORNING_STAR")

    def test_inside_bar_breakout_added(self):
        rows=[row(i,100,101,99,100) for i in range(12)]
        rows[-3]=row(9,100,102,98,100)
        rows[-2]=row(10,100,101,99,100.5)
        rows[-1]=row(11,100.5,103,100,102.5)
        result=analyse_price_action(rows,"LONG")
        self.assertEqual(result["status"],"TRIGGER_CONFIRMED")
        self.assertEqual(result["trigger"]["pattern"],"INSIDE_BAR_BREAKOUT")

    def test_direction_filter(self):
        rows=[row(i,100,101,99,100) for i in range(12)]; rows[-1]=row(11,99.5,101,97,100.8)
        self.assertEqual(analyse_price_action(rows,"SHORT")["status"],"NO_TRIGGER")
if __name__=="__main__": unittest.main()
