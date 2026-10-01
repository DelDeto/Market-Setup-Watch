import numpy as np
import pandas as pd

from .config import (
    CORRELATION_LOOKBACK_BARS,
    MAX_CORRELATED_SETUPS,
    MAX_RETURN_CORRELATION,
)


def _returns(frame):
    if frame is None or frame.empty:
        return None
    series = frame["close"].astype(float).pct_change().dropna()
    return series.tail(CORRELATION_LOOKBACK_BARS)


def apply_correlation_suppression(results, frames_by_symbol):
    selected = []
    cluster_members = []

    actionable = [
        item for item in results
        if item.get("bucket") in ("ENTRY_READY", "DEVELOPING")
    ]

    for item in actionable:
        item["correlation_suppressed"] = False
        item["correlation_reason"] = None

        frame = (frames_by_symbol.get(item.get("symbol")) or {}).get("15M")
        candidate_returns = _returns(frame)
        correlated_with = []

        if candidate_returns is not None:
            for kept in selected:
                if kept.get("direction") != item.get("direction"):
                    continue

                kept_frame = (
                    frames_by_symbol.get(kept.get("symbol")) or {}
                ).get("15M")
                kept_returns = _returns(kept_frame)
                if kept_returns is None:
                    continue

                joined = pd.concat(
                    [candidate_returns, kept_returns],
                    axis=1,
                    join="inner",
                ).dropna()

                if len(joined) < 30:
                    continue

                corr = float(joined.iloc[:, 0].corr(joined.iloc[:, 1]))
                if np.isfinite(corr) and abs(corr) >= MAX_RETURN_CORRELATION:
                    correlated_with.append((kept, corr))

        if len(correlated_with) >= MAX_CORRELATED_SETUPS:
            leaders = ", ".join(
                f"{leader.get('symbol')}({corr:+.2f})"
                for leader, corr in correlated_with[:2]
            )
            item["correlation_suppressed"] = True
            item["correlation_reason"] = (
                f"same-direction correlated cluster: {leaders}"
            )
        else:
            selected.append(item)

    return results
