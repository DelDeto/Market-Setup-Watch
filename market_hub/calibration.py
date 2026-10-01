import json
from pathlib import Path

from .config import (
    CALIBRATION_PATH,
    MIN_CALIBRATION_FEATURE_SAMPLES,
    MIN_CALIBRATION_OUTCOMES,
)


FEATURES = (
    "confirmed",
    "displacement",
    "structure",
    "retest",
    "sweep",
    "mtf_aligned",
    "zone_a_or_better",
    "rr_1_5_plus",
    "participation_aligned",
    "market_context_aligned",
)


def _closed_outcomes(records):
    return [
        row for row in records
        if row.get("outcome") in ("WIN", "LOSS")
    ]


def build_calibration(records):
    closed = _closed_outcomes(records)
    summary = {
        "active": False,
        "closed_samples": len(closed),
        "baseline_win_rate": None,
        "feature_adjustments": {},
    }

    if not closed:
        CALIBRATION_PATH.write_text(
            json.dumps(summary, indent=2),
            encoding="utf-8",
        )
        return summary

    baseline = sum(row.get("outcome") == "WIN" for row in closed) / len(closed)
    summary["baseline_win_rate"] = baseline

    if len(closed) < MIN_CALIBRATION_OUTCOMES:
        CALIBRATION_PATH.write_text(
            json.dumps(summary, indent=2),
            encoding="utf-8",
        )
        return summary

    adjustments = {}

    for feature in FEATURES:
        rows = [
            row for row in closed
            if (row.get("features") or {}).get(feature) is True
        ]

        if len(rows) < MIN_CALIBRATION_FEATURE_SAMPLES:
            continue

        win_rate = sum(row.get("outcome") == "WIN" for row in rows) / len(rows)
        delta = win_rate - baseline

        # Guardrail: at most +/-3 score points per empirical feature.
        points = max(-3, min(3, int(round(delta * 10))))
        adjustments[feature] = {
            "samples": len(rows),
            "win_rate": win_rate,
            "delta_vs_baseline": delta,
            "points": points,
        }

    summary["active"] = bool(adjustments)
    summary["feature_adjustments"] = adjustments

    CALIBRATION_PATH.write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )
    return summary


def adaptive_points(features, calibration):
    if not calibration or not calibration.get("active"):
        return 0

    total = 0
    for feature, meta in calibration.get("feature_adjustments", {}).items():
        if features.get(feature) is True:
            total += int(meta.get("points", 0))

    # Aggregate guardrail.
    return max(-6, min(6, total))
