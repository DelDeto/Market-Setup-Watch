import argparse
import json
from bisect import bisect_right
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from backtest_90d import (
    MIN_24H_TURNOVER_USDT,
    aggregate,
    evaluate_candidate,
    fetch_15m_range,
    historical_ticker,
    metric_block,
    record_candidate,
    select_current_universe,
    signal_id,
    sort_results,
)
from market_hub.correlation import apply_correlation_suppression
from market_hub.market_context import derive_market_context
from market_hub.scanner import analyze_symbol
from smc_analysis import (
    _atr,
    _find_displacements,
    _find_retests,
    _find_sweeps,
    _structure_events,
    _swing_masks,
    analyze_smc,
)

OUTDIR = Path("output/backtest_90d_accel")
OUTDIR.mkdir(parents=True, exist_ok=True)


def precompute_execution_events(frame):
    atr = _atr(frame)
    high_mask, low_mask = _swing_masks(frame, window=2)
    structure = _structure_events(frame, high_mask, low_mask, window=2)
    sweeps = _find_sweeps(frame, high_mask, low_mask, window=2)
    displacements = _find_displacements(frame, atr)
    retests = _find_retests(frame, structure, atr)
    return {
        "structure": structure,
        "sweeps": sweeps,
        "displacements": displacements,
        "retests": retests,
    }


def _last_recent(events, current_index, bars, direction=None):
    # Historical precompute contains future events, so enforce event index <= now.
    best = None
    floor = current_index - bars
    for item in reversed(events):
        idx = int(item["index"])
        if idx > current_index:
            continue
        if idx < floor:
            break
        if direction is None or item.get("direction") == direction:
            best = item
            break
    return best


def causal_setup(events, current_index, direction):
    opposite = "bearish" if direction == "bullish" else "bullish"
    latest_opposite = _last_recent(events["structure"], current_index, 20, opposite)
    cutoff = int(latest_opposite["index"]) if latest_opposite else -1

    def after_cutoff(key, bars):
        item = _last_recent(events[key], current_index, bars, direction)
        if item is not None and int(item["index"]) <= cutoff:
            return None
        return item

    sweep = after_cutoff("sweeps", 20)
    displacement = after_cutoff("displacements", 12)
    structure = after_cutoff("structure", 12)
    retest = after_cutoff("retests", 8)
    items = [sweep, displacement, structure, retest]
    return {
        "score": sum(x is not None for x in items),
        "structure": structure,
        "latest_index": max([int(x["index"]) for x in items if x is not None], default=-1),
    }


def should_deep_analyze(events, current_index):
    # Exact actionable states require an active 15M setup (>=2 signals) and a
    # recent structure event. This first branch mirrors that necessary gate.
    bull = causal_setup(events, current_index, "bullish")
    bear = causal_setup(events, current_index, "bearish")
    if (bull["score"] >= 2 and bull["structure"]) or (bear["score"] >= 2 and bear["structure"]):
        return True

    # Inclusive guardrail for rolling-420-window boundary differences: allow a
    # wider causal event envelope. This creates extra deep analyses, not fewer.
    recent_structure = _last_recent(events["structure"], current_index, 20, None)
    if recent_structure is None:
        return False
    for key in ("sweeps", "displacements", "retests"):
        if _last_recent(events[key], current_index, 30, None) is not None:
            return True
    return False


def slice_frames(frames, scan_time):
    f15 = frames["15M"].loc[(frames["15M"].index + pd.Timedelta(minutes=15)) <= scan_time].tail(420)
    f1 = frames["1H"].loc[(frames["1H"].index + pd.Timedelta(hours=1)) <= scan_time].tail(420)
    f4 = frames["4H"].loc[(frames["4H"].index + pd.Timedelta(hours=4)) <= scan_time].tail(420)
    if min(len(f15), len(f1), len(f4)) < 360:
        return None
    return {"15M": f15, "1H": f1, "4H": f4}


