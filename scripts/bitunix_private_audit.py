"""Run a local read-only Bitunix Futures account connectivity audit.

Credentials are read from environment variables or the local .env file.
Only status and record counts are printed; no account details are displayed.
"""
import asyncio
from app.config import settings
from app.bitunix_private import BitunixPrivateReadOnlyClient

async def main():
    client = BitunixPrivateReadOnlyClient(
        api_key=settings.bitunix_api_key,
        secret_key=settings.bitunix_api_secret,
        base_url=settings.bitunix_futures_base_url,
        timeout=settings.request_timeout_seconds,
    )
    positions, orders, tp_sl = await asyncio.gather(
        client.get_open_positions(),
        client.get_pending_orders(),
        client.get_pending_tp_sl_orders(),
    )
    print({
        "authentication": "success",
        "open_positions_count": len(positions),
        "pending_orders_count": len(orders),
        "pending_tp_sl_orders_count": len(tp_sl),
        "mode": "read_only",
        "order_execution": "not_implemented",
    })

if __name__ == "__main__":
    asyncio.run(main())
