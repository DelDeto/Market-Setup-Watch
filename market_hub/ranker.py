from .calibration import adaptive_points
from .market_context import market_context_points

from .config import (
    DEVELOPING_MIN_EXECUTION_SCORE,
    DEVELOPING_MIN_SCORE,
    HTF_1H_BLOCK_DISTANCE_ATR,
    HTF_4H_BLOCK_DISTANCE_ATR,
    MAX_ATR_PCT,
    MAX_DEVELOPING_ENTRY_DISTANCE_ATR,
    MAX_ENTRY_DISTANCE_ATR,
    MAX_NEAR_ENTRY_DISTANCE_ATR,
    MIN_ATR_PCT,
    MIN_DEVELOPING_RR,
    MIN_READY_RR,
    NEAR_ENTRY_MIN_EXECUTION_SCORE,
    NEAR_ENTRY_MIN_SCORE,
    READY_MIN_EXECUTION_SCORE,
    READY_MIN_SCORE,
    WATCH_MIN_SCORE,
)


def _context_zone_grade_points(analysis_15m, direction):
    zone = (
        analysis_15m.get("nearest_demand")
        if direction == "long"
        else analysis_15m.get("nearest_supply")
    ) or {}

    return {
        "A+": 18,
        "A": 15,
        "B": 10,
        "C": 2,
    }.get(zone.get("grade"), 0)


def _entry_zone_grade_points(plan):
    grade = ((plan or {}).get("entry_zone") or {}).get("zone_grade")
    return {
        "A+": 10,
        "A": 9,
        "B": 6,
        "C": -8,
    }.get(grade, 2)


def _entry_distance_atr(plan, live_price, atr):
    if not plan.get("active") or live_price is None or not atr:
        return None

    entry = plan.get("entry_zone", {})
    lower = entry.get("lower")
    upper = entry.get("upper")
    if lower is None or upper is None:
        return None

    lower = float(lower)
    upper = float(upper)
    live_price = float(live_price)

    if lower <= live_price <= upper:
        return 0.0

    distance = min(abs(live_price - lower), abs(live_price - upper))
    return distance / max(float(atr), 1e-9)


def _rr_execution_points(first_rr):
    if first_rr is None:
        return -15
    first_rr = float(first_rr)
    if first_rr < 1.0:
        return -15
    if first_rr < 1.20:
        return 4
    if first_rr < 1.50:
        return 10
    if first_rr < 2.0:
        return 16
    if first_rr < 3.0:
        return 21
    return 24


def _proximity_execution_points(distance_atr):
    if distance_atr is None:
        return 0
    if distance_atr == 0:
        return 30
    if distance_atr <= 0.10:
        return 28
    if distance_atr <= MAX_ENTRY_DISTANCE_ATR:
        return 24
    if distance_atr <= MAX_NEAR_ENTRY_DISTANCE_ATR:
        return 16
    if distance_atr <= 1.25:
        return 8
    return 0


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


def _participation_points(ticker, direction):
    context = (ticker or {}).get("participation_context") or {}
    regime = context.get("regime")

    if regime == "LONG_BUILD":
        return 4 if direction == "long" else -4
    if regime == "SHORT_BUILD":
        return 4 if direction == "short" else -4
    if regime == "DELEVERAGING":
        return -2
    return 0


def _calibration_features(setup, alignment_label, zone_grade):
    return {
        "confirmed": bool(setup.get("confirmed")),
        "displacement": bool(setup.get("displacement")),
        "structure": bool(setup.get("structure")),
        "retest": bool(setup.get("retest")),
        "sweep": bool(setup.get("sweep")),
        "mtf_aligned": alignment_label == "ALIGNED",
        "zone_a_or_better": zone_grade in ("A+", "A", "B"),
    }


