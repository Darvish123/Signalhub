# Bitunix connectivity check

The Futures public market-data endpoints do not require API credentials. The
project's client is configured by default for `https://fapi.bitunix.com`.

From the repository root, install dependencies and run:

```bash
pip install -r requirements.txt
python -m scripts.check_bitunix_connection
```

A successful check prints `"status": "CONNECTED"` after fetching the public
Futures ticker list and 20 BTCUSDT 15m candles, then validating candle freshness.
A failed check prints `"status": "CONNECTION_FAILED"` with the exception.

This validates public market-data reachability only. It does not authenticate
the user's Bitunix account, inspect balances or positions, or enable trading.
Private REST requests require an API key, timestamp, nonce and the documented
two-stage SHA256 signature. Do not place API secrets in source code or share
them in chat. If private account connectivity is ever required, create a
separate key with read-only permissions and IP restrictions; do not grant
trading/withdrawal permissions to this research MVP.

Official docs:
- Public vs private interfaces: https://www.bitunix.com/api-docs/
- Futures kline endpoint: https://www.bitunix.com/api-docs/futures/market/get_kline
- Signature rules: https://www.bitunix.com/api-docs/futures/common/sign.html
