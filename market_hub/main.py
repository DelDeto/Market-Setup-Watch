import json
from datetime import datetime, timezone

from .calibration import build_calibration
from .chart import render_setup_chart
from .config import (
    DEEP_SCAN_SYMBOLS,
    FAST_SCAN_LIQUIDITY_RESERVE,
    FAST_SCAN_VOLATILITY_RESERVE,
    MAX_TELEGRAM_SETUPS,
    REPORT_PATH,
    STATE_PATH,
    TELEGRAM_HEARTBEAT_MINUTES,
)
from .correlation import apply_correlation_suppression
from .fast_scan import (
    score_fast_candidate,
    score_ticker_candidate,
    select_deep_scan_symbols,
)
from .market_context import derive_market_context
from .meta_selector import apply_top_pick_selector
from .mexc_market import (
    fetch_many_fast_frames,
    fetch_many_frames,
    get_all_tickers,
    get_contract_universe,
)
from .notifier import send_heartbeat, send_telegram
from .outcomes import (
    load_outcomes,
    register_candidates,
    save_outcomes,
    update_outcomes,
)
from .participation import apply_participation_context
from .scanner import analyze_symbol


BENCHMARK_SYMBOLS = ("BTC_USDT", "ETH_USDT")


def _load_state():
    if not STATE_PATH.exists():
        return {"signatures": [], "hold_vol_snapshot": {}}

    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"signatures": [], "hold_vol_snapshot": {}}
        data.setdefault("signatures", [])
        data.setdefault("hold_vol_snapshot", {})
        return data
    except Exception:
        return {"signatures": [], "hold_vol_snapshot": {}}


