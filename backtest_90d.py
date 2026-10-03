import argparse
import json
import math
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from market_hub.binance_crosslist import get_binance_crosslisted_bases, mexc_underlying
from market_hub.config import MAX_SPREAD_BPS, MIN_24H_TURNOVER_USDT
from market_hub.correlation import apply_correlation_suppression
from market_hub.market_context import derive_market_context
from market_hub.mexc_market import (
    INTERVAL_MAP,
    INTERVAL_SECONDS,
    _get_json,
    _parse_kline,
    get_all_tickers,
    get_contract_universe,
)
from market_hub.scanner import analyze_symbol

OUTDIR = Path("output/backtest_90d")
OUTDIR.mkdir(parents=True, exist_ok=True)

BUCKET_PRIORITY = {
    "ENTRY_READY": 0,
    "NEAR_ENTRY": 1,
    "DEVELOPING": 2,
    "WATCHLIST": 3,
}


def liquidity_value(ticker):
    if not ticker:
        return 0.0
    turnover = ticker.get("turnover_24h")
    if turnover is not None:
        return max(0.0, float(turnover))
    volume = ticker.get("volume_24h")
    price = ticker.get("last_price")
    if volume is not None and price is not None:
        return max(0.0, float(volume) * float(price))
    return 0.0


def live_quality_ok(ticker):
    if not ticker or ticker.get("last_price") is None:
        return False
    if liquidity_value(ticker) < MIN_24H_TURNOVER_USDT:
        return False
    spread = ticker.get("spread_bps")
    if spread is not None and spread > MAX_SPREAD_BPS:
        return False
    return True


def select_current_universe(limit):
    mexc = get_contract_universe()
    crosslisted, meta = get_binance_crosslisted_bases()
    if crosslisted is not None:
        mexc = [s for s in mexc if mexc_underlying(s) in crosslisted]
    tickers = get_all_tickers()
    ranked = [(s, liquidity_value(tickers.get(s))) for s in mexc if live_quality_ok(tickers.get(s))]
    ranked.sort(key=lambda x: x[1], reverse=True)
    selected = [s for s, _ in ranked[:limit]]
    for benchmark in ("BTC_USDT", "ETH_USDT"):
        if benchmark not in selected and benchmark in mexc:
            selected.append(benchmark)
    return selected, tickers, meta, len(mexc), len(ranked)


def fetch_15m_range(symbol, start_ts, end_ts, chunk_bars=1200):
    sec = INTERVAL_SECONDS["15m"]
    cursor = int(start_ts.timestamp())
    end = int(end_ts.timestamp())
    frames = []
    while cursor < end:
        chunk_end = min(end, cursor + sec * chunk_bars)
        payload = _get_json(
            f"/api/v1/contract/kline/{symbol}",
            params={
                "interval": INTERVAL_MAP["15m"],
                "start": cursor,
                "end": chunk_end,
            },
            timeout=20,
            retries=4,
        )
        frame = _parse_kline(payload)
        if frame is not None and not frame.empty:
            frames.append(frame)
            last_ts = int(frame.index.max().timestamp())
            cursor = max(cursor + sec, last_ts + sec)
        else:
            cursor = chunk_end + sec
    if not frames:
        raise RuntimeError(f"No 15M history for {symbol}")
    frame = pd.concat(frames).sort_index()
    frame = frame[~frame.index.duplicated(keep="last")]
    return frame.loc[(frame.index >= start_ts) & (frame.index <= end_ts)]


def aggregate(frame, rule):
    out = frame.resample(rule, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    )
    return out.dropna()


def historical_ticker(frame_15m):
    if frame_15m.empty:
        return {}
    last = float(frame_15m["close"].iloc[-1])
    tail = frame_15m.tail(96)
    turnover = float((tail["volume"].astype(float) * tail["close"].astype(float)).sum())
    change = None
    if len(frame_15m) >= 97:
        old = float(frame_15m["close"].iloc[-97])
        if old:
            change = last / old - 1.0
    return {
        "last_price": last,
        "turnover_24h": turnover,
        "spread_bps": None,
        "change_rate_24h": change,
        "hold_vol": None,
        "funding_rate": None,
        "participation_context": {"regime": "N/A", "hold_vol_change_pct": None},
    }


