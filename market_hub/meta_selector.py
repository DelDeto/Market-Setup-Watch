from .config import (
    A_BASE_RISK_PCT,
    A_PLUS_BASE_RISK_PCT,
    A_PLUS_SELECTOR_SCORE,
    FULL_SIZE_MIN_STOP_PCT,
    MAX_NOTIONAL_EQUITY_MULTIPLE,
    MAX_TOTAL_TOP_PICK_RISK_PCT,
    REDUCED_SIZE_MIN_STOP_PCT,
    RUNNER_FRACTION,
    RUNNER_MAX_R,
    RUNNER_MIN_R,
    SELECTOR_MIN_SCORE,
    SELECTOR_TARGET_R,
    TIGHT_SIZE_MIN_STOP_PCT,
    TOP_PICK_2_MAX_RISK_PCT,
    TOP_PICK_COUNT,
    TP1_CLOSE_FRACTION,
)


ACTIONABLE_BUCKETS = (
    "ENTRY_READY",
    "NEAR_ENTRY",
    "DEVELOPING",
)


def _entry_selection_score(item):
    plan = item.get("trade_plan") or {}
    entry = plan.get("entry_zone") or {}
    value = entry.get("selection_score")
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _fast_score(item, fast_by_symbol):
    row = fast_by_symbol.get(item.get("symbol")) or {}
    try:
        return float(row.get("fast_score") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _selector_score(item, fast_by_symbol):
    if item.get("bucket") not in ACTIONABLE_BUCKETS:
        return 0.0, {}

    if item.get("correlation_suppressed", False):
        return 0.0, {"blocked": "correlation_suppressed"}

    plan = item.get("trade_plan") or {}
    entry = plan.get("entry_zone") or {}
    filters = item.get("filters") or {}
    features = (item.get("analysis_15m") or {}).get("setup") or {}
    participation = filters.get("participation") or {}
    market_context = filters.get("market_context") or {}

    selection = _entry_selection_score(item)
    quality = float(item.get("quality_score") or item.get("score") or 0.0)
    adaptive_points = float(
        (item.get("score_breakdown") or {}).get("adaptive") or 0.0
    )
    quality = max(0.0, min(100.0, quality - adaptive_points))
    execution = float(item.get("execution_score") or 0.0)
    fast = _fast_score(item, fast_by_symbol)
    distance = item.get("entry_distance_atr")
    distance = float(distance) if distance is not None else 99.0
    rr = plan.get("first_target_rr")
    rr = float(rr) if rr is not None else 0.0

    score = (
        selection * 0.40
        + execution * 0.20
        + quality * 0.15
        + fast * 0.10
    )

    # Fixed 2R target: structural room matters, but extreme headline RR is
    # deliberately capped so 10R-15R plans do not dominate the selector.
    rr_points = min(10.0, max(0.0, rr) / SELECTOR_TARGET_R * 5.0)
    score += rr_points

    if item.get("mtf_alignment") == "ALIGNED":
        score += 4.0

    part_regime = participation.get("regime")
    direction = item.get("direction")
    if (
        (direction == "long" and part_regime == "LONG_BUILD")
        or (direction == "short" and part_regime == "SHORT_BUILD")
    ):
        score += 3.0

    market_regime = market_context.get("regime")
    if (
        (direction == "long" and market_regime == "BULLISH")
        or (direction == "short" and market_regime == "BEARISH")
    ):
        score += 3.0

    if features.get("sweep"):
        score += 2.0

    # Prefer entries that are reachable but not chasey.
    if distance <= 0.35:
        score += 4.0
    elif distance <= 0.80:
        score += 2.0
    else:
        score -= 8.0

    # A 2R target needs enough structural room. Do not hard-block sub-2R
    # structural TP because some historically continued beyond that target,
    # but penalize it.
    if rr < 1.5:
        score -= 8.0
    elif rr < SELECTOR_TARGET_R:
        score -= 3.0

    breakdown = {
        "entry_selection": round(selection * 0.40, 2),
        "execution": round(execution * 0.20, 2),
        "quality": round(quality * 0.15, 2),
        "fast": round(fast * 0.10, 2),
        "rr_room": round(rr_points, 2),
        "mtf_bonus": 4.0 if item.get("mtf_alignment") == "ALIGNED" else 0.0,
        "distance_atr": round(distance, 3),
        "structural_rr": round(rr, 3),
    }
    return max(0.0, min(100.0, score)), breakdown


def _selector_target_price(item):
    plan = item.get("trade_plan") or {}
    entry = plan.get("entry_zone") or {}
    lower = entry.get("lower")
    upper = entry.get("upper")
    stop = plan.get("stop_loss")
    direction = item.get("direction")

    if lower is None or upper is None or stop is None or direction not in ("long", "short"):
        return None

    entry_mid = (float(lower) + float(upper)) / 2.0
    risk = abs(entry_mid - float(stop))
    if risk <= 0:
        return None

    if direction == "long":
        return entry_mid + SELECTOR_TARGET_R * risk
    return entry_mid - SELECTOR_TARGET_R * risk



def _stop_distance_pct(item):
    plan = item.get("trade_plan") or {}
    entry = plan.get("entry_zone") or {}
    lower = entry.get("lower")
    upper = entry.get("upper")
    stop = plan.get("stop_loss")

    if lower is None or upper is None or stop is None:
        return None

    entry_mid = (float(lower) + float(upper)) / 2.0
    if entry_mid <= 0:
        return None

    return abs(entry_mid - float(stop)) / entry_mid * 100.0


def _risk_modifier_for_stop(stop_pct):
    if stop_pct is None:
        return 0.0, "UNKNOWN_STOP"
    if stop_pct >= FULL_SIZE_MIN_STOP_PCT:
        return 1.00, "FULL"
    if stop_pct >= REDUCED_SIZE_MIN_STOP_PCT:
        return 0.85, "REDUCED"
    if stop_pct >= TIGHT_SIZE_MIN_STOP_PCT:
        return 0.65, "TIGHT"
    return 0.40, "VERY_TIGHT"


def _runner_target_r(item):
    plan = item.get("trade_plan") or {}
    structural_rr = plan.get("first_target_rr")
    try:
        structural_rr = float(structural_rr)
    except (TypeError, ValueError):
        structural_rr = RUNNER_MIN_R

    return max(
        RUNNER_MIN_R,
        min(RUNNER_MAX_R, structural_rr),
    )


def _runner_target_price(item, runner_r):
    plan = item.get("trade_plan") or {}
    entry = plan.get("entry_zone") or {}
    lower = entry.get("lower")
    upper = entry.get("upper")
    stop = plan.get("stop_loss")
    direction = item.get("direction")

    if lower is None or upper is None or stop is None:
        return None

    entry_mid = (float(lower) + float(upper)) / 2.0
    risk = abs(entry_mid - float(stop))
    if risk <= 0:
        return None

    if direction == "long":
        return entry_mid + runner_r * risk
    if direction == "short":
        return entry_mid - runner_r * risk
    return None


def _position_plan(item, rank, remaining_risk_pct):
    score = float(item.get("selector_score") or 0.0)
    bucket = item.get("bucket")
    distance = item.get("entry_distance_atr")
    distance = float(distance) if distance is not None else 99.0
    htf = ((item.get("filters") or {}).get("htf_location") or {})

    a_plus_execution = (
        item.get("mtf_alignment") == "ALIGNED"
        and not htf.get("blocked", False)
        and (
            bucket == "ENTRY_READY"
            or (bucket == "NEAR_ENTRY" and distance <= 0.20)
        )
    )

    if score >= A_PLUS_SELECTOR_SCORE and a_plus_execution:
        grade = "A+"
        base_risk_pct = A_PLUS_BASE_RISK_PCT
    else:
        grade = "A"
        base_risk_pct = A_BASE_RISK_PCT

    if rank == 2:
        base_risk_pct = min(base_risk_pct, TOP_PICK_2_MAX_RISK_PCT)

    stop_pct = _stop_distance_pct(item)
    stop_modifier, stop_size_label = _risk_modifier_for_stop(stop_pct)
    suggested_risk_pct = base_risk_pct * stop_modifier
    suggested_risk_pct = min(suggested_risk_pct, remaining_risk_pct)

    if stop_pct is None or stop_pct <= 0:
        notional_multiple = 0.0
        effective_risk_pct = 0.0
    else:
        raw_notional_multiple = suggested_risk_pct / stop_pct
        notional_multiple = min(
            raw_notional_multiple,
            MAX_NOTIONAL_EQUITY_MULTIPLE,
        )
        effective_risk_pct = notional_multiple * stop_pct

    runner_r = _runner_target_r(item)
    tp1_locked_r = TP1_CLOSE_FRACTION * SELECTOR_TARGET_R
    full_target_r = (
        TP1_CLOSE_FRACTION * SELECTOR_TARGET_R
        + RUNNER_FRACTION * runner_r
    )

    return {
        "grade": grade,
        "base_risk_pct": round(base_risk_pct, 3),
        "stop_distance_pct": (
            round(stop_pct, 4) if stop_pct is not None else None
        ),
        "stop_size_label": stop_size_label,
        "stop_risk_modifier": round(stop_modifier, 2),
        "recommended_risk_pct": round(effective_risk_pct, 3),
        "notional_equity_multiple": round(notional_multiple, 3),
        "max_notional_equity_multiple": MAX_NOTIONAL_EQUITY_MULTIPLE,
        "tp1_r": SELECTOR_TARGET_R,
        "tp1_close_fraction": TP1_CLOSE_FRACTION,
        "runner_fraction": RUNNER_FRACTION,
        "runner_target_r": round(runner_r, 2),
        "runner_target_price": _runner_target_price(item, runner_r),
        "profit_if_runner_be_pct": round(
            effective_risk_pct * tp1_locked_r,
            3,
        ),
        "profit_if_runner_target_pct": round(
            effective_risk_pct * full_target_r,
            3,
        ),
        "management": (
            "At +1R move stop to breakeven; at +2R close 80%; "
            "trail the remaining 20% toward 3R-4R / structural liquidity."
        ),
    }

def apply_top_pick_selector(results, fast_rows):
    fast_by_symbol = {row.get("symbol"): row for row in fast_rows}
    candidates = []

    for item in results:
        score, breakdown = _selector_score(item, fast_by_symbol)
        item["selector_score"] = round(score, 2)
        item["selector_breakdown"] = breakdown
        item["selector_target_r"] = SELECTOR_TARGET_R
        item["selector_tp1"] = _selector_target_price(item)
        item["top_pick_rank"] = None

        if (
            item.get("bucket") in ACTIONABLE_BUCKETS
            and not item.get("correlation_suppressed", False)
            and score >= SELECTOR_MIN_SCORE
            and item.get("selector_tp1") is not None
        ):
            candidates.append(item)

    candidates.sort(
        key=lambda item: (
            -float(item.get("selector_score") or 0.0),
            -float(
                ((item.get("trade_plan") or {}).get("entry_zone") or {})
                .get("selection_score")
                or 0.0
            ),
            -float(item.get("execution_score") or 0.0),
        )
    )

    selected = candidates[:TOP_PICK_COUNT]
    remaining_risk_pct = MAX_TOTAL_TOP_PICK_RISK_PCT

    for rank, item in enumerate(selected, start=1):
        item["top_pick_rank"] = rank
        position_plan = _position_plan(
            item,
            rank,
            remaining_risk_pct,
        )
        item["position_plan"] = position_plan
        remaining_risk_pct = max(
            0.0,
            remaining_risk_pct
            - float(position_plan.get("recommended_risk_pct") or 0.0),
        )

    return selected