def benchmark_context(data, scan_time, cache):
    bframes = {}
    key_parts = []
    for symbol in ("BTC_USDT", "ETH_USDT"):
        frames = slice_frames(data[symbol], scan_time)
        if frames is None:
            return {"regime": "MIXED", "confidence": "LOW", "btc_bias": "UNKNOWN", "eth_bias": "UNKNOWN"}
        bframes[symbol] = frames
        key_parts.extend([frames["1H"].index[-1].isoformat(), frames["4H"].index[-1].isoformat()])
    key = tuple(key_parts)
    if key in cache:
        return cache[key]

    items = {}
    for symbol, frames in bframes.items():
        items[symbol] = {
            "analysis_1h": analyze_smc(frames["1H"], timeframe="1H"),
            "analysis_4h": analyze_smc(frames["4H"], timeframe="4H"),
        }
    context = derive_market_context(items)
    cache[key] = context
    return context


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--symbols", type=int, default=20)
    ap.add_argument("--stride", type=int, default=8)
    args = ap.parse_args()

    now = pd.Timestamp.now(tz="UTC").floor("15min")
    signal_end = now - pd.Timedelta(days=2)
    signal_start = signal_end - pd.Timedelta(days=args.days)
    history_start = signal_start - pd.Timedelta(days=72)

    selected, live_tickers, cross_meta, cross_count, quality_count = select_current_universe(args.symbols)
    print(f"ACCEL universe={len(selected)} crosslisted={cross_count} quality_now={quality_count}", flush=True)
    print("Universe:", ",".join(selected), flush=True)
    print(f"Signals {signal_start} -> {signal_end}; stride={args.stride} ({args.stride*15}m)", flush=True)

    data = {}
    events = {}
    failed = {}
    for i, symbol in enumerate(selected, 1):
        try:
            frame15 = fetch_15m_range(symbol, history_start, now)
            data[symbol] = {"15M": frame15, "1H": aggregate(frame15, "1h"), "4H": aggregate(frame15, "4h")}
            events[symbol] = precompute_execution_events(frame15)
            print(
                f"[{i}/{len(selected)}] {symbol} bars={len(frame15)} "
                f"struct={len(events[symbol]['structure'])} disp={len(events[symbol]['displacements'])}",
                flush=True,
            )
        except Exception as exc:
            failed[symbol] = str(exc)
            print(f"FAIL {symbol}: {exc}", flush=True)

    if "BTC_USDT" not in data or "ETH_USDT" not in data:
        raise RuntimeError("BTC/ETH unavailable")

    scan_index = data["BTC_USDT"]["15M"].index
    scan_index = scan_index[
        ((scan_index + pd.Timedelta(minutes=15)) >= signal_start)
        & ((scan_index + pd.Timedelta(minutes=15)) <= signal_end)
    ][::args.stride]

    seen = set()
    candidates = []
    context_cache = {}
    deep_calls = 0
    gate_hits = 0
    bucket_observations = Counter()

    for pos, bar_start in enumerate(scan_index, 1):
        scan_time = bar_start + pd.Timedelta(minutes=15)
        gated_symbols = []
        frames_at = {}
        ticker_at = {}

        for symbol in selected:
            if symbol not in data:
                continue
            idx = data[symbol]["15M"].index.get_indexer([bar_start], method="pad")[0]
            if idx < 0 or not should_deep_analyze(events[symbol], int(idx)):
                continue
            frames = slice_frames(data[symbol], scan_time)
            if frames is None:
                continue
            ticker = historical_ticker(frames["15M"])
            if float(ticker.get("turnover_24h") or 0) < MIN_24H_TURNOVER_USDT:
                continue
            gated_symbols.append(symbol)
            frames_at[symbol] = frames
            ticker_at[symbol] = ticker

        if not gated_symbols:
            continue

        gate_hits += len(gated_symbols)
        context = benchmark_context(data, scan_time, context_cache)
        results = []
        for symbol in gated_symbols:
            try:
                item = analyze_symbol(
                    symbol,
                    frames_at[symbol],
                    ticker_at[symbol],
                    market_context=None if symbol in ("BTC_USDT", "ETH_USDT") else context,
                    calibration=None,
                )
                deep_calls += 1
                if item.get("bucket") != "IGNORE":
                    results.append(item)
            except Exception as exc:
                print(f"ANALYSIS_FAIL {symbol} {scan_time}: {exc}", flush=True)

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

        if pos % 100 == 0:
            print(
                f"Replay {pos}/{len(scan_index)} gate_hits={gate_hits} deep={deep_calls} "
                f"candidates={len(candidates)} buckets={dict(bucket_observations)} contexts={len(context_cache)}",
                flush=True,
            )
            (OUTDIR / "progress.json").write_text(
                json.dumps({
                    "pos": pos,
                    "total": len(scan_index),
                    "gate_hits": gate_hits,
                    "deep_calls": deep_calls,
                    "candidate_count": len(candidates),
                    "bucket_observations": dict(bucket_observations),
                }, indent=2),
                encoding="utf-8",
            )

    evaluated = []
    for i, row in enumerate(candidates, 1):
        evaluated.append(evaluate_candidate(row, data[row["symbol"]]["15M"]))
        if i % 250 == 0:
            print(f"Outcome {i}/{len(candidates)}", flush=True)

    unsuppressed = [r for r in evaluated if not r.get("correlation_suppressed")]
    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "engine": "Market Setup Watch V3 - accelerated causal event gate + unchanged deep analysis",
        "days": args.days,
        "replay_stride_15m_bars": args.stride,
        "replay_interval_minutes": args.stride * 15,
        "signal_start_utc": signal_start.isoformat(),
        "signal_end_utc": signal_end.isoformat(),
        "universe_requested": args.symbols,
        "universe_loaded": len(data),
        "universe": list(data.keys()),
        "failed_symbols": failed,
        "gate_hits": gate_hits,
        "deep_analysis_calls": deep_calls,
        "market_context_snapshots": len(context_cache),
        "bucket_observations": dict(bucket_observations),
        "all_actionable_candidates": metric_block(evaluated),
        "unsuppressed_actionable_candidates": metric_block(unsuppressed),
        "by_bucket_unsuppressed": {
            b: metric_block([r for r in unsuppressed if r["bucket"] == b])
            for b in ("ENTRY_READY", "NEAR_ENTRY", "DEVELOPING")
        },
        "by_direction_unsuppressed": {
            d: metric_block([r for r in unsuppressed if r["direction"] == d])
            for d in ("long", "short")
        },
        "limitations": [
            "Universe uses today's Binance spot+futures crosslist/current liquidity ranking (survivorship bias).",
            "Historical bid/ask spread snapshots unavailable; spread gate cannot be replayed.",
            "Historical OI/holdVol snapshots unavailable; participation score is neutral.",
            "Replay is sampled at the configured stride; deep V3 analysis itself is unchanged.",
            "Accelerator uses an inclusive causal 15M event gate before expensive deep analysis; it is designed to over-include candidate states.",
        ],
    }

    by_symbol = []
    for symbol in data:
        rows = [r for r in unsuppressed if r["symbol"] == symbol]
        if rows:
            m = metric_block(rows)
            m["symbol"] = symbol
            by_symbol.append(m)
    by_symbol.sort(key=lambda x: (x.get("expectancy_r") is not None, x.get("expectancy_r") or -999), reverse=True)
    summary["by_symbol_unsuppressed"] = by_symbol

    (OUTDIR / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    pd.DataFrame(evaluated).to_csv(OUTDIR / "trades.csv", index=False)
    print("BACKTEST_SUMMARY_JSON_START", flush=True)
    print(json.dumps(summary, indent=2), flush=True)
    print("BACKTEST_SUMMARY_JSON_END", flush=True)


if __name__ == "__main__":
    main()
