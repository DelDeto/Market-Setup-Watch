import os
from datetime import datetime, timedelta, timezone

import requests

from .config import MAX_TELEGRAM_SETUPS, TEXT_PATH


VN_TZ = timezone(timedelta(hours=7))

# Shared Telegram destination for Market Scan subscribers.
# Telegram chat IDs are routing identifiers, not bot credentials.
DEFAULT_GROUP_CHAT_ID = "-1003984243045"


def _fmt(value):
    if value is None:
        return "-"
    value = float(value)
    if abs(value) >= 1000:
        return f"{value:,.2f}"
    if abs(value) >= 1:
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return f"{value:.6f}".rstrip("0").rstrip(".")


def _fmt_signed(value):
    if value is None:
        return "-"
    value = int(value)
    return f"{value:+d}"


def _scan_time_vn(value):
    if not value:
        return "-"
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(VN_TZ).strftime("%d/%m/%Y %H:%M")
    except (TypeError, ValueError):
        return str(value)


def build_text(report):
    rows = [
        item
        for item in report.get("setups", [])
        if not item.get("correlation_suppressed", False)
    ][:MAX_TELEGRAM_SETUPS]
    counts = report.get("alert_counts") or report.get("counts", {})
    market_context = report.get("market_context", {})
    calibration = report.get("calibration", {})
    outcomes = report.get("outcome_summary", {})

    lines = [
        "🔥 MARKET SETUP WATCH",
        "=" * 30,
        f"Scan VN: {_scan_time_vn(report.get('generated_at_utc'))}",
        (
            f"Universe: {report.get('universe_count', 0)} | "
            f"Quality+Liquid: "
            f"{report.get('quality_liquid_universe_count', 0)} | "
            f"Full PA/SMC: {report.get('full_scan_count', 0)}"
        ),
        (
            "READY "
            f"{counts.get('ENTRY_READY', 0)} | "
            "NEAR "
            f"{counts.get('NEAR_ENTRY', 0)} | "
            "DEVELOPING "
            f"{counts.get('DEVELOPING', 0)} | "
            "WATCH "
            f"{counts.get('WATCHLIST', 0)}"
        ),
        (
            f"Market: {market_context.get('regime', 'MIXED')} | "
            f"BTC {market_context.get('btc_bias', 'UNKNOWN')} | "
            f"ETH {market_context.get('eth_bias', 'UNKNOWN')}"
        ),
        (
            f"Adaptive: {'ON' if calibration.get('active') else 'OFF'} "
            f"({calibration.get('closed_samples', 0)} closed) | "
            f"Tracked outcomes: {outcomes.get('tracked', 0)}"
        ),
        (
            f"Correlation suppressed: "
            f"{report.get('correlation_suppressed_count', 0)}"
        ),
    ]

    if not rows:
        lines += [
            "",
            "Hiện chưa có setup đạt ngưỡng giữ lại.",
        ]
        return "\n".join(lines)

    icons = {
        "ENTRY_READY": "🔥",
        "NEAR_ENTRY": "🎯",
        "DEVELOPING": "⚡",
        "WATCHLIST": "👀",
    }

    for index, item in enumerate(rows, start=1):
        plan = item.get("trade_plan", {})
        entry = plan.get("entry_zone", {})
        targets = plan.get("targets", [])
        setup = item.get("analysis_15m", {}).get("setup", {})
        breakdown = item.get("score_breakdown", {})
        execution_breakdown = item.get("execution_breakdown", {})
        filters = item.get("filters", {})
        htf = filters.get("htf_location", {})

        direction = (item.get("direction") or "-").upper()

        lines += [
            "",
            (
                f"{icons.get(item['bucket'], '•')} {index}. "
                f"{item['symbol']} · {direction} · "
                f"Q{item.get('quality_score', item.get('score', 0))}/100 · "
                f"E{item.get('execution_score', 0)}/100"
            ),
            (
                f"{item['bucket']} | MTF {item['mtf_alignment']} | "
                f"15M {setup.get('score', 0)}/4"
            ),
            (
                f"Regime: 4H {item['regime_4h']} | "
                f"1H {item['regime_1h']} | "
                f"15M {item['regime_15m']}"
            ),
            (
                f"Entry: {_fmt(entry.get('lower'))} - "
                f"{_fmt(entry.get('upper'))} "
                f"[{entry.get('source', '-')}]"
            ),
            f"SL: {_fmt(plan.get('stop_loss'))}",
        ]

        for target in targets[:3]:
            rr = target.get("rr")
            rr_text = f"{rr:.2f}R" if rr is not None else "-"
            lines.append(
                f"{target.get('name')}: {_fmt(target.get('price'))} "
                f"[{target.get('source')}, {rr_text}]"
            )

        atr_pct = filters.get("atr_pct")
        atr_text = f"{atr_pct:.2f}%" if atr_pct is not None else "-"
        distance = item.get("entry_distance_atr")
        distance_text = f"{distance:.2f} ATR" if distance is not None else "-"

        lines += [
            (
                f"Filters: RRdev={'Y' if filters.get('rr_developing_ok') else 'N'} | "
                f"RRready={'Y' if filters.get('rr_ready_ok') else 'N'} | "
                f"Vol={'Y' if filters.get('volatility_ok') else 'N'} "
                f"({atr_text}) | HTF={htf.get('label', '-')}"
            ),
            f"Entry distance: {distance_text}",
            (
                "Quality: "
                f"Setup {_fmt_signed(breakdown.get('setup_completeness'))}, "
                f"Conf {_fmt_signed(breakdown.get('confirmed'))}, "
                f"Disp {_fmt_signed(breakdown.get('displacement'))}, "
                f"Struct {_fmt_signed(breakdown.get('structure'))}, "
                f"Retest {_fmt_signed(breakdown.get('retest'))}, "
                f"Sweep {_fmt_signed(breakdown.get('sweep'))}, "
                f"Zone {_fmt_signed(breakdown.get('zone_quality'))}, "
                f"MTF {_fmt_signed(breakdown.get('mtf_alignment'))}, "
                f"RR {_fmt_signed(breakdown.get('first_target_rr'))}, "
                f"HTF {_fmt_signed(breakdown.get('htf_location'))}, "
                f"OI {_fmt_signed(breakdown.get('participation'))}, "
                f"Mkt {_fmt_signed(breakdown.get('market_context'))}, "
                f"Adapt {_fmt_signed(breakdown.get('adaptive'))}"
            ),
            (
                "Execution: "
                f"Prox {_fmt_signed(execution_breakdown.get('entry_proximity'))}, "
                f"RR {_fmt_signed(execution_breakdown.get('first_target_rr'))}, "
                f"Ready {_fmt_signed(execution_breakdown.get('plan_ready'))}, "
                f"Zone {_fmt_signed(execution_breakdown.get('entry_zone'))}, "
                f"Struct {_fmt_signed(execution_breakdown.get('structure'))}, "
                f"Disp {_fmt_signed(execution_breakdown.get('displacement'))}, "
                f"Retest {_fmt_signed(execution_breakdown.get('retest'))}, "
                f"Sweep {_fmt_signed(execution_breakdown.get('sweep'))}"
            ),
        ]

        participation = filters.get("participation") or {}
        lines.append(
            f"Participation: {participation.get('regime', 'N/A')} | "
            f"HoldVol Δ "
            f"{_fmt(participation.get('hold_vol_change_pct'))}%"
        )

        management = plan.get("management") or {}
        if management:
            lines.append(
                "Manage: "
                f"+{_fmt(management.get('protect_at_r'))}R→BE | "
                f"+{_fmt(management.get('partial_at_r'))}R→protect/partial | "
                f"+{_fmt(management.get('trail_at_r'))}R→trail 15M"
            )

        blockers = list(plan.get("blockers") or [])
        if filters.get("volatility_ok") is False:
            blockers.append("15M volatility outside allowed ATR% band")
        if htf.get("blocked"):
            blockers.append("Entry too close to opposing 1H/4H zone")
        if filters.get("rr_developing_ok") is False:
            blockers.append("First target RR below developing threshold")

        if blockers:
            lines.append("Blocker: " + "; ".join(blockers[:3]))

    return "\n".join(lines)


