import json
from datetime import datetime, timezone

from .config import OUTCOME_PATH


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

    return {
        "confirmed": bool(setup.get("confirmed")),
        "displacement": bool(setup.get("displacement")),
        "structure": bool(setup.get("structure")),
        "retest": bool(setup.get("retest")),
        "sweep": bool(setup.get("sweep")),
        "mtf_aligned": item.get("mtf_alignment") == "ALIGNED",
        "zone_a_or_better": zone.get("grade") in ("A+", "A", "B"),
    }


def register_candidates(records, results, generated_at):
    existing = {row.get("signal_id") for row in records}

    for item in results:
        if item.get("bucket") not in ("ENTRY_READY", "DEVELOPING"):
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
            "entry_lower": entry.get("lower"),
            "entry_upper": entry.get("upper"),
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


def update_outcomes(records, frames_by_symbol):
    now = datetime.now(timezone.utc)

    for row in records:
        if row.get("outcome") in ("WIN", "LOSS", "EXPIRED", "AMBIGUOUS"):
            continue

        frame = (
            frames_by_symbol.get(row.get("symbol")) or {}
        ).get("15M")

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
                age_hours = (now - created.to_pydatetime()).total_seconds() / 3600
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

        if entry_time is not None:
            checkpoints = row.setdefault(
                "checkpoints_r",
                {"1h": None, "4h": None, "24h": None},
            )

            for label, hours in (("1h", 1), ("4h", 4), ("24h", 24)):
                if checkpoints.get(label) is not None:
                    continue

                target_time = entry_time + pd.Timedelta(hours=hours)
                close_times = active_candles.index + pd.Timedelta(minutes=15)
                eligible = active_candles.loc[close_times >= target_time]

                if eligible.empty:
                    continue

                close_price = float(eligible.iloc[0]["close"])
                if direction == "long":
                    checkpoint_r = (close_price - entry_mid) / risk
                else:
                    checkpoint_r = (entry_mid - close_price) / risk

                checkpoints[label] = round(checkpoint_r, 3)

    return records
