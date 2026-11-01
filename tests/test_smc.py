import unittest
from app.models import Candle
from app.smc import (fair_value_gaps, confirmed_swings, liquidity_sweeps,
                     premium_discount, analyse_smc, order_blocks, StructureEvent)

def c(i,o,h,l,cl):
    return Candle(i*60000,o,h,l,cl,1000,10)

class SMCTests(unittest.TestCase):
    def test_bullish_fvg(self):
        gaps=fair_value_gaps([c(0,10,11,9,10),c(1,11,13,10,12),c(2,12,14,11.5,13)])
        self.assertEqual((gaps[0].direction,gaps[0].lower,gaps[0].upper),("BULLISH",11,11.5))
    def test_bearish_fvg(self):
        gaps=fair_value_gaps([c(0,13,14,12,13),c(1,12,13,10,11),c(2,10,11,9,10)])
        self.assertEqual(gaps[0].direction,"BEARISH")
    def test_confirmed_swings_and_labels(self):
        vals=[(10,8),(12,7),(15,6),(12,7),(11,8),(13,7),(16,6),(12,8),(10,9)]
        rows=[c(i,h,h,l,h) for i,(h,l) in enumerate(vals)]
        swings=confirmed_swings(rows,1,1)
        self.assertTrue(any(s.label=="HH" for s in swings if s.kind=="HIGH"))
    def test_premium_discount_requires_adjacent_pair(self):
        rows=[c(i,10,11,9,10) for i in range(8)]
        self.assertEqual(premium_discount(rows,[] )["status"],"UNAVAILABLE")
        swings=[type("S",(),{"index":2,"kind":"LOW","price":8})(),
                type("S",(),{"index":4,"kind":"HIGH","price":12})()]
        self.assertEqual(premium_discount(rows,swings)["zone"],"DISCOUNT")
    def test_order_block_mitigation(self):
        rows=[c(0,10,11,9,10),c(1,10,12,9,11),c(2,11,12,10,11),
              c(3,11,12,10,11),c(4,11,12,9.5,10.5),c(5,10.5,11,8,8.5)]
        event=StructureEvent(3,rows[3].time_ms,"BOS","BULLISH",11.5,12)
        ob=order_blocks(rows,[event],lookback=3)[0]
        self.assertEqual(ob.mitigation,"INVALIDATED")
        self.assertEqual(ob.mitigation_index,5)
    def test_sweep_consumes_level_once(self):
        rows=[c(0,10,11,9,10),c(1,10,12,9.5,11),c(2,11,11.5,10,11),
              c(3,11,12.5,10.5,11.2),c(4,11.2,12.8,10.6,11.1)]
        swings=[type("S",(),{"index":0,"kind":"HIGH","price":11})()]
        found=liquidity_sweeps(rows,swings,0)
        self.assertEqual(len(found),1)
    def test_rejects_non_chronological_candles(self):
        rows=[c(0,10,11,9,10),c(2,10,11,9,10),c(1,10,11,9,10),c(3,10,11,9,10),c(4,10,11,9,10),c(5,10,11,9,10),c(6,10,11,9,10)]
        with self.assertRaises(ValueError): analyse_smc(rows)
    def test_analysis_rejects_short_input(self):
        with self.assertRaises(ValueError): analyse_smc([c(0,10,11,9,10)])
if __name__=="__main__": unittest.main()