def _parse_utc(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _heartbeat_due(previous, now):
    last_notification = _parse_utc(previous.get("last_notification_utc"))
    if last_notification is None:
        return True
    elapsed_seconds = (now - last_notification).total_seconds()
    return elapsed_seconds >= TELEGRAM_HEARTBEAT_MINUTES * 60


def _alert_eligible(item):
    return (
        item.get("bucket") in (
            "ENTRY_READY",
            "NEAR_ENTRY",
            "DEVELOPING",
        )
        and not item.get("correlation_suppressed", False)
    )


def _signature(item):
    plan = item.get("trade_plan", {})
    entry = plan.get("entry_zone", {})
    return "|".join(
        str(value)
        for value in [
            item.get("symbol"),
            item.get("bucket"),
            item.get("direction"),
            item.get("mtf_alignment"),
            round(float(entry.get("lower") or 0), 8),
            round(float(entry.get("upper") or 0), 8),
            bool(plan.get("execution_ready")),
            item.get("top_pick_rank") or 0,
        ]
    )


def _should_notify(previous, setups):
    important = [item for item in setups if _alert_eligible(item)]
    if not important:
        return False

    previous_signatures = set(previous.get("signatures", []))
    current_signatures = {_signature(item) for item in important}

    if any(
        item.get("bucket") == "ENTRY_READY"
        and _signature(item) not in previous_signatures
        for item in important
    ):
        return True

    return current_signatures != previous_signatures


def _compact_for_state(setups):
    return [
        _signature(item)
        for item in setups
        if _alert_eligible(item)
    ]


def _sort_results(results):
    bucket_priority = {
        "ENTRY_READY": 0,
        "NEAR_ENTRY": 1,
        "DEVELOPING": 2,
        "WATCHLIST": 3,
    }
    results.sort(
        key=lambda item: (
            bucket_priority.get(item.get("bucket"), 9),
            -float(item.get("execution_score", 0)),
            -float(item.get("quality_score", item.get("score", 0))),
            float(
                item.get("entry_distance_atr")
                if item.get("entry_distance_atr") is not None
                else 99
            ),
        )
    )
    return results


def main():
    generated_dt = datetime.now(timezone.utc)
    generated_at = generated_dt.isoformat()
    previous = _load_state()

    mexc_universe = get_contract_universe()
    universe = list(mexc_universe)
    tickers = get_all_tickers()

    hold_vol_snapshot = apply_participation_context(
        tickers,
        previous_hold_vol=previous.get("hold_vol_snapshot", {}),
    )

    # Load the journal before candidate selection so any still-open historical
    # setup is forced into the deep-scan set and never loses monitoring.
    outcomes = load_outcomes()
    tracked_symbols = [
        row.get("symbol")
        for row in outcomes
        if (
            row.get("symbol") in universe
            and row.get("status") in ("PENDING_ENTRY", "ACTIVE")
        )
    ]

    # FAST STAGE: every tradable MEXC USDT perpetual gets a lightweight 1H
    # structural/momentum scan. No Binance, turnover, or spread pre-filter is
    # allowed to remove a symbol before this stage.
    fast_frames, fast_fetch_errors = fetch_many_fast_frames(universe)
    fast_rows = []
    fast_analysis_errors = {}
    fast_fallback_count = 0

    for symbol in universe:
        frame = fast_frames.get(symbol)
        ticker = tickers.get(symbol)

        if not ticker or ticker.get("last_price") is None:
            continue

        try:
            if frame is not None:
                fast_rows.append(
                    score_fast_candidate(
                        symbol,
                        frame,
                        ticker,
                    )
                )
            else:
                fast_rows.append(
                    score_ticker_candidate(
                        symbol,
                        ticker,
                    )
                )
                fast_fallback_count += 1
        except Exception as exc:
            fast_analysis_errors[symbol] = str(exc)

    scan_symbols = select_deep_scan_symbols(
        fast_rows,
        deep_limit=DEEP_SCAN_SYMBOLS,
        liquidity_reserve=FAST_SCAN_LIQUIDITY_RESERVE,
        volatility_reserve=FAST_SCAN_VOLATILITY_RESERVE,
        required_symbols=BENCHMARK_SYMBOLS + tuple(tracked_symbols),
    )

    # Required symbols are appended even if their fast-stage history was
    # insufficient, so benchmarks and live journal entries remain observable.
    for symbol in list(BENCHMARK_SYMBOLS) + tracked_symbols:
        if symbol in universe and symbol not in scan_symbols:
            scan_symbols.append(symbol)

    print(
        f"MEXC_universe={len(universe)} | "
        f"fast_scanned={len(fast_rows)} | "
        f"fast_fallback={fast_fallback_count} | "
        f"fast_errors={len(fast_fetch_errors) + len(fast_analysis_errors)} | "
        f"deep_scan={len(scan_symbols)}"
    )

    # DEEP STAGE: only selected candidates pay the cost of full 4H/1H/15M
    # PA/SMC analysis. If a selected symbol lacks enough history, automatically
    # backfill from the remaining fast-ranked universe until we have the
    # requested number of successful deep scans.
    frames_by_symbol, fetch_errors = fetch_many_frames(
        scan_symbols,
        workers=6,
    )

    attempted_symbols = set(scan_symbols)
    fallback_ranked = sorted(
        fast_rows,
        key=lambda row: (
            -float(row.get("fast_score", 0)),
            -float(row.get("opportunity_strength", 0)),
            -float(row.get("turnover_24h", 0)),
        ),
    )

    while len(frames_by_symbol) < DEEP_SCAN_SYMBOLS:
        needed = DEEP_SCAN_SYMBOLS - len(frames_by_symbol)
        fallback_symbols = [
            row["symbol"]
            for row in fallback_ranked
            if row["symbol"] not in attempted_symbols
        ][:max(needed * 2, 20)]

        if not fallback_symbols:
            break

        attempted_symbols.update(fallback_symbols)
        scan_symbols.extend(fallback_symbols)

        more_frames, more_errors = fetch_many_frames(
            fallback_symbols,
            workers=6,
        )
        frames_by_symbol.update(more_frames)
        fetch_errors.update(more_errors)

        if not more_frames and not fallback_symbols:
            break

    print(
        f"Deep_attempted={len(attempted_symbols)} | "
        f"deep_success={len(frames_by_symbol)} | "
        f"deep_errors={len(fetch_errors)}"
    )

    # Outcome journal is updated before calibration so newly resolved trades
    # immediately contribute to empirical statistics.
    outcomes = update_outcomes(outcomes, frames_by_symbol)
    calibration = build_calibration(outcomes)

    analysis_errors = {}
    benchmark_items = {}

    for symbol in BENCHMARK_SYMBOLS:
        frames = frames_by_symbol.get(symbol)
        if not frames:
            continue
        try:
            benchmark_items[symbol] = analyze_symbol(
                symbol,
                frames,
                tickers.get(symbol, {}),
                market_context=None,
                calibration=calibration,
            )
        except Exception as exc:
            analysis_errors[f"{symbol}:benchmark"] = str(exc)

    market_context = derive_market_context(benchmark_items)

    results = []
    for symbol in scan_symbols:
        frames = frames_by_symbol.get(symbol)
        if not frames:
            continue

        try:
            if symbol in benchmark_items:
                item = benchmark_items[symbol]
            else:
                item = analyze_symbol(
                    symbol,
                    frames,
                    tickers.get(symbol, {}),
                    market_context=market_context,
                    calibration=calibration,
                )

            if item.get("bucket") != "IGNORE":
                results.append(item)

        except Exception as exc:
            analysis_errors[symbol] = str(exc)

    _sort_results(results)
    apply_correlation_suppression(results, frames_by_symbol)
    top_picks = apply_top_pick_selector(results, fast_rows)

    counts = {
        bucket: sum(item.get("bucket") == bucket for item in results)
        for bucket in (
            "ENTRY_READY",
            "NEAR_ENTRY",
            "DEVELOPING",
            "WATCHLIST",
        )
    }

    alert_counts = {
        bucket: sum(
            item.get("bucket") == bucket
            and not item.get("correlation_suppressed", False)
            for item in results
        )
        for bucket in (
            "ENTRY_READY",
            "NEAR_ENTRY",
            "DEVELOPING",
            "WATCHLIST",
        )
    }

    suppressed_count = sum(
        bool(item.get("correlation_suppressed"))
        for item in results
    )

    # Register after correlation + meta selection so TOP PICK rank and the
    # fixed 2R objective are frozen into the forward journal.
    outcomes = register_candidates(outcomes, results, generated_at)
    save_outcomes(outcomes)

    closed_outcomes = [
        row for row in outcomes
        if row.get("outcome") in ("WIN", "LOSS")
    ]
    wins = sum(row.get("outcome") == "WIN" for row in closed_outcomes)
    losses_after_protect = sum(
        row.get("outcome") == "LOSS"
        and bool(
            (row.get("management") or {}).get(
                "protect_reached"
            )
        )
        for row in closed_outcomes
    )
    raw_realized_r = [
        (row.get("management") or {}).get("raw_realized_r")
        for row in closed_outcomes
        if (row.get("management") or {}).get("raw_realized_r")
        is not None
    ]
    selector_closed = [
        row for row in outcomes
        if (row.get("selector") or {}).get("outcome") in ("WIN", "LOSS")
    ]
    selector_wins = sum(
        (row.get("selector") or {}).get("outcome") == "WIN"
        for row in selector_closed
    )

    outcome_summary = {
        "tracked": len(outcomes),
        "closed_win_loss": len(closed_outcomes),
        "wins": wins,
        "losses": len(closed_outcomes) - wins,
        "win_rate": (
            wins / len(closed_outcomes)
            if closed_outcomes
            else None
        ),
        "losses_after_1r": losses_after_protect,
        "raw_realized_r_sum": (
            round(sum(float(value) for value in raw_realized_r), 3)
            if raw_realized_r
            else None
        ),
        "selector_2r_closed": len(selector_closed),
        "selector_2r_wins": selector_wins,
        "selector_2r_losses": len(selector_closed) - selector_wins,
        "selector_2r_win_rate": (
            selector_wins / len(selector_closed)
            if selector_closed else None
        ),
    }

    report = {
        "generated_at_utc": generated_at,
        "exchange": "MEXC",
        "market": "USDT perpetual futures",
        "engine": "PA-MTF Hybrid V4 whole-MEXC two-stage scanner",
        "mexc_universe_count": len(mexc_universe),
        "universe_count": len(universe),
        "fast_scan_attempted_count": len(universe),
        "fast_scan_count": len(fast_rows),
        "fast_scan_full_history_count": len(fast_frames),
        "fast_scan_fallback_count": fast_fallback_count,
        "fast_scan_error_count": (
            len(fast_fetch_errors) + len(fast_analysis_errors)
        ),
        "deep_scan_attempted_count": len(attempted_symbols),
        "deep_scan_count": len(frames_by_symbol),
        "full_scan_count": len(frames_by_symbol),
        "fast_scan_top": sorted(
            fast_rows,
            key=lambda row: (
                -float(row.get("fast_score", 0)),
                -float(row.get("turnover_24h", 0)),
            ),
        )[:100],
        "counts": counts,
        "alert_counts": alert_counts,
        "correlation_suppressed_count": suppressed_count,
        "market_context": market_context,
        "calibration": calibration,
        "outcome_summary": outcome_summary,
        "top_pick_count": len(top_picks),
        "top_pick_symbols": [item.get("symbol") for item in top_picks],
        "selector_target_r": 2.0,
        "setups": results,
        "prefilter_rejection_count": 0,
        "prefilter_rejections": {},
        "fast_fetch_errors": fast_fetch_errors,
        "fast_analysis_errors": fast_analysis_errors,
        "fetch_error_count": len(fetch_errors),
        "analysis_error_count": len(analysis_errors),
        "fetch_errors": fetch_errors,
        "analysis_errors": analysis_errors,
    }

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    should_notify = _should_notify(previous, results)
    heartbeat_due = _heartbeat_due(previous, generated_dt)

    chart_paths = []
    important = [
        item for item in results
        if _alert_eligible(item)
    ]
    important.sort(
        key=lambda item: (
            0 if item.get("top_pick_rank") else 1,
            item.get("top_pick_rank") or 99,
            -float(item.get("selector_score") or 0),
        )
    )
    important = important[:MAX_TELEGRAM_SETUPS]

    for item in important:
        symbol = item.get("symbol")
        frames = frames_by_symbol.get(symbol)
        if not frames:
            continue
        try:
            path = render_setup_chart(
                symbol,
                frames["15M"],
                item,
            )
            chart_paths.append(
                {
                    "symbol": symbol,
                    "bucket": item.get("bucket"),
                    "score": item.get("score"),
                    "direction": item.get("direction"),
                    "top_pick_rank": item.get("top_pick_rank"),
                    "selector_score": item.get("selector_score"),
                    "path": str(path),
                }
            )
        except Exception as exc:
            analysis_errors[f"{symbol}:chart"] = str(exc)

    report["charts"] = [
        {
            key: value
            for key, value in chart.items()
            if key != "path"
        }
        for chart in chart_paths
    ]
    report["analysis_error_count"] = len(analysis_errors)
    report["analysis_errors"] = analysis_errors

    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    notification_sent = False
    notification_kind = None

    if should_notify:
        notification_sent = send_telegram(
            report,
            chart_paths=chart_paths,
        )
        notification_kind = "setup_change"
    elif heartbeat_due:
        notification_sent = send_heartbeat(report)
        notification_kind = "heartbeat"
    else:
        print(
            "Market Setup Watch: no new unsuppressed "
            "READY/NEAR/DEVELOPING setup change and heartbeat not due; "
            "Telegram suppressed."
        )

    last_notification_utc = previous.get("last_notification_utc")
    if notification_sent:
        last_notification_utc = generated_at
        print(
            f"Telegram notification recorded: "
            f"{notification_kind} at {generated_at}"
        )

    STATE_PATH.write_text(
        json.dumps(
            {
                "updated_at_utc": generated_at,
                "last_notification_utc": last_notification_utc,
                "signatures": _compact_for_state(results),
                "counts": counts,
                "alert_counts": alert_counts,
                "hold_vol_snapshot": hold_vol_snapshot,
                "market_context": market_context,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(
        f"Market Setup Watch completed: "
        f"READY={counts['ENTRY_READY']} "
        f"NEAR={counts['NEAR_ENTRY']} "
        f"DEVELOPING={counts['DEVELOPING']} "
        f"WATCH={counts['WATCHLIST']} | "
        f"correlation_suppressed={suppressed_count} | "
        f"top_picks={len(top_picks)} | "
        f"calibration_active={calibration.get('active', False)} | "
        f"heartbeat_due={heartbeat_due}"
    )


if __name__ == "__main__":
    main()
