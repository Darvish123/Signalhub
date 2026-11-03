"""Causal 4H supply/demand discovery and 1H zone refinement.

Zones are OHLC-derived hypotheses, not verified resting orders or institutional intent.
"""
from __future__ import annotations

from app.models import Candle
from app.smc import analyse_smc
from app.analysis import atr


def _overlap(a_low: float, a_high: float, b_low: float, b_high: float) -> bool:
    return a_low <= b_high and a_high >= b_low


def build_zone_context(
    h4_candles: list[Candle],
    h1_candles: list[Candle],
    direction: str,
    max_distance_atr: float = 4.0,
    liquidity_distance_atr: float = 2.0,
    lookback: int = 160,
    h4_analysis: dict | None = None,
) -> dict:
    """Find a nearby 4H OB, refine it with 1H OB/FVG, and audit nearby liquidity.

    A zone is CONFIRMED only when 1H confluence and nearby liquidity evidence exist.
    Otherwise the function fails closed and returns NO_ZONE with diagnostic context.
    """
    if direction not in ("LONG", "SHORT"):
        raise ValueError("direction must be LONG or SHORT")
    if max_distance_atr <= 0 or liquidity_distance_atr <= 0 or lookback < 20:
        raise ValueError("Invalid zone configuration")
    for name, rows in (("4H", h4_candles), ("1H", h1_candles)):
        if len(rows) < 30:
            return {"status": "UNAVAILABLE", "zone": None, "reason": f"Insufficient {name} candles"}
        if any(not c.valid() for c in rows) or any(b.time_ms <= a.time_ms for a, b in zip(rows, rows[1:])):
            raise ValueError(f"{name} zone candles must be valid and chronological")

    side = "BULLISH" if direction == "LONG" else "BEARISH"
    h4 = h4_candles[-lookback:]
    h1 = h1_candles[-lookback:]
    h4_smc = h4_analysis if h4_analysis is not None else analyse_smc(h4)
    h1_smc = analyse_smc(h1)
    h4_atr = atr(h4, 14)
    h1_atr = atr(h1, 14)
    if h4_atr <= 0 or h1_atr <= 0:
        return {"status": "UNAVAILABLE", "zone": None, "reason": "ATR unavailable"}

    price = h1[-1].close
    candidates = []
    for ob in h4_smc["order_blocks"]:
        if ob["direction"] != side or ob["mitigation"] == "INVALIDATED":
            continue
        lo, hi = float(ob["lower"]), float(ob["upper"])
        distance = max(lo - price, price - hi, 0.0)
        if distance > max_distance_atr * h4_atr:
            continue
        candidates.append((ob, lo, hi, distance / h4_atr))
    candidates.sort(key=lambda x: (x[0]["index"], -x[3]), reverse=True)

    if not candidates:
        return {"status": "NO_ZONE", "zone": None,
                "reason": "No nearby, non-invalidated 4H order-block zone in the 1D direction",
                "price": price}

    for h4_ob, zlow, zhigh, distance_atr in candidates:
        refinements = []
        for ob in h1_smc["order_blocks"]:
            if ob["direction"] == side and ob["mitigation"] != "INVALIDATED" and _overlap(
                zlow, zhigh, float(ob["lower"]), float(ob["upper"])
            ):
                refinements.append(("1H_ORDER_BLOCK", max(zlow, float(ob["lower"])),
                                    min(zhigh, float(ob["upper"])), ob["index"]))
        for gap in h1_smc["fair_value_gaps"]:
            if gap["direction"] == side and _overlap(
                zlow, zhigh, float(gap["lower"]), float(gap["upper"])
            ):
                refinements.append(("1H_FVG", max(zlow, float(gap["lower"])),
                                    min(zhigh, float(gap["upper"])), gap["index"]))
        if not refinements:
            continue
        refinements.sort(key=lambda x: (x[3], x[0] == "1H_ORDER_BLOCK"), reverse=True)
        method, refined_low, refined_high, refinement_index = refinements[0]
        if refined_low >= refined_high:
            continue

        # Liquidity is considered nearby when an equal-high/low pool or a recent
        # directionally aligned sweep is within the configured ATR distance.
        pool_kind = "SSL" if direction == "LONG" else "BSL"
        liquidity = []
        for pool in h1_smc["liquidity_pools"]:
            if pool["kind"] != pool_kind:
                continue
            level = float(pool["level"])
            distance = max(refined_low - level, level - refined_high, 0.0)
            if distance <= liquidity_distance_atr * h1_atr:
                liquidity.append({"type": "EQUAL_LEVEL_POOL", "kind": pool_kind,
                                  "level": level, "status": pool["status"],
                                  "distance_atr": round(distance / h1_atr, 3)})
        for sweep in h1_smc["liquidity_sweeps"][-12:]:
            if sweep["direction"] != side:
                continue
            level = float(sweep["wick_extreme"])
            distance = max(refined_low - level, level - refined_high, 0.0)
            if distance <= liquidity_distance_atr * h1_atr:
                liquidity.append({"type": "RECENT_SWEEP", "kind": pool_kind,
                                  "level": level, "status": "SWEPT",
                                  "distance_atr": round(distance / h1_atr, 3)})
        if not liquidity:
            continue

        invalidation = refined_low if direction == "LONG" else refined_high
        return {
            "status": "CONFIRMED",
            "h1_swings": h1_smc["swings"],
            "zone": {
                "direction": direction,
                "lower": refined_low,
                "upper": refined_high,
                "invalidation": invalidation,
                "source_4h": "ORDER_BLOCK",
                "source_4h_index": h4_ob["index"],
                "refined_by": method,
                "refinement_1h_index": refinement_index,
                "distance_atr_4h": round(distance_atr, 3),
                "liquidity_nearby": True,
                "liquidity_evidence": liquidity,
                "as_of_ms": h1[-1].time_ms,
            },
            "methodology": "4h_ob_to_1h_confluence_and_liquidity_v1",
            "caveats": [
                "OHLC-derived zones and equal-level pools are heuristic candidates, not observed resting orders.",
                "The 1H refinement is the intersection with the selected overlapping OB/FVG.",
                "Only closed candles should be supplied; the caller is responsible for candle closure validation.",
            ],
        }

    return {"status": "NO_ZONE", "zone": None,
            "reason": "4H zones found, but none had both 1H refinement and nearby aligned liquidity",
            "price": price}
