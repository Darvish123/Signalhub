import unittest

from app.exchange import BitunixClient, InvalidMarketDataError


class FixtureBitunixClient(BitunixClient):
    def __init__(self, rows):
        super().__init__("https://fapi.bitunix.com", "https://www.bitunix.com")
        self.rows = rows

    async def _get(self, url, params=None):
        return self.rows


class RawHistoricalCandleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.invalid = {
            "time": 1_800_000_000_000,
            "open": "100.1",
            "high": "101",
            "low": "100.2",
            "close": "100.8",
            "quoteVol": "1000",
            "baseVol": "10",
        }

    async def test_default_validation_remains_strict(self):
        client = FixtureBitunixClient([self.invalid])
        with self.assertRaises(InvalidMarketDataError):
            await client.futures_klines("BTCUSDT", "1h", 1)

    async def test_raw_mode_is_explicit_and_returns_invalid_row_for_audit(self):
        client = FixtureBitunixClient([self.invalid])
        rows = await client.futures_klines(
            "BTCUSDT", "1h", 1, strict_validation=False
        )
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0].valid())


if __name__ == "__main__":
    unittest.main()
