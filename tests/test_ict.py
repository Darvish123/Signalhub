import unittest
from datetime import datetime, timezone
from app.models import Candle
from app.ict import analyse_ict, killzone

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

    def test_invalid_direction_is_rejected(self):
        rows=[Candle(i*3600000,100,101,99,100,1000,10) for i in range(50)]
        with self.assertRaises(ValueError):
            analyse_ict(rows,direction="BUY")

if __name__=="__main__":
    unittest.main()