def sort_results(results):
    results.sort(
        key=lambda item: (
            BUCKET_PRIORITY.get(item.get("bucket"), 9),
            -float(item.get("execution_score", 0)),
            -float(item.get("quality_score", item.get("score", 0))),
            float(item.get("entry_distance_atr") if item.get("entry_distance_atr") is not None else 99),
        )
    )
    return results


def signal_id(item):
    plan = item.get("trade_plan") or {}
    entry = plan.get("entry_zone") or {}
    return "|".join([
        str(item.get("symbol")),
        str(item.get("direction")),
        str(round(float(entry.get("lower") or 0), 8)),
        str(round(float(entry.get("upper") or 0), 8)),
        str(round(float(plan.get("stop_loss") or 0), 8)),
    ])


def record_candidate(item, created_at):
    plan = item.get("trade_plan") or {}
    entry = plan.get("entry_zone") or {}
    targets = plan.get("targets") or []
    return {
        "signal_id": signal_id(item),
        "created_at_utc": created_at.isoformat(),
        "symbol": item.get("symbol"),
        "direction": item.get("direction"),
        "bucket": item.get("bucket"),
        "quality_score": item.get("quality_score"),
        "execution_score": item.get("execution_score"),
        "entry_distance_atr": item.get("entry_distance_atr"),
        "mtf_alignment": item.get("mtf_alignment"),
        "entry_lower": entry.get("lower"),
        "entry_upper": entry.get("upper"),
        "entry_source": entry.get("source"),
        "entry_zone_grade": entry.get("zone_grade"),
        "stop_loss": plan.get("stop_loss"),
        "tp1": targets[0].get("price") if targets else None,
        "first_target_rr": plan.get("first_target_rr"),
        "correlation_suppressed": bool(item.get("correlation_suppressed")),
    }


def evaluate_candidate(row, frame):
    created = pd.Timestamp(row["created_at_utc"])
    close_times = frame.index + pd.Timedelta(minutes=15)
    future = frame.loc[close_times > created]
    lower = float(row["entry_lower"])
    upper = float(row["entry_upper"])
    stop = float(row["stop_loss"])
    tp1 = float(row["tp1"]) if row.get("tp1") is not None else None
    direction = row["direction"]
    entry_mid = (lower + upper) / 2.0
    risk = abs(entry_mid - stop)
    if risk <= 0 or future.empty:
        return {**row, "outcome": "OPEN", "mfe_r": None, "mae_r": None}

    entry_window = future.loc[close_times.loc[future.index] <= created + pd.Timedelta(hours=24)]
    touched = entry_window[(entry_window["low"] <= upper) & (entry_window["high"] >= lower)]
    if touched.empty:
        return {**row, "outcome": "EXPIRED", "entry_time_utc": None, "closed_at_utc": None, "mfe_r": 0.0, "mae_r": 0.0}

    entry_ts = touched.index[0]
    active = future.loc[future.index >= entry_ts]
    best_r = 0.0
    worst_r = 0.0
    protect = partial = trail = False
    outcome = "OPEN"
    closed_at = None

    for ts, candle in active.iterrows():
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
        protect = protect or favorable >= 1.0
        partial = partial or favorable >= 1.5
        trail = trail or favorable >= 2.0

        if hit_stop and hit_tp:
            outcome = "AMBIGUOUS"
            closed_at = ts.isoformat()
            break
        if hit_tp:
            outcome = "WIN"
            closed_at = ts.isoformat()
            break
        if hit_stop:
            outcome = "LOSS"
            closed_at = ts.isoformat()
            break

    raw_r = None
    if outcome == "WIN":
        raw_r = float(row.get("first_target_rr") or 0)
    elif outcome == "LOSS":
        raw_r = -1.0

    return {
        **row,
        "outcome": outcome,
        "entry_time_utc": entry_ts.isoformat(),
        "closed_at_utc": closed_at,
        "mfe_r": round(best_r, 3),
        "mae_r": round(worst_r, 3),
        "protect_reached": protect,
        "partial_reached": partial,
        "trail_reached": trail,
        "raw_realized_r": round(raw_r, 3) if raw_r is not None else None,
    }


