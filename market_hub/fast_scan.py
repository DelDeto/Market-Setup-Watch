import math

import pandas as pd


def _safe_float(value, default=None):
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _return_pct(values, bars):
    if len(values) <= bars:
        return 0.0
    start = float(values.iloc[-(bars + 1)])
    end = float(values.iloc[-1])
    if start == 0:
        return 0.0
    return (end / start - 1.0) * 100.0


def score_fast_candidate(symbol, frame, ticker):
    close = frame["close"].astype(float)
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    volume = frame["volume"].astype(float)

    last = float(close.iloc[-1])
    ema20 = float(close.ewm(span=20, adjust=False).mean().iloc[-1])
    ema50 = (
        float(close.ewm(span=50, adjust=False).mean().iloc[-1])
        if len(close) >= 50
        else ema20
    )

    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr14 = float(tr.rolling(14, min_periods=8).mean().iloc[-1])
    atr_pct = atr14 / max(last, 1e-12) * 100.0

    r4 = _return_pct(close, 4)
    r12 = _return_pct(close, 12)
    r24 = _return_pct(close, 24)

    prior_high = float(high.iloc[-21:-1].max()) if len(high) >= 21 else float(high.max())
    prior_low = float(low.iloc[-21:-1].min()) if len(low) >= 21 else float(low.min())
    distance_high_atr = abs(prior_high - last) / max(atr14, 1e-12)
    distance_low_atr = abs(last - prior_low) / max(atr14, 1e-12)
    extreme_distance_atr = min(distance_high_atr, distance_low_atr)

    avg_volume = float(volume.iloc[-21:-1].mean()) if len(volume) >= 21 else float(volume.mean())
    volume_ratio = float(volume.iloc[-1]) / max(avg_volume, 1e-12)

    turnover = _safe_float((ticker or {}).get("turnover_24h"), 0.0) or 0.0
    spread_bps = _safe_float((ticker or {}).get("spread_bps"), None)
    change_rate = _safe_float((ticker or {}).get("change_rate_24h"), 0.0) or 0.0
    change_24h_pct = change_rate * 100.0 if abs(change_rate) <= 2 else change_rate

    trend_points = 0
    if last > ema20 > ema50:
        direction = "long"
        trend_points = 20
    elif last < ema20 < ema50:
        direction = "short"
        trend_points = 20
    elif last >= ema20:
        direction = "long"
        trend_points = 10
    else:
        direction = "short"
        trend_points = 10

    momentum_strength = max(abs(r4), abs(r12) * 0.7, abs(r24) * 0.45)
    momentum_points = min(20.0, momentum_strength * 3.0)

    if 0.15 <= atr_pct <= 4.0:
        volatility_points = 12.0
    elif 0.08 <= atr_pct <= 8.0:
        volatility_points = 8.0
    else:
        volatility_points = 3.0

    if extreme_distance_atr <= 0.6:
        location_points = 15.0
    elif extreme_distance_atr <= 1.2:
        location_points = 10.0
    elif extreme_distance_atr <= 2.0:
        location_points = 5.0
    else:
        location_points = 0.0

    if volume_ratio >= 2.0:
        volume_points = 15.0
    elif volume_ratio >= 1.3:
        volume_points = 11.0
    elif volume_ratio >= 0.9:
        volume_points = 7.0
    else:
        volume_points = 2.0

    if turnover >= 50_000_000:
        liquidity_points = 15.0
    elif turnover >= 10_000_000:
        liquidity_points = 12.0
    elif turnover >= 2_000_000:
        liquidity_points = 9.0
    elif turnover >= 500_000:
        liquidity_points = 5.0
    elif turnover > 0:
        liquidity_points = 2.0
    else:
        liquidity_points = 0.0

    spread_penalty = 0.0
    if spread_bps is not None:
        if spread_bps > 60:
            spread_penalty = -18.0
        elif spread_bps > 30:
            spread_penalty = -10.0
        elif spread_bps > 15:
            spread_penalty = -4.0

    fast_score = max(
        0.0,
        min(
            100.0,
            trend_points
            + momentum_points
            + volatility_points
            + location_points
            + volume_points
            + liquidity_points
            + spread_penalty,
        ),
    )

    opportunity_strength = (
        abs(r4)
        + abs(r12) * 0.5
        + abs(change_24h_pct) * 0.25
        + max(0.0, volume_ratio - 1.0) * 2.0
        + atr_pct
    )

    return {
        "symbol": symbol,
        "fast_score": round(fast_score, 2),
        "direction_hint": direction,
        "return_4h_pct": round(r4, 3),
        "return_12h_pct": round(r12, 3),
        "return_24h_pct": round(r24, 3),
        "ticker_change_24h_pct": round(change_24h_pct, 3),
        "atr_pct_1h": round(atr_pct, 3),
        "volume_ratio_1h": round(volume_ratio, 3),
        "extreme_distance_atr": round(extreme_distance_atr, 3),
        "turnover_24h": turnover,
        "spread_bps": spread_bps,
        "opportunity_strength": round(opportunity_strength, 3),
    }


def select_deep_scan_symbols(
    fast_rows,
    deep_limit,
    liquidity_reserve,
    volatility_reserve,
    required_symbols=None,
):
    required_symbols = list(dict.fromkeys(required_symbols or []))
    by_symbol = {row["symbol"]: row for row in fast_rows}

    selected = []
    selected_set = set()

    def add(symbol):
        if (
            symbol
            and symbol in by_symbol
            and symbol not in selected_set
            and len(selected) < deep_limit
        ):
            selected.append(symbol)
            selected_set.add(symbol)

    for symbol in required_symbols:
        add(symbol)

    liquidity_ranked = sorted(
        fast_rows,
        key=lambda row: (
            -float(row.get("turnover_24h") or 0.0),
            -float(row.get("fast_score") or 0.0),
        ),
    )
    added = 0
    for row in liquidity_ranked:
        before = len(selected)
        add(row["symbol"])
        if len(selected) > before:
            added += 1
        if added >= liquidity_reserve:
            break

    opportunity_ranked = sorted(
        fast_rows,
        key=lambda row: (
            -float(row.get("opportunity_strength") or 0.0),
            -float(row.get("fast_score") or 0.0),
        ),
    )
    added = 0
    for row in opportunity_ranked:
        before = len(selected)
        add(row["symbol"])
        if len(selected) > before:
            added += 1
        if added >= volatility_reserve:
            break

    score_ranked = sorted(
        fast_rows,
        key=lambda row: (
            -float(row.get("fast_score") or 0.0),
            -float(row.get("turnover_24h") or 0.0),
        ),
    )
    for row in score_ranked:
        add(row["symbol"])
        if len(selected) >= deep_limit:
            break

    return selected
