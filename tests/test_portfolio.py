import unittest
from unittest.mock import patch
from app.portfolio import run_portfolio_backtest

def trade(symbol, entry_time, exit_time, pnl=10.0):
    return {
        "symbol": symbol, "entry_time_ms": entry_time, "exit_time_ms": exit_time,
        "entry": 100.0, "stop": 98.0, "position_fraction": 0.25,
        "equity_pnl_pct": pnl, "side": "LONG",
    }

class PortfolioTests(unittest.TestCase):
    def report(self, rows):
        return {"trades": rows, "funding_records_loaded": 0,
                "funding_settlements_in_test_window": 0}

    @patch("app.portfolio.run_backtest")
    def test_shared_risk_limit_rejects_excess_candidate(self, run):
        run.side_effect = [
            self.report([trade("AAAUSDT", 10, 30)]),
            self.report([trade("BBBUSDT", 11, 31)]),
        ]
        result = run_portfolio_backtest(
            {"AAAUSDT": [], "BBBUSDT": []}, {}, 0, 100,
            max_positions=5, max_open_risk_pct=0.75,
        )
        self.assertEqual(result["accepted_trades"], 1)
        self.assertEqual(result["rejected_candidates"], 1)
        self.assertEqual(result["rejections"][0]["reason"], "PORTFOLIO_OPEN_RISK_LIMIT")

    @patch("app.portfolio.run_backtest")
    def test_overlapping_trade_pnl_uses_entry_equity(self, run):
        run.side_effect = [
            self.report([trade("AAAUSDT", 10, 30)]),
            self.report([trade("BBBUSDT", 11, 30)]),
        ]
        result = run_portfolio_backtest(
            {"AAAUSDT": [], "BBBUSDT": []}, {}, 0, 100,
            max_positions=2, max_open_risk_pct=2.0,
        )
        self.assertEqual(result["accepted_trades"], 2)
        self.assertAlmostEqual(result["final_equity"], 120.0)
        self.assertEqual(result["wins"], 2)

    @patch("app.portfolio.run_backtest")
    def test_max_concurrent_positions_is_enforced(self, run):
        run.side_effect = [
            self.report([trade("AAAUSDT", 10, 30)]),
            self.report([trade("BBBUSDT", 11, 31)]),
        ]
        result = run_portfolio_backtest(
            {"AAAUSDT": [], "BBBUSDT": []}, {}, 0, 100,
            max_positions=1, max_open_risk_pct=2.0,
        )
        self.assertEqual(result["accepted_trades"], 1)
        self.assertEqual(result["rejections"][0]["reason"], "MAX_CONCURRENT_POSITIONS")

if __name__ == "__main__":
    unittest.main()
