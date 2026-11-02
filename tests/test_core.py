import tempfile,unittest
from app.analysis import ema,atr,pivots
from app.models import Candle,Signal
from app.storage import SignalStore
def make(v): return [Candle(i*900000,x,x+1,x-1,x,1000,10) for i,x in enumerate(v)]
class CoreTests(unittest.TestCase):
 def test_ema(self): self.assertAlmostEqual(ema([1,2,3,4,5],3),4.)
 def test_atr(self): self.assertGreater(atr(make(list(range(10,30))),14),0)
 def test_invalid_candle(self): self.assertFalse(Candle(1,10,8,9,10,1,1).valid())
 def test_pivots(self):
  rows=[(11,9),(12,8),(15,7),(12,8),(11,9),(10,9),(11,8),(14,6),(11,8)]
  c=[Candle(i,h,h,l,10,1,1) for i,(h,l) in enumerate(rows)]
  hi,lo=pivots(c,1,1); self.assertIn(15,hi); self.assertIn(7,lo)
 def test_storage(self):
  with tempfile.TemporaryDirectory() as d:
   db=SignalStore(d+"/db.sqlite"); s=Signal("BTCUSDT","FUTURES","NONE","NO_TRADE",0,None,None,None,None,None,["test"],[],123)
   self.assertEqual(db.latest(1),[]); self.assertEqual(db.save(s),1); self.assertEqual(db.latest(1)[0]["symbol"],"BTCUSDT")
if __name__=="__main__": unittest.main()
