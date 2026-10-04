import math

import pandas as pd

from smc_analysis import analyze_smc

from .config import (
    SWING_A_PLUS_RISK_PCT,
    SWING_A_PLUS_SCORE,
    SWING_A_RISK_PCT,
    SWING_IDEAL_RUNNER_MOVE_PCT,
    SWING_MAX_24H_CHASE_PCT,
    SWING_MAX_NOTIONAL_EQUITY_MULTIPLE,
    SWING_MAX_RUNNER_MOVE_PCT,
    SWING_MAX_STOP_PCT,
    SWING_MAX_TOTAL_RISK_PCT,
    SWING_MIN_RUNNER_MOVE_PCT,
    SWING_MIN_SCORE,
    SWING_MIN_STOP_PCT,
    SWING_RUNNER_FRACTION,
    SWING_TOP_PICK_COUNT,
    SWING_TP1_CLOSE_FRACTION,
    SWING_TP1_R,
    SWING_TP2_CLOSE_FRACTION,
    SWING_TP2_R,
)


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


def _regime_direction(analysis):
    regime = str((analysis or {}).get("regime") or "")
    trend = str((analysis or {}).get("trend") or "")

    bullish = {
        "BULLISH_TREND",
        "BULLISH_PULLBACK",
        "BEARISH_TO_BULLISH_TRANSITION",
        "BULLISH_TRANSITION",
    }
    bearish = {
        "BEARISH_TREND",
        "BEARISH_PULLBACK",
        "BULLISH_TO_BEARISH_TRANSITION",
        "BEARISH_TRANSITION",
    }

    if regime in bullish or trend == "bullish":
        return "long"
    if regime in bearish or trend == "bearish":
        return "short"
    return None


