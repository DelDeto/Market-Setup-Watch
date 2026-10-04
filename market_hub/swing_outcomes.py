import json
from datetime import datetime, timedelta, timezone

import pandas as pd

from .config import SWING_OUTCOME_PATH


ENTRY_EXPIRY_HOURS = 48


def load_swing_outcomes():
    if not SWING_OUTCOME_PATH.exists():
        return []
    try:
        data = json.loads(SWING_OUTCOME_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_swing_outcomes(records):
    SWING_OUTCOME_PATH.write_text(
        json.dumps(records, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _ts(value):
    if not value:
        return None
    parsed = pd.Timestamp(str(value))
    if parsed.tzinfo is None:
        parsed = parsed.tz_localize("UTC")
    return parsed.tz_convert("UTC")


def register_swing_picks(records, picks, generated_at):
    for item in picks:
        active_same = next(
            (
                row for row in records
                if row.get("symbol") == item.get("symbol")
                and row.get("direction") == item.get("direction")
                and row.get("status") in ("PENDING_ENTRY", "ACTIVE")
            ),
            None,
        )
        if active_same is not None:
            history = active_same.setdefault("promotion_history", [])
            history.append({
                "at_utc": generated_at,
                "rank": item.get("swing_top_pick_rank"),
                "score": item.get("swing_score"),
            })
            continue

        entry = item.get("entry_zone") or {}
        records.append({
            "signal_id": (
                f"{item.get('symbol')}|{item.get('direction')}|"
                f"{generated_at}"
            ),
            "created_at_utc": generated_at,
            "symbol": item.get("symbol"),
            "direction": item.get("direction"),
            "rank": item.get("swing_top_pick_rank"),
            "score": item.get("swing_score"),
            "grade": item.get("grade"),
            "entry_lower": entry.get("lower"),
            "entry_upper": entry.get("upper"),
            "entry_source": entry.get("source"),
            "stop_loss": item.get("stop_loss"),
            "tp1": item.get("tp1"),
            "tp2": item.get("tp2"),
            "runner_target": item.get("runner_target"),
            "runner_move_pct": item.get("runner_move_pct"),
            "position_plan": item.get("position_plan"),
            "status": "PENDING_ENTRY",
            "outcome": None,
            "entry_time_utc": None,
            "closed_at_utc": None,
            "tp1_hit": False,
            "tp1_hit_at_utc": None,
            "tp2_hit": False,
            "tp2_hit_at_utc": None,
            "runner_hit": False,
            "runner_hit_at_utc": None,
            "protect_1r_hit": False,
            "mfe_r": None,
            "mae_r": None,
            "promotion_history": [{
                "at_utc": generated_at,
                "rank": item.get("swing_top_pick_rank"),
                "score": item.get("swing_score"),
            }],
        })

    return records


def update_swing_outcomes(records, frames_by_symbol):
    now = datetime.now(timezone.utc)

    for row in records:
        if row.get("status") in ("CLOSED", "EXPIRED"):
            continue

        frame = (
            frames_by_symbol.get(row.get("symbol")) or {}
        ).get("1H")
        if frame is None or frame.empty:
            continue

        created = _ts(row.get("created_at_utc"))
        if created is None:
            continue

        direction = row.get("direction")
        lower = float(row.get("entry_lower"))
        upper = float(row.get("entry_upper"))
        stop = float(row.get("stop_loss"))
        tp1 = float(row.get("tp1"))
        tp2 = float(row.get("tp2"))
        runner = float(row.get("runner_target"))
        entry_mid = (lower + upper) / 2.0
        risk = abs(entry_mid - stop)
        if risk <= 0:
            continue

        entry_time = _ts(row.get("entry_time_utc"))

        if entry_time is None:
            candles = frame.loc[frame.index >= created]
            for ts, candle in candles.iterrows():
                high = float(candle["high"])
                low = float(candle["low"])
                if low <= upper and high >= lower:
                    entry_time = ts
                    row["entry_time_utc"] = ts.isoformat()
                    row["status"] = "ACTIVE"
                    break

            if entry_time is None:
                age = now - created.to_pydatetime()
                if age >= timedelta(hours=ENTRY_EXPIRY_HOURS):
                    row["status"] = "EXPIRED"
                    row["outcome"] = "EXPIRED"
                    row["closed_at_utc"] = now.isoformat()
                continue

        candles = frame.loc[frame.index >= entry_time]
        best_r = -999.0
        worst_r = 999.0

        for ts, candle in candles.iterrows():
            high = float(candle["high"])
            low = float(candle["low"])

            if direction == "long":
                favorable = (high - entry_mid) / risk
                adverse = (low - entry_mid) / risk
                stop_hit = low <= stop
                protect_hit = high >= entry_mid + risk
                tp1_hit = high >= tp1
                tp2_hit = high >= tp2
                runner_hit = high >= runner
            else:
                favorable = (entry_mid - low) / risk
                adverse = (entry_mid - high) / risk
                stop_hit = high >= stop
                protect_hit = low <= entry_mid - risk
                tp1_hit = low <= tp1
                tp2_hit = low <= tp2
                runner_hit = low <= runner

            best_r = max(best_r, favorable)
            worst_r = min(worst_r, adverse)

            if protect_hit:
                row["protect_1r_hit"] = True

            if tp1_hit and not row.get("tp1_hit"):
                row["tp1_hit"] = True
                row["tp1_hit_at_utc"] = ts.isoformat()
                row["outcome"] = "WIN"

            if tp2_hit and not row.get("tp2_hit"):
                row["tp2_hit"] = True
                row["tp2_hit_at_utc"] = ts.isoformat()

            if runner_hit and not row.get("runner_hit"):
                row["runner_hit"] = True
                row["runner_hit_at_utc"] = ts.isoformat()
                row["status"] = "CLOSED"
                row["closed_at_utc"] = ts.isoformat()
                row["outcome"] = "WIN"
                break

            if stop_hit:
                row["status"] = "CLOSED"
                row["closed_at_utc"] = ts.isoformat()
                if row.get("tp1_hit"):
                    row["outcome"] = "WIN"
                elif row.get("protect_1r_hit"):
                    row["outcome"] = "BE"
                else:
                    row["outcome"] = "LOSS"
                break

        if best_r > -999:
            row["mfe_r"] = round(best_r, 3)
        if worst_r < 999:
            row["mae_r"] = round(worst_r, 3)

    return records
