import json
from datetime import datetime, timezone

from .config import (
    MAX_FULL_SCAN_SYMBOLS,
    MIN_24H_TURNOVER_USDT,
    REPORT_PATH,
    STATE_PATH,
)
from .mexc_market import (
    fetch_many_frames,
    get_all_tickers,
    get_contract_universe,
)
from .notifier import send_telegram
from .scanner import analyze_symbol


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


def _load_state():
    if not STATE_PATH.exists():
        return {"signatures": []}

    try:
        return json.loads(
            STATE_PATH.read_text(encoding="utf-8")
        )
    except Exception:
        return {"signatures": []}


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
    # Market Hub is event-driven: no Telegram spam when only watchlist
    # context exists and nothing actionable/developing changed.
    important = [
        item
        for item in setups
        if item.get("bucket") in ("ENTRY_READY", "DEVELOPING")
    ]

    if not important:
        return False

    previous_signatures = set(previous.get("signatures", []))
    current_signatures = {_signature(item) for item in important}

    # Always notify a newly READY setup.
    if any(
        item.get("bucket") == "ENTRY_READY"
        and _signature(item) not in previous_signatures
        for item in important
    ):
        return True

    # Notify meaningful candidate-set changes.
    return current_signatures != previous_signatures


def _compact_for_state(setups):
    return [
        _signature(item)
        for item in setups
        if item.get("bucket") in ("ENTRY_READY", "DEVELOPING")
    ]


def main():
    generated_at = datetime.now(timezone.utc).isoformat()

    universe = get_contract_universe()
    tickers = get_all_tickers()

    ranked_universe = []
    for symbol in universe:
        ticker = tickers.get(symbol)
        liquidity = _liquidity_value(ticker)

        if ticker is None or ticker.get("last_price") is None:
            continue

        if liquidity < MIN_24H_TURNOVER_USDT:
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

    print(
        f"Universe={len(universe)} | "
        f"liquid={len(ranked_universe)} | "
        f"full_scan={len(scan_symbols)}"
    )

    frames_by_symbol, fetch_errors = fetch_many_frames(
        scan_symbols,
        workers=6,
    )

    results = []
    analysis_errors = {}

    for symbol in scan_symbols:
        frames = frames_by_symbol.get(symbol)
        if not frames:
            continue

        try:
            item = analyze_symbol(
                symbol,
                frames,
                tickers.get(symbol, {}),
            )

            if item.get("bucket") != "IGNORE":
                results.append(item)

        except Exception as exc:
            analysis_errors[symbol] = str(exc)

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

    counts = {
        bucket: sum(item.get("bucket") == bucket for item in results)
        for bucket in ("ENTRY_READY", "DEVELOPING", "WATCHLIST")
    }

    report = {
        "generated_at_utc": generated_at,
        "exchange": "MEXC",
        "market": "USDT perpetual futures",
        "engine": "PA-MTF Hybrid V2 deterministic scanner",
        "universe_count": len(universe),
        "liquid_universe_count": len(ranked_universe),
        "full_scan_count": len(scan_symbols),
        "counts": counts,
        "setups": results,
        "fetch_error_count": len(fetch_errors),
        "analysis_error_count": len(analysis_errors),
        "fetch_errors": fetch_errors,
        "analysis_errors": analysis_errors,
    }

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    previous = _load_state()
    should_notify = _should_notify(previous, results)

    if should_notify:
        send_telegram(report)
    else:
        print(
            "Market Hub: no new READY/DEVELOPING setup change; "
            "Telegram suppressed."
        )

    STATE_PATH.write_text(
        json.dumps(
            {
                "updated_at_utc": generated_at,
                "signatures": _compact_for_state(results),
                "counts": counts,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(
        f"Market Hub completed: "
        f"READY={counts['ENTRY_READY']} "
        f"DEVELOPING={counts['DEVELOPING']} "
        f"WATCH={counts['WATCHLIST']}"
    )


if __name__ == "__main__":
    main()