def score_swing_fast_candidate(symbol, frame, ticker):
    close = frame["close"].astype(float)
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    volume = frame["volume"].astype(float)

    last = float(close.iloc[-1])
    ema20 = float(close.ewm(span=20, adjust=False).mean().iloc[-1])
    ema50 = float(close.ewm(span=50, adjust=False).mean().iloc[-1])

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

    r24 = _return_pct(close, 6)
    r3d = _return_pct(close, 18)
    r7d = _return_pct(close, 42)

    lookback = min(42, len(close) - 1)
    recent_high = float(high.iloc[-lookback:].max())
    recent_low = float(low.iloc[-lookback:].min())
    range_pct = (
        (recent_high - recent_low) / max(last, 1e-12) * 100.0
    )

    prior_high = float(high.iloc[-21:-1].max())
    prior_low = float(low.iloc[-21:-1].min())
    dist_high_atr = abs(prior_high - last) / max(atr14, 1e-12)
    dist_low_atr = abs(last - prior_low) / max(atr14, 1e-12)
    extreme_distance_atr = min(dist_high_atr, dist_low_atr)

    avg_volume = float(volume.iloc[-21:-1].mean())
    volume_ratio = float(volume.iloc[-1]) / max(avg_volume, 1e-12)

    turnover = _safe_float((ticker or {}).get("turnover_24h"), 0.0) or 0.0
    spread_bps = _safe_float((ticker or {}).get("spread_bps"), None)

    if last > ema20 > ema50:
        direction = "long"
        trend_points = 22.0
    elif last < ema20 < ema50:
        direction = "short"
        trend_points = 22.0
    elif last >= ema20:
        direction = "long"
        trend_points = 10.0
    else:
        direction = "short"
        trend_points = 10.0

    # Swing candidates need enough 4H volatility to support multi-session
    # expansion, but very extreme ATR is more likely to be post-pump noise.
    if 1.0 <= atr_pct <= 5.0:
        volatility_points = 18.0
    elif 0.60 <= atr_pct <= 7.5:
        volatility_points = 12.0
    elif 0.35 <= atr_pct <= 10.0:
        volatility_points = 6.0
    else:
        volatility_points = 1.0

    if volume_ratio >= 1.8:
        volume_points = 14.0
    elif volume_ratio >= 1.2:
        volume_points = 10.0
    elif volume_ratio >= 0.8:
        volume_points = 6.0
    else:
        volume_points = 2.0

    if extreme_distance_atr <= 0.60:
        location_points = 12.0
    elif extreme_distance_atr <= 1.20:
        location_points = 8.0
    elif extreme_distance_atr <= 2.0:
        location_points = 4.0
    else:
        location_points = 0.0

    if turnover >= 50_000_000:
        liquidity_points = 12.0
    elif turnover >= 10_000_000:
        liquidity_points = 9.0
    elif turnover >= 2_000_000:
        liquidity_points = 6.0
    elif turnover >= 500_000:
        liquidity_points = 3.0
    else:
        liquidity_points = 1.0

    expansion_points = min(
        18.0,
        max(
            abs(r3d) * 0.35,
            abs(r7d) * 0.18,
            range_pct * 0.35,
            atr_pct * 2.0,
        ),
    )

    chase_penalty = 0.0
    if abs(r24) > SWING_MAX_24H_CHASE_PCT:
        chase_penalty = -18.0
    elif abs(r24) > SWING_MAX_24H_CHASE_PCT * 0.70:
        chase_penalty = -8.0

    spread_penalty = 0.0
    if spread_bps is not None:
        if spread_bps > 60:
            spread_penalty = -15.0
        elif spread_bps > 30:
            spread_penalty = -8.0
        elif spread_bps > 15:
            spread_penalty = -3.0

    score = max(
        0.0,
        min(
            100.0,
            trend_points
            + volatility_points
            + volume_points
            + location_points
            + liquidity_points
            + expansion_points
            + chase_penalty
            + spread_penalty,
        ),
    )

    projected_move_pct = max(
        SWING_MIN_RUNNER_MOVE_PCT,
        min(
            SWING_MAX_RUNNER_MOVE_PCT,
            max(
                range_pct * 0.90,
                atr_pct * 5.0,
                abs(r7d) * 0.75,
            ),
        ),
    )

    return {
        "symbol": symbol,
        "swing_fast_score": round(score, 2),
        "direction_hint": direction,
        "atr_pct_4h": round(atr_pct, 3),
        "return_24h_pct": round(r24, 3),
        "return_3d_pct": round(r3d, 3),
        "return_7d_pct": round(r7d, 3),
        "range_7d_pct": round(range_pct, 3),
        "volume_ratio_4h": round(volume_ratio, 3),
        "extreme_distance_atr": round(extreme_distance_atr, 3),
        "turnover_24h": turnover,
        "spread_bps": spread_bps,
        "projected_move_pct": round(projected_move_pct, 2),
        "chase_penalty": chase_penalty,
    }


