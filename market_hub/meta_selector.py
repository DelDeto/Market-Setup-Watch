from .config import (
    SELECTOR_MIN_SCORE,
    SELECTOR_TARGET_R,
    TOP_PICK_COUNT,
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
    for rank, item in enumerate(selected, start=1):
        item["top_pick_rank"] = rank

    return selected
