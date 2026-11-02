import asyncio
from app.config import settings
from app.exchange import BitunixClient
async def main():
    c=BitunixClient(settings.bitunix_futures_base_url,settings.bitunix_spot_base_url,settings.request_timeout_seconds)
    t=await c.futures_tickers(); print("futures tickers:",len(t))
    k=await c.futures_klines("BTCUSDT","15m",30); print("BTCUSDT candles:",len(k),"last open(ms):",k[-1].time_ms,"close:",k[-1].close)
if __name__=="__main__": asyncio.run(main())