def select_swing_deep_symbols(rows, limit):
    ranked = sorted(
        rows,
        key=lambda row: (
            -float(row.get("swing_fast_score") or 0.0),
            -float(row.get("projected_move_pct") or 0.0),
            -float(row.get("turnover_24h") or 0.0),
        ),
    )

    selected = []
    selected_set = set()

    # Reserve part of the list for high-volatility/high-upside candidates so
    # large-move coins are not crowded out by only the most liquid majors.
    expansion = sorted(
        rows,
        key=lambda row: (
            -float(row.get("projected_move_pct") or 0.0),
            -float(row.get("swing_fast_score") or 0.0),
        ),
    )
    for row in expansion[: max(20, limit // 3)]:
        symbol = row["symbol"]
        if symbol not in selected_set:
            selected.append(symbol)
            selected_set.add(symbol)
        if len(selected) >= limit:
            return selected

    for row in ranked:
        symbol = row["symbol"]
        if symbol not in selected_set:
            selected.append(symbol)
            selected_set.add(symbol)
        if len(selected) >= limit:
            break

    return selected


def _entry_zone(analysis_1h, direction):
    zone = (
        analysis_1h.get("nearest_demand")
        if direction == "long"
        else analysis_1h.get("nearest_supply")
    )
    if zone:
        return {
            "lower": float(zone["lower"]),
            "upper": float(zone["upper"]),
            "source": "1H demand" if direction == "long" else "1H supply",
            "grade": zone.get("grade"),
            "quality": zone.get("quality"),
        }

    current = float(analysis_1h["current_price"])
    atr = max(float(analysis_1h.get("atr") or 0.0), current * 0.001)
    half = atr * 0.18
    return {
        "lower": current - half,
        "upper": current + half,
        "source": "1H ATR pullback",
        "grade": None,
        "quality": None,
    }


def _build_stop(analysis_1h, entry, direction):
    atr = max(float(analysis_1h.get("atr") or 0.0), 1e-12)
    if direction == "long":
        refs = [float(entry["lower"])]
        ssl = (analysis_1h.get("ssl") or {}).get("price")
        if ssl is not None:
            refs.append(float(ssl))
        return min(refs) - 0.15 * atr

    refs = [float(entry["upper"])]
    bsl = (analysis_1h.get("bsl") or {}).get("price")
    if bsl is not None:
        refs.append(float(bsl))
    return max(refs) + 0.15 * atr


def _structural_room_pct(analysis_4h, direction, entry_mid):
    candidates = []

    if direction == "long":
        bsl = (analysis_4h.get("bsl") or {}).get("price")
        if bsl is not None and float(bsl) > entry_mid:
            candidates.append(float(bsl))
        supply = analysis_4h.get("nearest_supply")
        if supply and float(supply["lower"]) > entry_mid:
            candidates.append(float(supply["lower"]))
        if not candidates:
            return None
        target = min(candidates)
        return (target / entry_mid - 1.0) * 100.0

    ssl = (analysis_4h.get("ssl") or {}).get("price")
    if ssl is not None and float(ssl) < entry_mid:
        candidates.append(float(ssl))
    demand = analysis_4h.get("nearest_demand")
    if demand and float(demand["upper"]) < entry_mid:
        candidates.append(float(demand["upper"]))
    if not candidates:
        return None
    target = max(candidates)
    return (1.0 - target / entry_mid) * 100.0


def _price_for_r(entry_mid, risk, direction, multiple):
    if direction == "long":
        return entry_mid + multiple * risk
    return entry_mid - multiple * risk


def _price_for_move(entry_mid, direction, move_pct):
    if direction == "long":
        return entry_mid * (1.0 + move_pct / 100.0)
    return entry_mid * (1.0 - move_pct / 100.0)


def analyze_swing_candidate(symbol, frames, ticker, fast_row, market_context=None):
    analysis_4h = analyze_smc(frames["4H"], timeframe="4H")
    analysis_1h = analyze_smc(frames["1H"], timeframe="1H")

    direction_4h = _regime_direction(analysis_4h)
    direction_1h = _regime_direction(analysis_1h)
    setup_1h = analysis_1h.get("setup") or {}
    setup_4h = analysis_4h.get("setup") or {}

    setup_1h_direction = (
        "long" if setup_1h.get("direction") == "bullish"
        else "short" if setup_1h.get("direction") == "bearish"
        else None
    )

    direction = direction_4h or fast_row.get("direction_hint")
    if direction not in ("long", "short"):
        return None

    entry = _entry_zone(analysis_1h, direction)
    entry_mid = (float(entry["lower"]) + float(entry["upper"])) / 2.0
    stop = _build_stop(analysis_1h, entry, direction)
    risk = abs(entry_mid - stop)
    if risk <= 0:
        return None

    stop_pct = risk / max(entry_mid, 1e-12) * 100.0
    atr_1h = max(float(analysis_1h.get("atr") or 0.0), 1e-12)
    current = float(analysis_1h["current_price"])

    if current < entry["lower"]:
        entry_distance = entry["lower"] - current
    elif current > entry["upper"]:
        entry_distance = current - entry["upper"]
    else:
        entry_distance = 0.0
    entry_distance_atr = entry_distance / atr_1h

    structural_room_pct = _structural_room_pct(
        analysis_4h,
        direction,
        entry_mid,
    )

    projected = float(fast_row.get("projected_move_pct") or 0.0)
    if structural_room_pct is not None and structural_room_pct > 0:
        runner_move_pct = min(
            projected,
            max(SWING_MIN_RUNNER_MOVE_PCT, structural_room_pct),
        )
    else:
        runner_move_pct = projected

    runner_move_pct = max(
        SWING_MIN_RUNNER_MOVE_PCT,
        min(SWING_MAX_RUNNER_MOVE_PCT, runner_move_pct),
    )

    tp1 = _price_for_r(entry_mid, risk, direction, SWING_TP1_R)
    tp2 = _price_for_r(entry_mid, risk, direction, SWING_TP2_R)
    runner = _price_for_move(entry_mid, direction, runner_move_pct)
    runner_r = (
        abs(runner - entry_mid) / risk
        if risk > 0 else 0.0
    )

    score = float(fast_row.get("swing_fast_score") or 0.0) * 0.35

    if direction_4h == direction:
        score += 18.0
    else:
        score -= 15.0

    if direction_1h == direction:
        score += 12.0
    elif direction_1h and direction_1h != direction:
        score -= 12.0

    setup_score_1h = int(setup_1h.get("score") or 0)
    if setup_1h_direction == direction:
        score += min(16.0, setup_score_1h * 4.0)
        if setup_1h.get("confirmed"):
            score += 5.0
    elif setup_score_1h >= 2:
        score -= 10.0

    setup_4h_direction = (
        "long" if setup_4h.get("direction") == "bullish"
        else "short" if setup_4h.get("direction") == "bearish"
        else None
    )
    if setup_4h_direction == direction and int(setup_4h.get("score") or 0) >= 2:
        score += 6.0

    grade = entry.get("grade")
    if grade == "A+":
        score += 8.0
    elif grade == "A":
        score += 6.0
    elif grade == "B":
        score += 2.0

    if entry_distance_atr <= 0.35:
        score += 8.0
    elif entry_distance_atr <= 0.80:
        score += 4.0
    elif entry_distance_atr > 1.50:
        score -= 8.0

    if SWING_MIN_STOP_PCT <= stop_pct <= SWING_MAX_STOP_PCT:
        score += 6.0
    elif stop_pct < SWING_MIN_STOP_PCT:
        score -= 5.0
    else:
        score -= 8.0

    if runner_move_pct >= SWING_IDEAL_RUNNER_MOVE_PCT:
        score += 12.0
    elif runner_move_pct >= 15.0:
        score += 8.0
    elif runner_move_pct >= SWING_MIN_RUNNER_MOVE_PCT:
        score += 4.0

    participation = (ticker or {}).get("participation_context") or {}
    part_regime = participation.get("regime")
    if (
        (direction == "long" and part_regime == "LONG_BUILD")
        or (direction == "short" and part_regime == "SHORT_BUILD")
    ):
        score += 5.0

    market_regime = (market_context or {}).get("regime")
    if (
        (direction == "long" and market_regime == "BULLISH")
        or (direction == "short" and market_regime == "BEARISH")
    ):
        score += 4.0

    if abs(float(fast_row.get("return_24h_pct") or 0.0)) > SWING_MAX_24H_CHASE_PCT:
        score -= 12.0

    score = max(0.0, min(100.0, score))

    if score >= SWING_A_PLUS_SCORE:
        grade_label = "A+"
        base_risk_pct = SWING_A_PLUS_RISK_PCT
    else:
        grade_label = "A"
        base_risk_pct = SWING_A_RISK_PCT

    if stop_pct < SWING_MIN_STOP_PCT:
        risk_modifier = 0.60
        size_label = "TIGHT"
    elif stop_pct > SWING_MAX_STOP_PCT:
        risk_modifier = 0.60
        size_label = "WIDE"
    else:
        risk_modifier = 1.0
        size_label = "FULL"

    suggested_risk_pct = base_risk_pct * risk_modifier
    raw_notional_multiple = suggested_risk_pct / max(stop_pct, 1e-12)
    notional_multiple = min(
        raw_notional_multiple,
        SWING_MAX_NOTIONAL_EQUITY_MULTIPLE,
    )
    effective_risk_pct = notional_multiple * stop_pct

    total_target_r = (
        SWING_TP1_CLOSE_FRACTION * SWING_TP1_R
        + SWING_TP2_CLOSE_FRACTION * SWING_TP2_R
        + SWING_RUNNER_FRACTION * runner_r
    )

    return {
        "symbol": symbol,
        "mode": "SWING",
        "direction": direction,
        "swing_score": round(score, 2),
        "grade": grade_label,
        "analysis_4h": analysis_4h,
        "analysis_1h": analysis_1h,
        "fast": fast_row,
        "entry_zone": entry,
        "entry_mid": entry_mid,
        "stop_loss": stop,
        "stop_distance_pct": round(stop_pct, 3),
        "entry_distance_atr": round(entry_distance_atr, 3),
        "tp1": tp1,
        "tp1_r": SWING_TP1_R,
        "tp2": tp2,
        "tp2_r": SWING_TP2_R,
        "runner_target": runner,
        "runner_move_pct": round(runner_move_pct, 2),
        "runner_r": round(runner_r, 2),
        "structural_room_pct": (
            round(structural_room_pct, 2)
            if structural_room_pct is not None else None
        ),
        "position_plan": {
            "base_risk_pct": round(base_risk_pct, 3),
            "size_label": size_label,
            "risk_modifier": round(risk_modifier, 2),
            "recommended_risk_pct": round(effective_risk_pct, 3),
            "notional_equity_multiple": round(notional_multiple, 3),
            "tp1_close_fraction": SWING_TP1_CLOSE_FRACTION,
            "tp2_close_fraction": SWING_TP2_CLOSE_FRACTION,
            "runner_fraction": SWING_RUNNER_FRACTION,
            "projected_account_profit_pct": round(
                effective_risk_pct * total_target_r,
                2,
            ),
        },
        "ticker": ticker,
        "trade_plan": {
            "active": True,
            "execution_ready": score >= SWING_MIN_SCORE and entry_distance_atr <= 1.50,
            "direction": direction,
            "entry_zone": entry,
            "stop_loss": stop,
            "targets": [
                {"name": "TP1", "price": tp1, "source": "2R", "rr": SWING_TP1_R},
                {"name": "TP2", "price": tp2, "source": "4R", "rr": SWING_TP2_R},
                {
                    "name": "RUNNER",
                    "price": runner,
                    "source": f"{runner_move_pct:.1f}% swing move",
                    "rr": runner_r,
                },
            ],
            "mtf_alignment": {
                "label": (
                    "ALIGNED"
                    if direction_4h == direction and direction_1h == direction
                    else "PARTIAL"
                )
            },
            "management": {
                "protect_at_r": 1.0,
                "tp1_close_fraction": SWING_TP1_CLOSE_FRACTION,
                "tp2_close_fraction": SWING_TP2_CLOSE_FRACTION,
                "runner_fraction": SWING_RUNNER_FRACTION,
                "policy": (
                    "At +1R protect at breakeven; close 35% at +2R; "
                    "close 35% at +4R; trail 30% runner on 1H/4H structure."
                ),
            },
        },
    }


def select_swing_top_picks(items):
    candidates = [
        item for item in items
        if item
        and float(item.get("swing_score") or 0.0) >= SWING_MIN_SCORE
        and float(item.get("runner_move_pct") or 0.0) >= SWING_MIN_RUNNER_MOVE_PCT
        and float(item.get("entry_distance_atr") or 99.0) <= 1.50
    ]

    candidates.sort(
        key=lambda item: (
            -float(item.get("swing_score") or 0.0),
            -float(item.get("runner_move_pct") or 0.0),
            float(item.get("entry_distance_atr") or 99.0),
        )
    )

    selected = candidates[:SWING_TOP_PICK_COUNT]
    remaining_risk = SWING_MAX_TOTAL_RISK_PCT

    for rank, item in enumerate(selected, start=1):
        item["swing_top_pick_rank"] = rank
        plan = item.get("position_plan") or {}
        risk = min(
            float(plan.get("recommended_risk_pct") or 0.0),
            remaining_risk,
        )
        plan["recommended_risk_pct"] = round(risk, 3)
        stop_pct = float(item.get("stop_distance_pct") or 0.0)
        if stop_pct > 0:
            plan["notional_equity_multiple"] = round(
                min(
                    risk / stop_pct,
                    SWING_MAX_NOTIONAL_EQUITY_MULTIPLE,
                ),
                3,
            )
        remaining_risk = max(0.0, remaining_risk - risk)

    return selected
