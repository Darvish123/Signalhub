import hashlib
import unittest

import httpx

from app.bitunix_private import (
    BitunixPrivateError,
    BitunixPrivateReadOnlyClient,
    build_signature,
)


class SigningTests(unittest.TestCase):
    def test_documented_double_sha256(self):
        nonce, timestamp, key, secret = "n-1", "1700000000000", "key", "secret"
        digest = hashlib.sha256((nonce + timestamp + key + "id1uid200").encode()).hexdigest()
        expected = hashlib.sha256((digest + secret).encode()).hexdigest()
        self.assertEqual(
            build_signature(key, secret, nonce, timestamp, {"uid": "200", "id": "1"}),
            expected,
        )

    def test_query_key_order_does_not_change_signature(self):
        self.assertEqual(
            build_signature("k", "s", "n", "1", {"z": "9", "a": "1"}),
            build_signature("k", "s", "n", "1", {"a": "1", "z": "9"}),
        )

    def test_credentials_required(self):
        with self.assertRaises(ValueError):
            BitunixPrivateReadOnlyClient("", "secret")
        with self.assertRaises(ValueError):
            BitunixPrivateReadOnlyClient("key", "   ")

    def test_positive_timeout_required(self):
        with self.assertRaises(ValueError):
            BitunixPrivateReadOnlyClient("key", "secret", timeout=0)


class ReadOnlyClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_positions_signed_request_and_nonce_length(self):
        seen = {}

        def handler(request):
            seen["request"] = request
            return httpx.Response(200, json={"code": 0, "data": [{"symbol": "BTCUSDT"}]})

        client = BitunixPrivateReadOnlyClient(
            "key", "secret", transport=httpx.MockTransport(handler)
        )
        rows = await client.get_open_positions("btcusdt")
        self.assertEqual(rows[0]["symbol"], "BTCUSDT")
        for header in ("api-key", "nonce", "timestamp", "sign"):
            self.assertTrue(seen["request"].headers.get(header))
        self.assertLess(len(seen["request"].headers["nonce"]), 64)
        self.assertEqual(seen["request"].url.params["symbol"], "BTCUSDT")

    async def test_pending_orders(self):
        def handler(request):
            return httpx.Response(
                200, json={"code": "0", "data": {"orderList": [{"orderId": "1"}]}}
            )

        client = BitunixPrivateReadOnlyClient(
            "key", "secret", transport=httpx.MockTransport(handler)
        )
        self.assertEqual(await client.get_pending_orders(), [{"orderId": "1"}])

    async def test_pending_tp_sl_orders(self):
        def handler(request):
            return httpx.Response(
                200, json={"code": 0, "data": [{"id": "tp-sl-1", "symbol": "BTCUSDT"}]}
            )

        client = BitunixPrivateReadOnlyClient(
            "key", "secret", transport=httpx.MockTransport(handler)
        )
        self.assertEqual(
            await client.get_pending_tp_sl_orders(),
            [{"id": "tp-sl-1", "symbol": "BTCUSDT"}],
        )

    async def test_api_rejection(self):
        def handler(request):
            return httpx.Response(200, json={"code": 10007, "msg": "invalid signature"})

        client = BitunixPrivateReadOnlyClient(
            "key", "secret", transport=httpx.MockTransport(handler)
        )
        with self.assertRaises(BitunixPrivateError):
            await client.get_open_positions()

    async def test_http_failure_is_sanitized(self):
        def handler(request):
            return httpx.Response(403, text="forbidden")

        client = BitunixPrivateReadOnlyClient(
            "key", "secret", transport=httpx.MockTransport(handler)
        )
        with self.assertRaisesRegex(BitunixPrivateError, "HTTPStatusError"):
            await client.get_open_positions()

    async def test_limit_validation(self):
        client = BitunixPrivateReadOnlyClient("key", "secret")
        with self.assertRaises(ValueError):
            await client.get_pending_orders(limit=101)
        with self.assertRaises(ValueError):
            await client.get_pending_tp_sl_orders(limit=0)


if __name__ == "__main__":
    unittest.main()
