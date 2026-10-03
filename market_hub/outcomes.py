import json
from datetime import datetime, timezone

from .config import (
    OUTCOME_PATH,
    PARTIAL_AT_R,
    PROTECT_AT_R,
    SELECTOR_TARGET_R,
    TRAIL_AT_R,
)


def load_outcomes():
    if not OUTCOME_PATH.exists():
        return []

    try:
        data = json.loads(OUTCOME_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_outcomes(records):
    OUTCOME_PATH.write_text(
        json.dumps(records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _signal_id(item, generated_at):
    plan = item.get("trade_plan", {})
    entry = plan.get("entry_zone", {})
    return "|".join([
        str(item.get("symbol")),
        str(item.get("direction")),
        str(round(float(entry.get("lower") or 0), 8)),
        str(round(float(entry.get("upper") or 0), 8)),
        str(round(float(plan.get("stop_loss") or 0), 8)),
    ])


def _features(item):
    setup = (item.get("analysis_15m") or {}).get("setup") or {}
    plan = item.get("trade_plan") or {}
    direction = item.get("direction")
    zone = (
        (item.get("analysis_15m") or {}).get("nearest_demand")
        if direction == "long"
        else (item.get("analysis_15m") or {}).get("nearest_supply")
    ) or {}

    filters = item.get("filters") or {}
    participation = filters.get("participation") or {}
    market_context = filters.get("market_context") or {}
    part_regime = participation.get("regime")
    market_regime = market_context.get("regime")

    return {
        "confirmed": bool(setup.get("confirmed")),
        "displacement": bool(setup.get("displacement")),
        "structure": bool(setup.get("structure")),
        "retest": bool(setup.get("retest")),
        "sweep": bool(setup.get("sweep")),
        "mtf_aligned": item.get("mtf_alignment") == "ALIGNED",
        "zone_a_or_better": zone.get("grade") in ("A+", "A", "B"),
        "rr_1_5_plus": (
            plan.get("first_target_rr") is not None
            and float(plan.get("first_target_rr")) >= 1.5
        ),
        "participation_aligned": (
            (direction == "long" and part_regime == "LONG_BUILD")
            or (direction == "short" and part_regime == "SHORT_BUILD")
        ),
        "market_context_aligned": (
            (direction == "long" and market_regime == "BULLISH")
            or (direction == "short" and market_regime == "BEARISH")
        ),
    }


def _management_defaults():
    return {
        "protect_at_r": PROTECT_AT_R,
        "partial_at_r": PARTIAL_AT_R,
        "trail_at_r": TRAIL_AT_R,
        "protect_reached": False,
        "partial_reached": False,
        "trail_reached": False,
        "protect_reached_at_utc": None,
        "partial_reached_at_utc": None,
        "trail_reached_at_utc": None,
        "raw_loss_after_protect": False,
        "raw_realized_r": None,
    }


def _ensure_management(row):
    management = row.setdefault(
        "management",
        _management_defaults(),
    )

    defaults = _management_defaults()
    for key, value in defaults.items():
        management.setdefault(key, value)

    mfe = row.get("mfe_r")
    if mfe is not None:
        try:
            mfe = float(mfe)
        except (TypeError, ValueError):
            mfe = None

    if mfe is not None:
        management["protect_reached"] = bool(
            management.get("protect_reached")
            or mfe >= PROTECT_AT_R
        )
        management["partial_reached"] = bool(
            management.get("partial_reached")
            or mfe >= PARTIAL_AT_R
        )
        management["trail_reached"] = bool(
            management.get("trail_reached")
            or mfe >= TRAIL_AT_R
        )

    outcome = row.get("outcome")
    if outcome == "LOSS":
        management["raw_loss_after_protect"] = bool(
            management.get("protect_reached")
        )
        management["raw_realized_r"] = -1.0
    elif outcome == "WIN":
        rr = row.get("first_target_rr")
        if rr is not None:
            try:
                management["raw_realized_r"] = round(float(rr), 3)
            except (TypeError, ValueError):
                pass

    return management


def register_candidates(records, results, generated_at):
    existing = {row.get("signal_id") for row in records}

    for item in results:
        if item.get("bucket") not in (
            "ENTRY_READY",
            "NEAR_ENTRY",
            "DEVELOPING",
        ):
            continue

        plan = item.get("trade_plan") or {}
        entry = plan.get("entry_zone") or {}
        if not plan.get("active"):
            continue

        signal_id = _signal_id(item, generated_at)
        if signal_id in existing:
            continue

        targets = plan.get("targets") or []
        records.append({
            "signal_id": signal_id,
            "created_at_utc": generated_at,
            "symbol": item.get("symbol"),
            "direction": item.get("direction"),
            "bucket": item.get("bucket"),
            "score": item.get("score"),
            "quality_score": item.get(
                "quality_score",
                item.get("score"),
            ),
            "execution_score": item.get("execution_score"),
            "entry_distance_atr": item.get("entry_distance_atr"),
            "entry_lower": entry.get("lower"),
            "entry_upper": entry.get("upper"),
            "entry_source": entry.get("source"),
            "entry_selection_score": entry.get("selection_score"),
            "selector_score": item.get("selector_score"),
            "top_pick_rank": item.get("top_pick_rank"),
            "selector": {
                "target_r": item.get("selector_target_r", SELECTOR_TARGET_R),
                "tp1": item.get("selector_tp1"),
                "status": "PENDING_ENTRY",
                "outcome": None,
                "closed_at_utc": None,
            },
            "stop_loss": plan.get("stop_loss"),
            "tp1": targets[0].get("price") if targets else None,
            "first_target_rr": plan.get("first_target_rr"),
            "features": _features(item),
            "status": "PENDING_ENTRY",
            "entry_time_utc": None,
            "closed_at_utc": None,
            "outcome": None,
            "mfe_r": None,
            "mae_r": None,
            "management": _management_defaults(),
            "checkpoints_r": {
                "1h": None,
                "4h": None,
                "24h": None,
            },
            "correlation_suppressed": bool(
                item.get("correlation_suppressed")
            ),
        })

        existing.add(signal_id)

    return records


def _to_timestamp(value):
    try:
        import pandas as pd
        return pd.Timestamp(value)
    except Exception:
        return None




def _update_selector_outcome(row, frame):
    selector = row.get("selector")
    if not isinstance(selector, dict):
        return

    if selector.get("outcome") in ("WIN", "LOSS", "AMBIGUOUS", "EXPIRED"):
        return

    entry_time = _to_timestamp(row.get("entry_time_utc"))
    if entry_time is None:
        if row.get("outcome") == "EXPIRED":
            selector["status"] = "CLOSED"
            selector["outcome"] = "EXPIRED"
            selector["closed_at_utc"] = row.get("closed_at_utc")
        return

    tp1 = selector.get("tp1")
    if tp1 is None:
        return

    direction = row.get("direction")
    stop = float(row.get("stop_loss"))
    tp1 = float(tp1)
    import pandas as pd
    candles = frame.loc[frame.index >= entry_time]
    if candles.empty:
        return

    selector["status"] = "ACTIVE"
    for ts, candle in candles.iterrows():
        high = float(candle["high"])
        low = float(candle["low"])
        if direction == "long":
            hit_stop = low <= stop
            hit_tp = high >= tp1
        else:
            hit_stop = high >= stop
            hit_tp = low <= tp1

        if hit_stop and hit_tp:
            selector["status"] = "CLOSED"
            selector["outcome"] = "AMBIGUOUS"
            selector["closed_at_utc"] = ts.isoformat()
            return
        if hit_tp:
            selector["status"] = "CLOSED"
            selector["outcome"] = "WIN"
            selector["closed_at_utc"] = ts.isoformat()
            return
        if hit_stop:
            selector["status"] = "CLOSED"
            selector["outcome"] = "LOSS"
            selector["closed_at_utc"] = ts.isoformat()
            return


def update_outcomes(records, frames_by_symbol):
    now = datetime.now(timezone.utc)

    for row in records:
        management = _ensure_management(row)

        frame = (
            frames_by_symbol.get(row.get("symbol")) or {}
        ).get("15M")

        if frame is not None and not frame.empty:
            _update_selector_outcome(row, frame)

        if row.get("outcome") in (
            "WIN",
            "LOSS",
            "EXPIRED",
            "AMBIGUOUS",
        ):
            continue

        if frame is None or frame.empty:
            continue

        created = _to_timestamp(row.get("created_at_utc"))
        if created is None:
            continue

        import pandas as pd

        candle_close_times = frame.index + pd.Timedelta(minutes=15)
        candles = frame.loc[candle_close_times > created]
        if candles.empty:
            continue

        direction = row.get("direction")
        lower = float(row.get("entry_lower"))
        upper = float(row.get("entry_upper"))
        stop = float(row.get("stop_loss"))
        tp1 = row.get("tp1")
        tp1 = float(tp1) if tp1 is not None else None
        entry_mid = (lower + upper) / 2.0
        risk = abs(entry_mid - stop)

        if risk <= 0:
            continue

        entry_time = _to_timestamp(row.get("entry_time_utc"))
        active_candles = candles

        if row.get("status") == "PENDING_ENTRY":
            touched = candles[
                (candles["low"] <= upper)
                & (candles["high"] >= lower)
            ]
            if touched.empty:
                age_hours = (
                    now - created.to_pydatetime()
                ).total_seconds() / 3600
                if age_hours >= 24:
                    row["status"] = "CLOSED"
                    row["outcome"] = "EXPIRED"
                    row["closed_at_utc"] = now.isoformat()
                continue

            entry_time = touched.index[0]
            row["entry_time_utc"] = entry_time.isoformat()
            row["status"] = "ACTIVE"
            active_candles = candles.loc[candles.index >= entry_time]
        elif entry_time is not None:
            active_candles = candles.loc[candles.index >= entry_time]

        best_r = 0.0
        worst_r = 0.0

        for ts, candle in active_candles.iterrows():
            high = float(candle["high"])
            low = float(candle["low"])

            if direction == "long":
                favorable = (high - entry_mid) / risk
                adverse = (entry_mid - low) / risk
                hit_stop = low <= stop
                hit_tp = tp1 is not None and high >= tp1
            else:
                favorable = (entry_mid - low) / risk
                adverse = (high - entry_mid) / risk
                hit_stop = high >= stop
                hit_tp = tp1 is not None and low <= tp1

            best_r = max(best_r, favorable)
            worst_r = max(worst_r, adverse)

            if (
                not management.get("protect_reached")
                and favorable >= PROTECT_AT_R
            ):
                management["protect_reached"] = True
                management["protect_reached_at_utc"] = ts.isoformat()

            if (
                not management.get("partial_reached")
                and favorable >= PARTIAL_AT_R
            ):
                management["partial_reached"] = True
                management["partial_reached_at_utc"] = ts.isoformat()

            if (
                not management.get("trail_reached")
                and favorable >= TRAIL_AT_R
            ):
                management["trail_reached"] = True
                management["trail_reached_at_utc"] = ts.isoformat()

            # Raw outcome is deliberately preserved. If the same 15M candle
            # touches +1R and the original stop, intrabar ordering is unknown,
            # so we do not pretend a breakeven stop was definitely executed.
            if hit_stop and hit_tp:
                row["status"] = "CLOSED"
                row["outcome"] = "AMBIGUOUS"
                row["closed_at_utc"] = ts.isoformat()
                break
            if hit_tp:
                row["status"] = "CLOSED"
                row["outcome"] = "WIN"
                row["closed_at_utc"] = ts.isoformat()
                break
            if hit_stop:
                row["status"] = "CLOSED"
                row["outcome"] = "LOSS"
                row["closed_at_utc"] = ts.isoformat()
                break

        row["mfe_r"] = round(best_r, 3)
        row["mae_r"] = round(worst_r, 3)
        _ensure_management(row)

        if entry_time is not None:
            checkpoints = row.setdefault(
                "checkpoints_r",
                {"1h": None, "4h": None, "24h": None},
            )

            for label, hours in (
                ("1h", 1),
                ("4h", 4),
                ("24h", 24),
            ):
                if checkpoints.get(label) is not None:
                    continue

                target_time = entry_time + pd.Timedelta(hours=hours)
                close_times = active_candles.index + pd.Timedelta(minutes=15)
                eligible = active_candles.loc[
                    close_times >= target_time
                ]

                if eligible.empty:
                    continue

                close_price = float(eligible.iloc[0]["close"])
                if direction == "long":
                    checkpoint_r = (
                        close_price - entry_mid
                    ) / risk
                else:
                    checkpoint_r = (
                        entry_mid - close_price
                    ) / risk

                checkpoints[label] = round(checkpoint_r, 3)

    # Backfill new management observations for historical rows without
    # rewriting their original WIN/LOSS classification.
    for row in records:
        _ensure_management(row)

    return records
