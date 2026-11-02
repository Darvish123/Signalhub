"""Download Bitunix historical funding settlements to CSV."""
import argparse,asyncio
from app.funding import download_funding,save_funding_csv

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--symbol",default="BTCUSDT"); p.add_argument("--start-ms",type=int,required=True)
    p.add_argument("--end-ms",type=int,required=True); p.add_argument("--out",required=True)
    p.add_argument("--base-url",default="https://fapi.bitunix.com")
    a=p.parse_args()
    rows=asyncio.run(download_funding(a.symbol,a.start_ms,a.end_ms,a.base_url))
    save_funding_csv(rows,a.out)
    print(f"Saved {len(rows)} historical funding settlements to {a.out}")
if __name__=="__main__": main()
