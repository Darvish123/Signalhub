"""Authenticated, read-only Bitunix Futures REST client.

This module intentionally exposes no order placement, cancellation, transfer,
withdrawal, or account mutation methods.
"""
from __future__ import annotations

import hashlib
import secrets
import time
from typing import Any
from urllib.parse import urlencode

import httpx


class BitunixPrivateError(RuntimeError):
    """Authentication, transport, or response error from Bitunix private API."""


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_signature(
    api_key: str,
    secret_key: str,
    nonce: str,
    timestamp_ms: str,
    params: dict[str, Any] | None = None,
    body: str = "",
) -> str:
    """Build Bitunix's documented double-SHA256 REST signature."""
    query = "".join(
        f"{key}{value}"
        for key, value in sorted((params or {}).items(), key=lambda item: item[0])
        if value is not None
    )
    digest = _sha256_hex(nonce + timestamp_ms + api_key + query + body)
    return _sha256_hex(digest + secret_key)


class BitunixPrivateReadOnlyClient:
    """Small read-only client for documented Futures account endpoints."""

    def __init__(
        self,
        api_key: str,
        secret_key: str,
        base_url: str = "https://fapi.bitunix.com",
        timeout: float = 12.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_key or not secret_key:
            raise ValueError("BITUNIX_API_KEY and BITUNIX_API_SECRET are required")
        self._api_key = api_key
        self._secret_key = secret_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._transport = transport

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        clean_params = {k: v for k, v in (params or {}).items() if v is not None}
        nonce = secrets.token_hex(32)  # 64 hexadecimal characters
        timestamp = str(time.time_ns() // 1_000_000)
        headers = {
            "api-key": self._api_key,
            "nonce": nonce,
            "timestamp": timestamp,
            "sign": build_signature(
                self._api_key, self._secret_key, nonce, timestamp, clean_params
            ),
            "Content-Type": "application/json",
            "language": "en-US",
        }
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout, transport=self._transport
            ) as client:
                response = await client.get(
                    f"{self.base_url}{path}", params=clean_params, headers=headers
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            # Do not include request headers, signatures, or credentials in errors.
            raise BitunixPrivateError(
                f"Bitunix private GET failed for {path}: {type(exc).__name__}"
            ) from exc

        if not isinstance(payload, dict):
            raise BitunixPrivateError("Unexpected Bitunix response format")
        code = str(payload.get("code", "0"))
        if code not in ("0", "200"):
            # Exchange message only; never echo request headers or secrets.
            message = str(payload.get("msg", "unknown exchange error"))[:240]
            raise BitunixPrivateError(f"Bitunix rejected {path}: code={code}, msg={message}")
        return payload.get("data")

    async def get_open_positions(self, symbol: str | None = None) -> list[dict[str, Any]]:
        """Read currently open Futures positions."""
        data = await self._get(
            "/api/v1/futures/position/get_pending_positions",
            {"symbol": symbol.upper() if symbol else None},
        )
        if data is None:
            return []
        if not isinstance(data, list):
            raise BitunixPrivateError("Unexpected open-positions response shape")
        return data

    async def get_pending_orders(
        self, symbol: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Read active/pending Futures orders; this method cannot modify them."""
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        data = await self._get(
            "/api/v1/futures/trade/get_pending_orders",
            {"symbol": symbol.upper() if symbol else None, "limit": limit, "skip": 0},
        )
        if data is None:
            return []
        if not isinstance(data, dict) or not isinstance(data.get("orderList", []), list):
            raise BitunixPrivateError("Unexpected pending-orders response shape")
        return data.get("orderList", [])

    async def get_pending_tp_sl_orders(
        self, symbol: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Read pending TP/SL orders."""
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        data = await self._get(
            "/api/v1/futures/tpsl/get_pending_orders",
            {"symbol": symbol.upper() if symbol else None, "limit": limit, "skip": 0},
        )
        if data is None:
            return []
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and isinstance(data.get("orderList", []), list):
            return data.get("orderList", [])
        raise BitunixPrivateError("Unexpected pending TP/SL response shape")
