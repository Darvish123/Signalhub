import unittest
from unittest.mock import AsyncMock

from app.exchange import OKXClient, InvalidMarketDataError


class OKXClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_maps_linear_swap_and_returns_only_confirmed_sorted_bars(self):
        client = OKXClient()
        client._get = AsyncMock(return_value=[
            ["2000", "100", "102", "99", "101", "5", "0.05", "5.05", "1"],
            ["1000", "99", "101", "98", "100", "6", "0.06", "6.00", "1"],
            ["3000", "102", "103", "101", "102.5", "4", "0.04", "4.10", "0"],
        ])
        rows = await client.futures_klines("BTCUSDT", "1h", limit=10)
        self.assertEqual([x.time_ms for x in rows], [1000, 2000])
        self.assertEqual(rows[0].quote_volume, 6.0)
        client._get.assert_awaited_once_with({
            "instId": "BTC-USDT-SWAP", "bar": "1H", "limit": "10"
        })

    async def test_invalid_ohlc_fails_closed(self):
        client = OKXClient()
        client._get = AsyncMock(return_value=[
            ["1000", "100", "99", "98", "101", "1", "0.01", "1.01", "1"],
        ])
        with self.assertRaises(InvalidMarketDataError):
            await client.futures_klines("BTCUSDT", "15m")

    async def test_utc_daily_bar_mapping(self):
        client = OKXClient()
        client._get = AsyncMock(return_value=[
            ["86400000", "100", "102", "99", "101", "5", "0.05", "5.05", "1"],
        ])
        await client.futures_klines("BTCUSDT", "1d")
        self.assertEqual(client._get.await_args.args[0]["bar"], "1Dutc")


if __name__ == "__main__":
    unittest.main()