def build_heartbeat_text(report):
    counts = report.get("alert_counts") or report.get("counts", {})
    market_context = report.get("market_context", {})
    actionable = [
        item
        for item in report.get("setups", [])
        if (
            item.get("bucket") in (
                "ENTRY_READY",
                "NEAR_ENTRY",
                "DEVELOPING",
            )
            and not item.get("correlation_suppressed", False)
        )
    ][:3]

    lines = [
        "🛰 MARKET SETUP WATCH — HEARTBEAT",
        "Scanner: ✅ ONLINE",
        f"Scan VN: {_scan_time_vn(report.get('generated_at_utc'))}",
        (
            f"Universe {report.get('universe_count', 0)} | "
            f"Quality+Liquid {report.get('quality_liquid_universe_count', 0)} | "
            f"Deep scan {report.get('full_scan_count', 0)}"
        ),
        (
            f"🔥 READY {counts.get('ENTRY_READY', 0)} | "
            f"🎯 NEAR {counts.get('NEAR_ENTRY', 0)} | "
            f"⚡ DEVELOPING {counts.get('DEVELOPING', 0)} | "
            f"👀 WATCH {counts.get('WATCHLIST', 0)}"
        ),
        (
            f"Market {market_context.get('regime', 'MIXED')} | "
            f"BTC {market_context.get('btc_bias', 'UNKNOWN')} | "
            f"ETH {market_context.get('eth_bias', 'UNKNOWN')}"
        ),
    ]

    if actionable:
        lines.append("")
        lines.append("Top actionable hiện tại:")
        for item in actionable:
            plan = item.get("trade_plan", {})
            targets = plan.get("targets") or []
            first_rr = targets[0].get("rr") if targets else None
            rr_text = f"{first_rr:.2f}R" if first_rr is not None else "-"
            lines.append(
                f"• {item.get('symbol')} "
                f"{(item.get('direction') or '-').upper()} | "
                f"{item.get('bucket')} | "
                f"Q{item.get('quality_score', item.get('score', 0))} "
                f"E{item.get('execution_score', 0)} | TP1 {rr_text}"
            )
    else:
        lines += [
            "",
            "Không có READY/NEAR/DEVELOPING mới cần cảnh báo.",
        ]

    lines += [
        "",
        "Heartbeat này xác nhận scanner vẫn đang hoạt động.",
    ]
    return "\n".join(lines)