def score_setup(
    analysis_4h,
    analysis_1h,
    analysis_15m,
    alignment,
    plan,
    ticker,
    market_context=None,
    calibration=None,
    symbol=None,
):
    setup = analysis_15m.get("setup", {})
    direction = plan.get("direction") if plan.get("active") else None
    setup_score = int(setup.get("score", 0) or 0)
    alignment_label = alignment.get("label")

    context_zone = (
        analysis_15m.get("nearest_demand")
        if direction == "long"
        else analysis_15m.get("nearest_supply")
    ) or {}
    context_zone_grade = context_zone.get("grade")

    # QUALITY SCORE:
    # Structural/setup quality only. We intentionally keep "confirmed" small
    # because it is derived from the same 15M sequence already represented by
    # structure/displacement/retest/sweep and should not be double-counted.
    quality_breakdown = {}
    quality_breakdown["setup_completeness"] = min(16, setup_score * 4)
    quality_breakdown["confirmed"] = 4 if setup.get("confirmed") else 0
    quality_breakdown["displacement"] = 12 if setup.get("displacement") else -12
    quality_breakdown["structure"] = 14 if setup.get("structure") else -14
    quality_breakdown["retest"] = 6 if setup.get("retest") else 0
    quality_breakdown["sweep"] = 5 if setup.get("sweep") else 0
    quality_breakdown["zone_quality"] = (
        _context_zone_grade_points(analysis_15m, direction)
        if direction
        else 0
    )

    if alignment_label == "ALIGNED":
        quality_breakdown["mtf_alignment"] = 14
    elif alignment_label == "PARTIAL":
        quality_breakdown["mtf_alignment"] = 7
    elif alignment_label == "CONFLICT":
        quality_breakdown["mtf_alignment"] = -30
    else:
        quality_breakdown["mtf_alignment"] = 0

    htf_location = _htf_location(
        analysis_4h,
        analysis_1h,
        direction,
        plan,
    )
    quality_breakdown["htf_location"] = -20 if htf_location["blocked"] else 0

    quality_breakdown["participation"] = _participation_points(
        ticker,
        direction,
    )
    quality_breakdown["market_context"] = market_context_points(
        direction,
        market_context,
        symbol=symbol,
    )

    calibration_features = _calibration_features(
        setup,
        alignment_label,
        context_zone_grade,
    )
    participation_regime = (
        ((ticker or {}).get("participation_context") or {}).get("regime")
    )
    market_regime = (market_context or {}).get("regime")
    first_rr = plan.get("first_target_rr")

    calibration_features.update({
        "rr_1_5_plus": (
            first_rr is not None and float(first_rr) >= 1.5
        ),
        "participation_aligned": (
            (direction == "long" and participation_regime == "LONG_BUILD")
            or (
                direction == "short"
                and participation_regime == "SHORT_BUILD"
            )
        ),
        "market_context_aligned": (
            (direction == "long" and market_regime == "BULLISH")
            or (direction == "short" and market_regime == "BEARISH")
        ),
    })
    quality_breakdown["adaptive"] = adaptive_points(
        calibration_features,
        calibration,
    )

    quality_score = max(0, min(100, sum(quality_breakdown.values())))

    # EXECUTION SCORE:
    # Can this otherwise-valid setup be acted on near the current price?
    live_price = ticker.get("last_price") if ticker else None
    atr = analysis_15m.get("atr")
    distance_atr = _entry_distance_atr(plan, live_price, atr)

    execution_breakdown = {}
    execution_breakdown["entry_proximity"] = _proximity_execution_points(
        distance_atr
    )
    execution_breakdown["first_target_rr"] = _rr_execution_points(first_rr)
    execution_breakdown["plan_ready"] = (
        18 if plan.get("execution_ready")
        else (5 if plan.get("active") else 0)
    )
    execution_breakdown["entry_zone"] = _entry_zone_grade_points(plan)
    execution_breakdown["structure"] = 6 if setup.get("structure") else 0
    execution_breakdown["displacement"] = 6 if setup.get("displacement") else 0
    execution_breakdown["retest"] = 3 if setup.get("retest") else 0
    execution_breakdown["sweep"] = 2 if setup.get("sweep") else 0

    execution_score = max(
        0,
        min(100, sum(execution_breakdown.values())),
    )

    atr_pct = _atr_pct(analysis_15m)
    volatility_ok = (
        atr_pct is not None
        and MIN_ATR_PCT <= atr_pct <= MAX_ATR_PCT
    )

    rr_developing_ok = (
        first_rr is not None
        and first_rr >= MIN_DEVELOPING_RR
    )
    rr_ready_ok = (
        first_rr is not None
        and first_rr >= MIN_READY_RR
    )

    blockers = list(plan.get("blockers") or [])
    hard_clear = (
        plan.get("active")
        and alignment_label != "CONFLICT"
        and volatility_ok
        and not htf_location["blocked"]
        and not plan.get("higher_tf_conflict", False)
        and bool(setup.get("structure"))
        and rr_developing_ok
        and distance_atr is not None
    )

    ready = (
        hard_clear
        and plan.get("execution_ready")
        and rr_ready_ok
        and distance_atr <= MAX_ENTRY_DISTANCE_ATR
        and quality_score >= READY_MIN_SCORE
        and execution_score >= READY_MIN_EXECUTION_SCORE
    )

    near_entry = (
        hard_clear
        and rr_ready_ok
        and distance_atr <= MAX_NEAR_ENTRY_DISTANCE_ATR
        and quality_score >= NEAR_ENTRY_MIN_SCORE
        and execution_score >= NEAR_ENTRY_MIN_EXECUTION_SCORE
        and (
            plan.get("execution_ready")
            or (
                bool(setup.get("displacement"))
                and len(blockers) <= 1
            )
        )
    )

    developing = (
        hard_clear
        and distance_atr <= MAX_DEVELOPING_ENTRY_DISTANCE_ATR
        and quality_score >= DEVELOPING_MIN_SCORE
        and execution_score >= DEVELOPING_MIN_EXECUTION_SCORE
    )

    if ready:
        bucket = "ENTRY_READY"
    elif near_entry:
        bucket = "NEAR_ENTRY"
    elif developing:
        bucket = "DEVELOPING"
    elif quality_score >= WATCH_MIN_SCORE:
        bucket = "WATCHLIST"
    else:
        bucket = "IGNORE"

    filters = {
        "rr_developing_ok": rr_developing_ok,
        "rr_ready_ok": rr_ready_ok,
        "volatility_ok": volatility_ok,
        "atr_pct": atr_pct,
        "htf_location": htf_location,
        "participation": (ticker or {}).get("participation_context"),
        "market_context": market_context or {},
        "calibration_active": bool(
            calibration and calibration.get("active")
        ),
        "hard_clear": bool(hard_clear),
        "blocker_count": len(blockers),
    }

    return {
        # score remains the setup-quality score for backwards compatibility.
        "score": quality_score,
        "quality_score": quality_score,
        "execution_score": execution_score,
        "bucket": bucket,
        "entry_distance_atr": distance_atr,
        "score_breakdown": quality_breakdown,
        "execution_breakdown": execution_breakdown,
        "filters": filters,
    }
