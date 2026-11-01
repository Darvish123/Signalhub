import unittest
from app.funding import funding_cashflow_pct
class FundingTests(unittest.TestCase):
 def test_positive_rate_longs_pay_shorts_receive(self):
  self.assertAlmostEqual(funding_cashflow_pct("LONG",100,.5,.001,100),-.05)
  self.assertAlmostEqual(funding_cashflow_pct("SHORT",100,.5,.001,100),.05)
 def test_negative_rate_reverses_cashflow(self):
  self.assertAlmostEqual(funding_cashflow_pct("LONG",100,.5,-.001,100),.05)
if __name__=="__main__": unittest.main()
