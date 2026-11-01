import unittest
from datetime import datetime, timezone
from app.models import Candle
from app.ict import analyse_ict, killzone
from app.smc import analyse_smc

class ICTTests(unittest.TestCase):
    def test_ny_killzone_uses_dst_aware_timezone(self):
        ts=int(datetime(2026,7,1,13,0,tzinfo=timezone.utc).timestamp()*1000)
        self.assertEqual(killzone(ts),"NEW_YORK_AM")

    def test_no_setup_without_full_sequence(self):
        rows=[Candle(i*3600000,100,101,99,100,1000,10) for i in range(60)]
        self.assertEqual(analyse_ict(rows)["status"],"NO_SETUP")

    def test_rejects_non_chronological_data(self):
        rows=[Candle(i*3600000,100,101,99,100,1000,10) for i in range(50)]
        rows[20]=Candle(rows[19].time_ms,100,101,99,100,1000,10)
        with self.assertRaises(ValueError):
            analyse_ict(rows)


    def test_complete_sweep_mss_fvg_retracement_sequence(self):
        rows=[Candle(i*3600000,100,101,99,100,1000,10) for i in range(40)]
        rows[5]=Candle(5*3600000,100,105,99,104,1000,10)
        rows[10]=Candle(10*3600000,100,101,95,96,1000,10)
        rows[15]=Candle(15*3600000,98,100,94,96,1000,10)
        rows[18]=Candle(18*3600000,103,110,102,109,1000,10)
        for i in list(range(19,39)):
            rows[i]=Candle(i*3600000,100,100.5,99,100,1000,10)
        rows[39]=Candle(39*3600000,103,104,100.5,102.5,1000,10)
        smc=analyse_smc(rows)
        self.assertTrue(any(x["direction"]=="BULLISH" and x["index"]==15 for x in smc["liquidity_sweeps"]),smc["liquidity_sweeps"])
        self.assertTrue(any(x["direction"]=="BULLISH" and x["index"]==18 for x in smc["structure_events"]),smc["structure_events"])
        self.assertTrue(any(x["direction"]=="BULLISH" and x["index"]==18 for x in smc["fair_value_gaps"]),smc["fair_value_gaps"])
        result=analyse_ict(rows,direction="LONG",max_mss_to_tap=25)
        self.assertEqual(result["status"],"ICT_CONFIRMED",result)
        self.assertEqual(result["setup"]["direction"],"LONG")
        self.assertEqual(result["setup"]["sweep_index"],15)
        self.assertEqual(result["setup"]["mss_index"],18)
        self.assertEqual(result["setup"]["tap_index"],39)

    def test_invalid_direction_is_rejected(self):
        rows=[Candle(i*3600000,100,101,99,100,1000,10) for i in range(50)]
        with self.assertRaises(ValueError):
            analyse_ict(rows,direction="BUY")

if __name__=="__main__":
    unittest.main()
