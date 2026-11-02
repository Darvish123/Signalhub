import unittest
from app.models import Signal
from app.risk import evaluate_signal_risk

def candidate(side="LONG", entry=100.0, stop=98.0):
    return Signal("BTCUSDT","FUTURES",side,"CANDIDATE",90,entry,stop,107.0,110.0,3.0,[],[],1)

class RiskEngineTests(unittest.TestCase):
    def test_position_sizing_includes_round_trip_cost(self):
        p=evaluate_signal_risk(candidate(),1000,.5,1.0,0,14)
        self.assertTrue(p.allowed)
        self.assertLessEqual(p.estimated_total_loss_quote,5.0+1e-8)
        self.assertGreater(p.quantity,0)
        self.assertLessEqual(p.gross_leverage,1.0)
    def test_short_stop_must_be_above_entry(self):
        self.assertTrue(evaluate_signal_risk(candidate("SHORT",100,102),1000,.5,1).allowed)
        self.assertFalse(evaluate_signal_risk(candidate("SHORT",100,98),1000,.5,1).allowed)
    def test_zero_stop_distance_fails_closed(self):
        self.assertFalse(evaluate_signal_risk(candidate("LONG",100,100),1000,.5,1).allowed)
    def test_max_notional_cap_applies(self):
        p=evaluate_signal_risk(candidate(),1000,.5,3,25,14)
        self.assertTrue(p.allowed)
        self.assertLessEqual(p.notional_quote,25)
    def test_non_candidate_is_rejected(self):
        s=candidate(); s.status="NO_TRADE"
        self.assertFalse(evaluate_signal_risk(s).allowed)
    def test_invalid_configuration_raises(self):
        with self.assertRaises(ValueError): evaluate_signal_risk(candidate(),1000,0,1)

if __name__=="__main__": unittest.main()