def metric_block(rows):
    total = len(rows)
    counts = Counter(r["outcome"] for r in rows)
    closed = [r for r in rows if r["outcome"] in ("WIN", "LOSS")]
    wins = [r for r in closed if r["outcome"] == "WIN"]
    losses = [r for r in closed if r["outcome"] == "LOSS"]
    rvals = [float(r["raw_realized_r"]) for r in closed if r.get("raw_realized_r") is not None]
    win_r = sum(v for v in rvals if v > 0)
    loss_r = abs(sum(v for v in rvals if v < 0))
    chronological = sorted(
        [r for r in closed if r.get("closed_at_utc")],
        key=lambda r: r["closed_at_utc"],
    )
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for r in chronological:
        equity += float(r.get("raw_realized_r") or 0)
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return {
        "signals": total,
        "wins": len(wins),
        "losses": len(losses),
        "expired": counts.get("EXPIRED", 0),
        "ambiguous": counts.get("AMBIGUOUS", 0),
        "open": counts.get("OPEN", 0),
        "closed_win_loss": len(closed),
        "win_rate": round(len(wins) / len(closed), 4) if closed else None,
        "net_r": round(sum(rvals), 3),
        "expectancy_r": round(sum(rvals) / len(rvals), 3) if rvals else None,
        "profit_factor_r": round(win_r / loss_r, 3) if loss_r > 0 else None,
        "max_drawdown_r": round(max_dd, 3),
        "losses_after_1r": sum(r["outcome"] == "LOSS" and r.get("protect_reached") for r in rows),
        "losses_after_1_5r": sum(r["outcome"] == "LOSS" and r.get("partial_reached") for r in rows),
        "losses_after_2r": sum(r["outcome"] == "LOSS" and r.get("trail_reached") for r in rows),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--symbols", type=int, default=30)
    ap.add_argument("--stride", type=int, default=4, help="15M bars per replay step; 4 = hourly")
    args = ap.parse_args()

    now = pd.Timestamp.now(tz="UTC").floor("15min")
    signal_end = now - pd.Timedelta(days=2)
    signal_start = signal_end - pd.Timedelta(days=args.days)
    history_start = signal_start - pd.Timedelta(days=72)
    fetch_end = now

    selected, live_tickers, cross_meta, cross_count, quality_count = select_current_universe(args.symbols)
    print(f"Backtest universe selected={len(selected)} requested={args.symbols} crosslisted={cross_count} quality_now={quality_count}")
    print("Universe:", ",".join(selected))
    print(f"Window signals={signal_start.isoformat()} -> {signal_end.isoformat()} fetch={history_start.isoformat()} -> {fetch_end.isoformat()} stride={args.stride}x15m")

    data = {}
    failed = {}
    for i, symbol in enumerate(selected, start=1):
        try:
            frame15 = fetch_15m_range(symbol, history_start, fetch_end)
            data[symbol] = {
                "15M": frame15,
                "1H": aggregate(frame15, "1h"),
                "4H": aggregate(frame15, "4h"),
            }
            print(f"[{i}/{len(selected)}] {symbol}: 15M={len(frame15)} 1H={len(data[symbol]['1H'])} 4H={len(data[symbol]['4H'])}")
        except Exception as exc:
            failed[symbol] = str(exc)
            print(f"[{i}/{len(selected)}] FAIL {symbol}: {exc}")

    if "BTC_USDT" not in data or "ETH_USDT" not in data:
        raise RuntimeError("BTC/ETH benchmark history unavailable")

    scan_index = data["BTC_USDT"]["15M"].index
    scan_index = scan_index[(scan_index + pd.Timedelta(minutes=15) >= signal_start) & (scan_index + pd.Timedelta(minutes=15) <= signal_end)]
    scan_index = scan_index[::args.stride]

    seen = set()
    candidates = []
    bucket_observations = Counter()
    scan_errors = Counter()
    scan_count = 0

    for pos, bar_start in enumerate(scan_index, start=1):
        scan_time = bar_start + pd.Timedelta(minutes=15)
        frames_at = {}
        ticker_at = {}

        for symbol, frames in data.items():
            f15 = frames["15M"].loc[(frames["15M"].index + pd.Timedelta(minutes=15)) <= scan_time].tail(420)
            f1 = frames["1H"].loc[(frames["1H"].index + pd.Timedelta(hours=1)) <= scan_time].tail(420)
            f4 = frames["4H"].loc[(frames["4H"].index + pd.Timedelta(hours=4)) <= scan_time].tail(420)
            if min(len(f15), len(f1), len(f4)) < 360:
                continue
            ticker = historical_ticker(f15)
            if float(ticker.get("turnover_24h") or 0) < MIN_24H_TURNOVER_USDT:
                continue
            frames_at[symbol] = {"15M": f15, "1H": f1, "4H": f4}
            ticker_at[symbol] = ticker

        benchmark_items = {}
        for symbol in ("BTC_USDT", "ETH_USDT"):
            if symbol not in frames_at:
                continue
            try:
                benchmark_items[symbol] = analyze_symbol(
                    symbol,
                    frames_at[symbol],
                    ticker_at[symbol],
                    market_context=None,
                    calibration=None,
                )
            except Exception as exc:
                scan_errors[f"{symbol}:benchmark"] += 1

        market_context = derive_market_context(benchmark_items)
        results = []
        for symbol in selected:
            if symbol not in frames_at:
                continue
            try:
                if symbol in benchmark_items:
                    item = benchmark_items[symbol]
                else:
                    item = analyze_symbol(
                        symbol,
                        frames_at[symbol],
                        ticker_at[symbol],
                        market_context=market_context,
                        calibration=None,
                    )
                if item.get("bucket") != "IGNORE":
                    results.append(item)
            except Exception:
                scan_errors[symbol] += 1

        sort_results(results)
        apply_correlation_suppression(results, frames_at)
        for item in results:
            bucket_observations[item.get("bucket")] += 1
            if item.get("bucket") not in ("ENTRY_READY", "NEAR_ENTRY", "DEVELOPING"):
                continue
            sid = signal_id(item)
            if sid in seen:
                continue
            seen.add(sid)
            candidates.append(record_candidate(item, scan_time))
        scan_count += 1

        if pos % 250 == 0 or pos == len(scan_index):
            print(f"Replay {pos}/{len(scan_index)} scans | candidates={len(candidates)} | observations={dict(bucket_observations)}")

    evaluated = []
    for i, row in enumerate(candidates, start=1):
        frame = data[row["symbol"]]["15M"]
        evaluated.append(evaluate_candidate(row, frame))
        if i % 250 == 0:
            print(f"Evaluated {i}/{len(candidates)}")

    unsuppressed = [r for r in evaluated if not r.get("correlation_suppressed")]
    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "engine": "Market Setup Watch V3 current production logic",
        "days": args.days,
        "replay_stride_15m_bars": args.stride,
        "replay_interval_minutes": args.stride * 15,
        "signal_start_utc": signal_start.isoformat(),
        "signal_end_utc": signal_end.isoformat(),
        "survivorship_note": "Universe is selected using today's production crosslist/liquidity gates because historical ticker snapshots are unavailable.",
        "participation_note": "Historical OI/holdVol snapshots are unavailable; participation scoring is neutral (N/A).",
        "spread_note": "Historical bid/ask spread snapshots are unavailable; historical spread gate cannot be replayed.",
        "universe_requested": args.symbols,
        "universe_loaded": len(data),
        "universe": list(data.keys()),
        "failed_symbols": failed,
        "scan_count": scan_count,
        "bucket_observations": dict(bucket_observations),
        "all_actionable_candidates": metric_block(evaluated),
        "unsuppressed_actionable_candidates": metric_block(unsuppressed),
        "by_bucket_unsuppressed": {
            bucket: metric_block([r for r in unsuppressed if r["bucket"] == bucket])
            for bucket in ("ENTRY_READY", "NEAR_ENTRY", "DEVELOPING")
        },
        "by_direction_unsuppressed": {
            d: metric_block([r for r in unsuppressed if r["direction"] == d])
            for d in ("long", "short")
        },
    }

    symbol_rows = []
    for symbol in data:
        rows = [r for r in unsuppressed if r["symbol"] == symbol]
        if rows:
            m = metric_block(rows)
            m["symbol"] = symbol
            symbol_rows.append(m)
    symbol_rows.sort(key=lambda x: (x.get("expectancy_r") is not None, x.get("expectancy_r") or -999), reverse=True)
    summary["by_symbol_unsuppressed"] = symbol_rows

    (OUTDIR / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    pd.DataFrame(evaluated).to_csv(OUTDIR / "trades.csv", index=False)

    print("BACKTEST_SUMMARY_JSON_START")
    print(json.dumps(summary, indent=2))
    print("BACKTEST_SUMMARY_JSON_END")


if __name__ == "__main__":
    main()
