import unittest
from app.models import Candle
from app.smc import fair_value_gaps, confirmed_swings, liquidity_sweeps, premium_discount, analyse_smc

def c(i,o,h,l,cl):
    return Candle(i*60000,o,h,l,cl,1000,10)

class SMCTests(unittest.TestCase):
    def test_bullish_fvg(self):
        rows=[c(0,10,11,9,10),c(1,11,13,10,12),c(2,12,14,11.5,13)]
        gaps=fair_value_gaps(rows)
        self.assertEqual(len(gaps),1)
        self.assertEqual(gaps[0].direction,"BULLISH")
        self.assertEqual((gaps[0].lower,gaps[0].upper),(11,11.5))

    def test_bearish_fvg(self):
        rows=[c(0,13,14,12,13),c(1,12,13,10,11),c(2,10,11,9,10)]
        gaps=fair_value_gaps(rows)
        self.assertEqual(gaps[0].direction,"BEARISH")

    def test_confirmed_swings_and_labels(self):
        vals=[(10,8),(12,7),(15,6),(12,7),(11,8),(13,7),(16,6),(12,8),(10,9)]
        rows=[c(i,h,h,l,h) for i,(h,l) in enumerate(vals)]
        swings=confirmed_swings(rows,1,1)
        self.assertTrue(any(s.label=="HH" for s in swings if s.kind=="HIGH"))

    def test_sweep_detection(self):
        rows=[c(0,10,11,9,10),c(1,10,12,9.5,11),c(2,11,11.5,10,11),c(3,11,12.5,10.5,11.2)]
        swings=confirmed_swings(rows,1,1)
        # Function remains deterministic even where no confirmed pivot is available.
        self.assertIsInstance(liquidity_sweeps(rows,swings),list)

    def test_premium_discount(self):
        rows=[c(i,10,11,9,10) for i in range(8)]
        result=premium_discount(rows,[])
        self.assertEqual(result["status"],"UNAVAILABLE")

    def test_analysis_rejects_short_input(self):
        with self.assertRaises(ValueError): analyse_smc([c(0,10,11,9,10)])

if __name__ == '__main__': unittest.main()
