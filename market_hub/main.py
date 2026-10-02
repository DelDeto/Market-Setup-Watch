import json
from datetime import datetime, timezone

from .binance_crosslist import get_binance_crosslisted_bases, mexc_underlying
from .calibration import build_calibration
from .chart import render_setup_chart
from .config import (
    MAX_FULL_SCAN_SYMBOLS,
    MAX_SPREAD_BPS,
    MIN_24H_TURNOVER_USDT,
    REPORT_PATH,
    STATE_PATH,
    TELEGRAM_HEARTBEAT_MINUTES,
)
from .correlation import apply_correlation_suppression
from .market_context import derive_market_context
from .mexc_market import (
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


def _liquidity_value(ticker):
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


def _passes_market_quality(ticker):
    if not ticker:
        return False, "missing_ticker"

    spread_bps = ticker.get("spread_bps")
    if spread_bps is not None and spread_bps > MAX_SPREAD_BPS:
        return False, f"spread>{MAX_SPREAD_BPS:.0f}bps"

    return True, None


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
        item.get("bucket") in ("ENTRY_READY", "DEVELOPING")
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
        "DEVELOPING": 1,
        "WATCHLIST": 2,
    }
    results.sort(
        key=lambda item: (
            bucket_priority.get(item.get("bucket"), 9),
            -float(item.get("score", 0)),
        )
    )
    return results


def main():
    generated_dt = datetime.now(timezone.utc)
    generated_at = generated_dt.isoformat()
    previous = _load_state()

    mexc_universe = get_contract_universe()
    crosslisted_bases, crosslist_meta = get_binance_crosslisted_bases()

    if crosslisted_bases is not None:
        universe = [
            symbol
            for symbol in mexc_universe
            if mexc_underlying(symbol) in crosslisted_bases
        ]
    else:
        universe = list(mexc_universe)

    crosslist_rejection_count = len(mexc_universe) - len(universe)
    tickers = get_all_tickers()

    hold_vol_snapshot = apply_participation_context(
        tickers,
        previous_hold_vol=previous.get("hold_vol_snapshot", {}),
    )

    ranked_universe = []
    prefilter_rejections = {}

    for symbol in universe:
        ticker = tickers.get(symbol)
        liquidity = _liquidity_value(ticker)

        if ticker is None or ticker.get("last_price") is None:
            prefilter_rejections[symbol] = "missing_live_price"
            continue

        if liquidity < MIN_24H_TURNOVER_USDT:
            prefilter_rejections[symbol] = "low_turnover"
            continue

        quality_ok, quality_reason = _passes_market_quality(ticker)
        if not quality_ok:
            prefilter_rejections[symbol] = quality_reason
            continue

        ranked_universe.append((symbol, liquidity))

    ranked_universe.sort(
        key=lambda item: item[1],
        reverse=True,
    )

    scan_symbols = [
        symbol
        for symbol, _ in ranked_universe[:MAX_FULL_SCAN_SYMBOLS]
    ]

    # Benchmarks are always fetched so altcoin scoring can use BTC/ETH regime.
    for symbol in BENCHMARK_SYMBOLS:
        if symbol in universe and symbol not in scan_symbols:
            scan_symbols.append(symbol)

    print(
        f"MEXC_universe={len(mexc_universe)} | "
        f"binance_crosslisted={len(universe)} | "
        f"quality_liquid={len(ranked_universe)} | "
        f"full_scan={len(scan_symbols)}"
    )

    frames_by_symbol, fetch_errors = fetch_many_frames(
        scan_symbols,
        workers=6,
    )

    # Outcome journal is updated before calibration so newly resolved trades
    # immediately contribute to empirical statistics.
    outcomes = load_outcomes()
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

    counts = {
        bucket: sum(item.get("bucket") == bucket for item in results)
        for bucket in ("ENTRY_READY", "DEVELOPING", "WATCHLIST")
    }

    alert_counts = {
        bucket: sum(
            item.get("bucket") == bucket
            and not item.get("correlation_suppressed", False)
            for item in results
        )
        for bucket in ("ENTRY_READY", "DEVELOPING", "WATCHLIST")
    }

    suppressed_count = sum(
        bool(item.get("correlation_suppressed"))
        for item in results
    )

    # Register this run after suppression so the journal records whether a
    # valid setup was held back only because it duplicated another thesis.
    outcomes = register_candidates(outcomes, results, generated_at)
    save_outcomes(outcomes)

    closed_outcomes = [
        row for row in outcomes
        if row.get("outcome") in ("WIN", "LOSS")
    ]
    wins = sum(row.get("outcome") == "WIN" for row in closed_outcomes)
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
    }

    report = {
        "generated_at_utc": generated_at,
        "exchange": "MEXC",
        "market": "USDT perpetual futures",
        "engine": "PA-MTF Hybrid V2 deterministic scanner",
        "mexc_universe_count": len(mexc_universe),
        "universe_count": len(universe),
        "binance_crosslist_rejection_count": crosslist_rejection_count,
        "binance_crosslist": crosslist_meta,
        "quality_liquid_universe_count": len(ranked_universe),
        "full_scan_count": len(scan_symbols),
        "counts": counts,
        "alert_counts": alert_counts,
        "correlation_suppressed_count": suppressed_count,
        "market_context": market_context,
        "calibration": calibration,
        "outcome_summary": outcome_summary,
        "setups": results,
        "prefilter_rejection_count": len(prefilter_rejections),
        "prefilter_rejections": prefilter_rejections,
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
    important = [item for item in results if _alert_eligible(item)]

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
            "READY/DEVELOPING setup change and heartbeat not due; "
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
        f"DEVELOPING={counts['DEVELOPING']} "
        f"WATCH={counts['WATCHLIST']} | "
        f"correlation_suppressed={suppressed_count} | "
        f"calibration_active={calibration.get('active', False)} | "
        f"heartbeat_due={heartbeat_due}"
    )


if __name__ == "__main__":
    main()
