"""Run a shared-equity multi-symbol backtest from per-symbol CSV files."""
import argparse
import json
from pathlib import Path
from app.backtest import load_csv
from app.funding import load_funding_csv
from app.portfolio import run_portfolio_backtest

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--symbols", required=True,
                   help="Comma-separated symbols, e.g. BTCUSDT,ETHUSDT")
    p.add_argument("--data-dir", default="data")
    p.add_argument("--start-ms", type=int, required=True)
    p.add_argument("--end-ms", type=int, required=True)
    p.add_argument("--fee-bps", type=float, default=5.0)
    p.add_argument("--slippage-bps", type=float, default=2.0)
    p.add_argument("--risk-pct", type=float, default=0.5)
    p.add_argument("--max-leverage", type=float, default=1.0)
    p.add_argument("--initial-equity", type=float, default=100.0)
    p.add_argument("--max-positions", type=int, default=5)
    p.add_argument("--max-open-risk-pct", type=float, default=2.0)
    p.add_argument("--out", default="reports/portfolio-backtest.json")
    a = p.parse_args()
    symbols = [x.strip().upper() for x in a.symbols.split(",") if x.strip()]
    if not symbols or len(symbols) != len(set(symbols)):
        raise ValueError("Provide a non-empty list of unique symbols")
    root = Path(a.data_dir)
    candles = {s: load_csv(str(root / f"{s}_1h.csv")) for s in symbols}
    funding = {}
    for s in symbols:
        path = root / f"{s}_funding.csv"
        if not path.exists():
            raise FileNotFoundError(f"Missing funding history for {s}: {path}")
        funding[s] = load_funding_csv(str(path))
    result = run_portfolio_backtest(
        candles, funding, a.start_ms, a.end_ms, a.fee_bps, a.slippage_bps,
        a.risk_pct, a.max_leverage, a.initial_equity,
        a.max_positions, a.max_open_risk_pct,
    )
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items()
                      if k not in ("trades", "rejections", "equity_curve")}, indent=2))

if __name__ == "__main__":
    main()
