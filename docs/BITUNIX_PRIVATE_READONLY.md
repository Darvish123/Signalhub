# Bitunix private API — read-only integration

SignalHub has an optional authenticated Bitunix Futures client. It is deliberately
limited to GET requests for current positions, pending orders and pending TP/SL orders.
There are no order placement, amendment, cancellation, transfer or withdrawal methods.

## Security

- Create a dedicated Bitunix API key with read-only/account-query permission only.
- Disable trading and withdrawal permissions. Bind the key to a trusted fixed IP if available.
- Never paste API credentials into chat, source code, GitHub, issue comments or logs.
- Store credentials only as local environment variables or in an untracked local .env file.
- Revoke the key immediately if it is exposed.
- Exceptions do not include request headers, signatures, or credentials.

## Configure locally

Copy .env.example to .env and fill the two credential values locally. Load the file into
your shell environment, then run:

```bash
set -a
source .env
set +a
python -m unittest discover -s tests -v
python -m scripts.bitunix_private_audit
```

The audit prints only authentication status and counts of open positions, pending orders,
and pending TP/SL orders. It does not print balances or position/order details.

## Supported private read endpoints

- GET /api/v1/futures/position/get_pending_positions
- GET /api/v1/futures/trade/get_pending_orders
- GET /api/v1/futures/tpsl/get_pending_orders

The endpoints and double-SHA256 signature format follow the official Bitunix Futures
OpenAPI documentation. Account-wide wallet/balance retrieval is intentionally not included
because the exact supported Futures account-balance endpoint has not been verified against
the current official documentation. Do not infer account equity from configured paper equity.

## Important limits

A successful positions request confirms authentication and access to that endpoint only.
An empty positions/orders list is valid and does not mean authentication failed.
This integration is not a live risk manager and does not submit or manage trades.
