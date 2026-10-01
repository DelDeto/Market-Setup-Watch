from .config import (
    DEVELOPING_MIN_SCORE,
    MAX_ENTRY_DISTANCE_ATR,
    READY_MIN_SCORE,
    WATCH_MIN_SCORE,
)


def _zone_grade_points(analysis_15m, direction):
    zone = (
        analysis_15m.get("nearest_demand")
        if direction == "long"
        else analysis_15m.get("nearest_supply")
    ) or {}

    return {
        "A+": 20,
        "A": 17,
        "B": 12,
        "C": 5,
    }.get(zone.get("grade"), 0)


def _entry_distance_atr(plan, live_price, atr):
    if not plan.get("active") or live_price is None or not atr:
        return None

    entry = plan.get("entry_zone", {})
    lower = entry.get("lower")
    upper = entry.get("upper")
    if lower is None or upper is None:
        return None

    if lower <= live_price <= upper:
        return 0.0

    distance = min(abs(live_price - lower), abs(live_price - upper))
    return distance / max(float(atr), 1e-9)


def score_setup(analysis_4h, analysis_1h, analysis_15m, alignment, plan, ticker):
    setup = analysis_15m.get("setup", {})
    direction = plan.get("direction") if plan.get("active") else None
    setup_score = int(setup.get("score", 0) or 0)

    score = 0
    score += min(20, setup_score * 5)

    if setup.get("confirmed"):
        score += 10
    if setup.get("displacement"):
        score += 12
    if setup.get("structure"):
        score += 10
    if setup.get("retest"):
        score += 8
    if setup.get("sweep"):
        score += 8

    if direction:
        score += _zone_grade_points(analysis_15m, direction)

    alignment_label = alignment.get("label")
    if alignment_label == "ALIGNED":
        score += 10
    elif alignment_label == "PARTIAL":
        score += 5
    elif alignment_label == "CONFLICT":
        score -= 15

    first_rr = plan.get("first_target_rr")
    if first_rr is not None:
        if first_rr >= 2.0:
            score += 8
        elif first_rr >= 1.5:
            score += 6
        elif first_rr >= 1.0:
            score += 3

    live_price = ticker.get("last_price") if ticker else None
    atr = analysis_15m.get("atr")
    distance_atr = _entry_distance_atr(plan, live_price, atr)

    if distance_atr is not None:
        if distance_atr == 0:
            score += 8
        elif distance_atr <= 0.10:
            score += 6
        elif distance_atr <= MAX_ENTRY_DISTANCE_ATR:
            score += 4

    score = max(0, min(100, score))

    if (
        plan.get("execution_ready")
        and alignment_label != "CONFLICT"
        and distance_atr is not None
        and distance_atr <= MAX_ENTRY_DISTANCE_ATR
        and score >= READY_MIN_SCORE
    ):
        bucket = "ENTRY_READY"
    elif score >= DEVELOPING_MIN_SCORE and alignment_label != "CONFLICT":
        bucket = "DEVELOPING"
    elif score >= WATCH_MIN_SCORE:
        bucket = "WATCHLIST"
    else:
        bucket = "IGNORE"

    return {
        "score": score,
        "bucket": bucket,
        "entry_distance_atr": distance_atr,
    }
