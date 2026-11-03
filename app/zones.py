"""Causal 4H supply/demand discovery and 1H liquidity-led zone refinement.

All proximity decisions are structural. ATR is deliberately not used to decide
whether a 4H zone or 1H liquidity model is nearby.
"""
from __future__ import annotations

from app.models import Candle
from app.smc import analyse_smc


def _overlap(a_low: float, a_high: float, b_low: float, b_high: float) -> bool:
    return a_low <= b_high and a_high >= b_low


def build_zone_context(
    h4_candles: list[Candle],
    h1_candles: list[Candle],
    direction: str,
    lookback: int = 160,
    h4_analysis: dict | None = None,
) -> dict:
    """Select the nearest structurally accessible 4H OB and refine it on 1H.

    A 1H refinement must overlap the parent 4H OB. Liquidity confirmation is
    structural too: an aligned equal-high/low pool or recent aligned sweep
    must be located inside the parent 4H zone. No ATR or fixed-price distance
    threshold is used.
    """
    if direction not in ("LONG", "SHORT"):
        raise ValueError("direction must be LONG or SHORT")
    if lookback < 20:
        raise ValueError("Invalid zone lookback")
    for name, rows in (("4H", h4_candles), ("1H", h1_candles)):
        if len(rows) < 30:
            return {"status": "UNAVAILABLE", "zone": None,
                    "reason": f"Insufficient {name} candles"}
        if any(not c.valid() for c in rows) or any(
            b.time_ms <= a.time_ms for a, b in zip(rows, rows[1:])
        ):
            raise ValueError(f"{name} zone candles must be valid and chronological")

    side = "BULLISH" if direction == "LONG" else "BEARISH"
    h4 = h4_candles[-lookback:]
    h1 = h1_candles[-lookback:]
    h4_smc = h4_analysis if h4_analysis is not None else analyse_smc(h4)
    h1_smc = analyse_smc(h1)
    price = h1[-1].close

    # Demand zones for LONG must be at/below current price; supply zones for
    # SHORT must be at/above it. If several qualify, choose the nearest one,
    # then prefer the most recently formed zone at equal distance.
    candidates = []
    for ob in h4_smc.get("order_blocks", []):
        if ob["direction"] != side or ob["mitigation"] == "INVALIDATED":
            continue
        lo, hi = float(ob["lower"]), float(ob["upper"])
        if lo >= hi:
            continue
        if direction == "LONG" and lo > price:
            continue
        if direction == "SHORT" and hi < price:
            continue
        distance = max(lo - price, price - hi, 0.0)
        candidates.append((distance, -int(ob["index"]), ob, lo, hi))

    candidates.sort(key=lambda x: (x[0], x[1]))
    if not candidates:
        return {
            "status": "NO_ZONE", "zone": None,
            "reason": "No directionally accessible, non-invalidated 4H order-block zone",
            "price": price,
        }

    for distance, _, h4_ob, zlow, zhigh in candidates:
        refinements = []
        for ob in h1_smc.get("order_blocks", []):
            if ob["direction"] == side and ob["mitigation"] != "INVALIDATED" and _overlap(
                zlow, zhigh, float(ob["lower"]), float(ob["upper"])
            ):
                refinements.append((
                    "1H_ORDER_BLOCK",
                    max(zlow, float(ob["lower"])),
                    min(zhigh, float(ob["upper"])),
                    int(ob["index"]),
                ))

        fvg_states = {
            row["index"]: row["state"]
            for row in h1_smc.get("fvg_lifecycle", [])
        }
        for gap in h1_smc.get("fair_value_gaps", []):
            lifecycle = fvg_states.get(gap["index"], "UNMITIGATED")
            if lifecycle in ("INVALIDATED", "FILLED"):
                continue
            if gap["direction"] == side and _overlap(
                zlow, zhigh, float(gap["lower"]), float(gap["upper"])
            ):
                refinements.append((
                    "1H_FVG",
                    max(zlow, float(gap["lower"])),
                    min(zhigh, float(gap["upper"])),
                    int(gap["index"]),
                ))

        if not refinements:
            continue
        refinements.sort(
            key=lambda x: (x[3], x[0] == "1H_ORDER_BLOCK"), reverse=True
        )

        # Liquidity is associated with the 4H parent zone by price structure,
        # not by an ATR-derived radius. A pool/swept level outside that zone
        # cannot qualify this 4H candidate.
        pool_kind = "SSL" if direction == "LONG" else "BSL"
        liquidity = []
        for pool in h1_smc.get("liquidity_pools", []):
            if pool["kind"] != pool_kind or pool["status"] != "RESTING":
                continue
            level = float(pool["level"])
            if zlow <= level <= zhigh:
                liquidity.append({
                    "type": "EQUAL_LEVEL_POOL",
                    "kind": pool_kind,
                    "level": level,
                    "status": pool["status"],
                    "location": "INSIDE_4H_PARENT_ZONE",
                })

        for sweep in h1_smc.get("liquidity_sweeps", [])[-12:]:
            if sweep["index"] < len(h1) - 12 or sweep["direction"] != side:
                continue
            # swept_level is the prior confirmed swing level; wick_extreme is
            # the excursion beyond it. The former anchors the structural model.
            level = float(sweep.get("swept_level", sweep.get("wick_extreme")))
            if zlow <= level <= zhigh:
                liquidity.append({
                    "type": "RECENT_SWEEP",
                    "kind": pool_kind,
                    "level": level,
                    "wick_extreme": float(sweep["wick_extreme"]),
                    "status": "SWEPT",
                    "location": "INSIDE_4H_PARENT_ZONE",
                })

        if not liquidity:
            continue

        method, refined_low, refined_high, refinement_index = refinements[0]
        if refined_low >= refined_high:
            continue
        invalidation = refined_low if direction == "LONG" else refined_high
        return {
            "status": "CONFIRMED",
            "h1_swings": h1_smc.get("swings", []),
            "zone": {
                "direction": direction,
                "lower": refined_low,
                "upper": refined_high,
                "invalidation": invalidation,
                "source_4h": "ORDER_BLOCK",
                "source_4h_index": h4_ob["index"],
                "source_4h_bounds": {"lower": zlow, "upper": zhigh},
                "refined_by": method,
                "refinement_1h_index": refinement_index,
                "distance_price": round(distance, 10),
                "liquidity_nearby": True,
                "liquidity_evidence": liquidity,
                "liquidity_rule": "aligned 1H pool/sweep level inside parent 4H zone",
                "as_of_ms": h1[-1].time_ms,
            },
            "methodology": "4h_ob_to_1h_overlap_and_structural_liquidity_v2",
            "caveats": [
                "OHLC-derived zones and equal-level pools are heuristic candidates, not observed resting orders.",
                "The 1H refinement is the intersection with the selected overlapping OB/FVG.",
                "Liquidity proximity is structural: its aligned level must lie inside the parent 4H zone; no ATR radius is used.",
                "Only closed candles should be supplied; the caller is responsible for candle closure validation.",
            ],
        }

    return {
        "status": "NO_ZONE", "zone": None,
        "reason": "No accessible 4H zone had both an overlapping 1H refinement and aligned liquidity inside the parent zone",
        "price": price,
    }
