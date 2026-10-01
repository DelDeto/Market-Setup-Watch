from .config import (
    DEVELOPING_MIN_SCORE,
    HTF_1H_BLOCK_DISTANCE_ATR,
    HTF_4H_BLOCK_DISTANCE_ATR,
    MAX_ATR_PCT,
    MAX_ENTRY_DISTANCE_ATR,
    MIN_ATR_PCT,
    MIN_DEVELOPING_RR,
    MIN_READY_RR,
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


def _rr_points(first_rr):
    if first_rr is None:
        return 0
    if first_rr < 0.5:
        return -20
    if first_rr < 1.0:
        return -10
    if first_rr < 1.5:
        return 3
    if first_rr < 2.0:
        return 6
    return 8


def _atr_pct(analysis_15m):
    price = analysis_15m.get("current_price")
    atr = analysis_15m.get("atr")
    if not price or not atr:
        return None
    return float(atr) / max(float(price), 1e-12) * 100.0


def _opposing_zone_distance_atr(analysis, direction, entry_mid):
    if not analysis or entry_mid is None:
        return None

    atr = analysis.get("atr")
    if not atr:
        return None

    if direction == "long":
        zone = analysis.get("nearest_supply") or {}
        edge = zone.get("lower")
        if edge is None or float(edge) <= entry_mid:
            return None
        distance = float(edge) - entry_mid
    else:
        zone = analysis.get("nearest_demand") or {}
        edge = zone.get("upper")
        if edge is None or float(edge) >= entry_mid:
            return None
        distance = entry_mid - float(edge)

    return distance / max(float(atr), 1e-9)


def _htf_location(analysis_4h, analysis_1h, direction, plan):
    entry_mid = plan.get("entry_mid") if plan.get("active") else None
    if not direction or entry_mid is None:
        return {
            "blocked": False,
            "label": "UNKNOWN",
            "one_hour_distance_atr": None,
            "four_hour_distance_atr": None,
        }

    d1 = _opposing_zone_distance_atr(
        analysis_1h,
        direction,
        float(entry_mid),
    )
    d4 = _opposing_zone_distance_atr(
        analysis_4h,
        direction,
        float(entry_mid),
    )

    blocked_1h = d1 is not None and d1 <= HTF_1H_BLOCK_DISTANCE_ATR
    blocked_4h = d4 is not None and d4 <= HTF_4H_BLOCK_DISTANCE_ATR
    blocked = blocked_1h or blocked_4h

    if blocked:
        label = "BLOCKED"
    elif d1 is not None or d4 is not None:
        label = "CLEAR"
    else:
        label = "NO_OPPOSING_ZONE"

    return {
        "blocked": blocked,
        "label": label,
        "one_hour_distance_atr": d1,
        "four_hour_distance_atr": d4,
    }


def score_setup(analysis_4h, analysis_1h, analysis_15m, alignment, plan, ticker):
    setup = analysis_15m.get("setup", {})
    direction = plan.get("direction") if plan.get("active") else None
    setup_score = int(setup.get("score", 0) or 0)

    breakdown = {}

    breakdown["setup_completeness"] = min(20, setup_score * 5)
    breakdown["confirmed"] = 10 if setup.get("confirmed") else 0
    breakdown["displacement"] = 12 if setup.get("displacement") else -8
    breakdown["structure"] = 10 if setup.get("structure") else -8
    breakdown["retest"] = 8 if setup.get("retest") else 0
    breakdown["sweep"] = 8 if setup.get("sweep") else 0
    breakdown["zone_quality"] = (
        _zone_grade_points(analysis_15m, direction)
        if direction
        else 0
    )

    alignment_label = alignment.get("label")
    if alignment_label == "ALIGNED":
        breakdown["mtf_alignment"] = 10
    elif alignment_label == "PARTIAL":
        breakdown["mtf_alignment"] = 5
    elif alignment_label == "CONFLICT":
        breakdown["mtf_alignment"] = -25
    else:
        breakdown["mtf_alignment"] = 0

    first_rr = plan.get("first_target_rr")
    breakdown["first_target_rr"] = _rr_points(first_rr)

    live_price = ticker.get("last_price") if ticker else None
    atr = analysis_15m.get("atr")
    distance_atr = _entry_distance_atr(plan, live_price, atr)

    proximity_points = 0
    if distance_atr is not None:
        if distance_atr == 0:
            proximity_points = 8
        elif distance_atr <= 0.10:
            proximity_points = 6
        elif distance_atr <= MAX_ENTRY_DISTANCE_ATR:
            proximity_points = 4
    breakdown["entry_proximity"] = proximity_points

    atr_pct = _atr_pct(analysis_15m)
    volatility_ok = (
        atr_pct is not None
        and MIN_ATR_PCT <= atr_pct <= MAX_ATR_PCT
    )
    breakdown["volatility"] = 0 if volatility_ok else -12

    htf_location = _htf_location(
        analysis_4h,
        analysis_1h,
        direction,
        plan,
    )
    breakdown["htf_location"] = -18 if htf_location["blocked"] else 0

    score = max(0, min(100, sum(breakdown.values())))

    rr_developing_ok = (
        first_rr is not None
        and first_rr >= MIN_DEVELOPING_RR
    )
    rr_ready_ok = (
        first_rr is not None
        and first_rr >= MIN_READY_RR
    )

    ready = (
        plan.get("execution_ready")
        and alignment_label != "CONFLICT"
        and volatility_ok
        and not htf_location["blocked"]
        and rr_ready_ok
        and distance_atr is not None
        and distance_atr <= MAX_ENTRY_DISTANCE_ATR
        and score >= READY_MIN_SCORE
    )

    developing = (
        score >= DEVELOPING_MIN_SCORE
        and alignment_label != "CONFLICT"
        and volatility_ok
        and not htf_location["blocked"]
        and rr_developing_ok
    )

    if ready:
        bucket = "ENTRY_READY"
    elif developing:
        bucket = "DEVELOPING"
    elif score >= WATCH_MIN_SCORE:
        bucket = "WATCHLIST"
    else:
        bucket = "IGNORE"

    filters = {
        "rr_developing_ok": rr_developing_ok,
        "rr_ready_ok": rr_ready_ok,
        "volatility_ok": volatility_ok,
        "atr_pct": atr_pct,
        "htf_location": htf_location,
    }

    return {
        "score": score,
        "bucket": bucket,
        "entry_distance_atr": distance_atr,
        "score_breakdown": breakdown,
        "filters": filters,
    }