def _split_text(text, max_chars=3800):
    if len(text) <= max_chars:
        return [text]

    chunks = []
    current = []

    for block in text.split("\n\n"):
        candidate = "\n\n".join(current + [block])
        if len(candidate) <= max_chars:
            current.append(block)
            continue

        if current:
            chunks.append("\n\n".join(current))
            current = []

        if len(block) <= max_chars:
            current = [block]
        else:
            start = 0
            while start < len(block):
                chunks.append(block[start:start + max_chars])
                start += max_chars

    if current:
        chunks.append("\n\n".join(current))

    return chunks


def _credentials():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    personal_chat_id = os.getenv("TELEGRAM_CHAT_ID")
    group_chat_id = os.getenv("TELEGRAM_GROUP_CHAT_ID", DEFAULT_GROUP_CHAT_ID)

    if not token:
        print("Telegram skipped: missing TELEGRAM_BOT_TOKEN.")
        return None, []

    # Keep the existing personal destination as backup and also publish to
    # the shared group. Deduplicate IDs so the same destination is never
    # notified twice.
    chat_ids = []
    for chat_id in (personal_chat_id, group_chat_id):
        if chat_id and chat_id not in chat_ids:
            chat_ids.append(chat_id)

    if not chat_ids:
        print("Telegram skipped: no destinations configured.")
        return None, []

    return token, chat_ids


def _send_text(token, chat_id, text):
    chunks = _split_text(text)

    for index, chunk in enumerate(chunks, start=1):
        if len(chunks) > 1:
            chunk = f"[{index}/{len(chunks)}]\n" + chunk

        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": chunk,
                "disable_web_page_preview": True,
            },
            timeout=20,
        )

        if response.status_code != 200:
            raise RuntimeError(
                f"Telegram send failed: HTTP {response.status_code} "
                f"{response.text[:500]}"
            )

    return len(chunks)


def _send_photo(token, chat_id, chart):
    path = chart.get("path")
    if not path:
        return

    symbol = chart.get("symbol", "-")
    bucket = chart.get("bucket", "-")
    score = chart.get("score", "-")
    direction = (chart.get("direction") or "-").upper()
    caption = f"{symbol} | {bucket} | {direction} | Q-score {score}/100 | 15M"

    with open(path, "rb") as handle:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendPhoto",
            data={
                "chat_id": chat_id,
                "caption": caption,
            },
            files={"photo": handle},
            timeout=30,
        )

    if response.status_code != 200:
        raise RuntimeError(
            f"Telegram chart send failed for {symbol}: "
            f"HTTP {response.status_code} {response.text[:500]}"
        )


def send_heartbeat(report):
    token, chat_ids = _credentials()
    if not token or not chat_ids:
        return False

    text = build_heartbeat_text(report)
    chunk_count = 0
    for chat_id in chat_ids:
        chunk_count += _send_text(token, chat_id, text)
    print(
        f"Market Setup Watch heartbeat sent to {len(chat_ids)} destination(s) "
        f"({chunk_count} text message(s), 0 chart(s))."
    )
    return True


def send_telegram(report, chart_paths=None):
    text = build_text(report)
    TEXT_PATH.parent.mkdir(parents=True, exist_ok=True)
    TEXT_PATH.write_text(text, encoding="utf-8")

    token, chat_ids = _credentials()
    if not token or not chat_ids:
        return False

    chart_paths = chart_paths or []
    chunk_count = 0
    chart_count = 0
    for chat_id in chat_ids:
        chunk_count += _send_text(token, chat_id, text)
        for chart in chart_paths:
            _send_photo(token, chat_id, chart)
            chart_count += 1

    print(
        f"Market Setup Watch Telegram sent to {len(chat_ids)} destination(s) "
        f"({chunk_count} text message(s), "
        f"{chart_count} chart(s))."
    )
    return True
