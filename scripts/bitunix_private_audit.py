"""Run a local read-only Bitunix Futures account connectivity audit.

Set BITUNIX_API_KEY and BITUNIX_API_SECRET in the process environment or .env.
Only status and record counts are printed; no account details are displayed.
"""
import asyncio
import os
from app.bitunix_private import BitunixPrivateReadOnlyClient

async def main():
    client = BitunixPrivateReadOnlyClient(
        api_key=os.environ.get("BITUNIX_API_KEY", ""),
        secret_key=os.environ.get("BITUNIX_API_SECRET", ""),
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
