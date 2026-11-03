"""Closed-candle 15m price-action confirmation, optionally gated by a 1H zone."""
from dataclasses import asdict, dataclass
from app.models import Candle


@dataclass(frozen=True)
class PriceActionTrigger:
    direction: str
    pattern: str
    index: int
    time_ms: int
    trigger_level: float
    invalidation: float
    body_ratio: float
    close_location: float
    score: int


def analyse_price_action(candles: list[Candle], direction: str | None = None,
                         lookback: int = 8, min_body_ratio: float = 0.45,
                         min_close_location: float = 0.65,
                         zone: dict | None = None) -> dict:
    if direction not in (None, "LONG", "SHORT"):
        raise ValueError("direction must be LONG, SHORT or None")
    if lookback < 3 or not 0 < min_body_ratio <= 1 or not 0.5 <= min_close_location <= 1:
        raise ValueError("Invalid price-action parameters")
    if len(candles) < max(lookback + 2, 6):
        return {"status": "UNAVAILABLE", "trigger": None, "reason": "Insufficient 15m candles"}
    if any(not c.valid() for c in candles) or any(
        b.time_ms <= a.time_ms for a, b in zip(candles, candles[1:])
    ):
        raise ValueError("Price-action candles must be valid and chronological")

    c, p = candles[-1], candles[-2]
    span = c.high - c.low
    if span <= 0:
        return {"status": "NO_TRIGGER", "trigger": None, "reason": "Zero-range latest candle"}
    body = abs(c.close - c.open)
    ratio = body / span
    location = (c.close - c.low) / span
    prior = candles[-lookback - 1:-1]
    prior_low = min(x.low for x in prior)
    prior_high = max(x.high for x in prior)
    prev3 = candles[-4:-1]
    bull, bear = c.close > c.open, c.close < c.open
    candidates = []

    if zone is not None:
        try:
            zlow, zhigh = float(zone["lower"]), float(zone["upper"])
            zdir = zone["direction"]
        except (KeyError, TypeError, ValueError):
            raise ValueError("15m zone must contain direction, lower and upper")
        if zlow >= zhigh or zdir not in ("LONG", "SHORT"):
            raise ValueError("Invalid 15m confirmation zone")
        if direction is not None and zdir != direction:
            return {"status": "NO_TRIGGER", "trigger": None, "reason": "15m zone direction mismatch"}
        if not (c.low <= zhigh and c.high >= zlow and zlow <= c.close <= zhigh):
            return {"status": "NO_TRIGGER", "trigger": None,
                    "reason": "Latest closed 15m candle did not close inside the refined 1H zone"}

    # Existing patterns: wick reclaim, engulfing, and three-bar micro break.
    if bull and c.low < prior_low and c.close > prior_low and location >= min_close_location:
        candidates.append(("LONG", "SWEEP_RECLAIM", prior_low, c.low, 85))
    if bear and c.high > prior_high and c.close < prior_high and location <= 1 - min_close_location:
        candidates.append(("SHORT", "SWEEP_RECLAIM", prior_high, c.high, 85))
    if bull and p.close < p.open and c.open <= p.close and c.close >= p.open and ratio >= min_body_ratio:
        candidates.append(("LONG", "BULLISH_ENGULFING", p.open, c.low, 78))
    if bear and p.close > p.open and c.open >= p.close and c.close <= p.open and ratio >= min_body_ratio:
        candidates.append(("SHORT", "BEARISH_ENGULFING", p.open, c.high, 78))
    if bull and c.close > max(x.high for x in prev3) and ratio >= min_body_ratio and location >= min_close_location:
        candidates.append(("LONG", "MICRO_BREAKOUT", max(x.high for x in prev3), c.low, 75))
    if bear and c.close < min(x.low for x in prev3) and ratio >= min_body_ratio and location <= 1 - min_close_location:
        candidates.append(("SHORT", "MICRO_BREAKDOWN", min(x.low for x in prev3), c.high, 75))

    # Added rejection patterns: hammer / shooting-star style pin bars.
    upper_wick = c.high - max(c.open, c.close)
    lower_wick = min(c.open, c.close) - c.low
    if bull and lower_wick >= max(body * 2.0, span * 0.45) and upper_wick <= max(body, span * 0.12) and location >= min_close_location:
        candidates.append(("LONG", "BULLISH_PIN_BAR", c.high, c.low, 82))
    if bear and upper_wick >= max(body * 2.0, span * 0.45) and lower_wick <= max(body, span * 0.12) and location <= 1 - min_close_location:
        candidates.append(("SHORT", "BEARISH_PIN_BAR", c.low, c.high, 82))

    # Three-candle morning/evening star reversal (no gap requirement for 24/7 markets).
    if len(candles) >= 3:
        a, b = candles[-3], candles[-2]
        arange, brange = a.high - a.low, b.high - b.low
        abody = abs(a.close - a.open)
        bbody = abs(b.close - b.open)
        if arange > 0 and brange > 0:
            if a.close < a.open and abody / arange >= min_body_ratio and bbody / brange <= 0.30 and bull and ratio >= min_body_ratio and c.close > (a.open + a.close) / 2:
                candidates.append(("LONG", "MORNING_STAR", (a.open + a.close) / 2, min(a.low, b.low, c.low), 84))
            if a.close > a.open and abody / arange >= min_body_ratio and bbody / brange <= 0.30 and bear and ratio >= min_body_ratio and c.close < (a.open + a.close) / 2:
                candidates.append(("SHORT", "EVENING_STAR", (a.open + a.close) / 2, max(a.high, b.high, c.high), 84))

    # Inside-bar breakout: previous bar is contained by the mother candle.
    if len(candles) >= 3:
        mother, inside = candles[-3], candles[-2]
        is_inside = inside.high <= mother.high and inside.low >= mother.low
        if is_inside and bull and c.close > mother.high and ratio >= min_body_ratio and location >= min_close_location:
            candidates.append(("LONG", "INSIDE_BAR_BREAKOUT", mother.high, c.low, 80))
        if is_inside and bear and c.close < mother.low and ratio >= min_body_ratio and location <= 1 - min_close_location:
            candidates.append(("SHORT", "INSIDE_BAR_BREAKDOWN", mother.low, c.high, 80))

    candidates = [x for x in candidates if direction is None or x[0] == direction]
    if not candidates:
        return {"status": "NO_TRIGGER", "trigger": None,
                "reason": "No aligned 15m price-action pattern confirmed inside the refined 1H zone" if zone else
                          "No aligned 15m price-action pattern"}
    side, pattern, level, invalidation, score = max(candidates, key=lambda x: x[4])
    result = PriceActionTrigger(side, pattern, len(candles) - 1, c.time_ms, level,
                                invalidation, round(ratio, 4), round(location, 4), score)
    return {
        "status": "TRIGGER_CONFIRMED",
        "trigger": asdict(result),
        "methodology": "closed_15m_zone_gated_pa_v2",
        "caveats": [
            "OHLC patterns are heuristic candle classifications, not proof of order flow.",
            "The caller must exclude the forming candle.",
            "When a zone is supplied, the latest candle must close inside that 1H-refined zone.",
        ],
    }
