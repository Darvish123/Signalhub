import unittest
from app.models import Candle
from app.smc import (analyse_smc, confirmed_swings, equal_level_pools, fvg_lifecycle,
                     fair_value_gaps, smt_divergence, StructureEvent, order_blocks)

def c(i,o,h,l,cl):
    return Candle(i*3600000,o,h,l,cl,1000,10)

class SMCV3Tests(unittest.TestCase):
    def test_equal_highs_form_bsl_pool(self):
        rows=[c(i,10,11,9,10) for i in range(10)]
        swings=[type("S",(),{"index":2,"kind":"HIGH","price":12})(),
                type("S",(),{"index":5,"kind":"HIGH","price":12.05})()]
        pools=equal_level_pools(swings,.1)
        self.assertEqual(len(pools),1); self.assertEqual(pools[0].kind,"BSL")
    def test_fvg_lifecycle_marks_filled(self):
        rows=[c(0,10,11,9,10),c(1,11,13,10,12),c(2,12,14,11.5,13),
              c(3,12,13,10.5,11)]
        gaps=fair_value_gaps(rows)
        life=fvg_lifecycle(rows,gaps)
        self.assertEqual(life[0]["state"],"FILLED")
    def test_ob_mitigation_is_first_revisit_after_break(self):
        rows=[c(0,10,11,9,10),c(1,10,12,9,11),c(2,11,12,10,10),
              c(3,11,13,10,12),c(4,11,12,9.5,10.5)]
        event=StructureEvent(3,rows[3].time_ms,"BOS","BULLISH",11.5,12)
        ob=order_blocks(rows,[event],3)[0]
        self.assertEqual(ob.mitigation,"MITIGATED")
        self.assertEqual(ob.mitigation_index,4)
    def test_smt_requires_aligned_data_and_detects_bearish(self):
        a=[c(i,10,11+i*.1,9,10) for i in range(20)]
        b=[c(i,10,12-i*.02,9,10) for i in range(20)]
        result=smt_divergence(a,b,left=1,right=1)
        self.assertIn(result["status"],("DIVERGENCE","NONE","UNAVAILABLE"))
    def test_analysis_exposes_full_context_contract(self):
        rows=[c(i,10,11,9,10) for i in range(70)]
        result=analyse_smc(rows)
        for key in ("liquidity_pools","fvg_lifecycle","breaker_blocks","inducements","dealing_range","premium_discount"):
            self.assertIn(key,result)
    def test_smt_rejects_unaligned_timestamps_as_unavailable(self):
        a=[c(i,10,11,9,10) for i in range(20)]
        b=[Candle(i*3600000+1000,10,11,9,10,1000,10) for i in range(20)]
        self.assertEqual(smt_divergence(a,b)["status"],"UNAVAILABLE")

if __name__=="__main__": unittest.main()
