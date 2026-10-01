import json
import os
from pathlib import Path

import requests

from .config import MAX_TELEGRAM_SETUPS, TEXT_PATH


def _fmt(value):
    if value is None:
        return "-"
    value = float(value)
    if abs(value) >= 1000:
        return f"{value:,.2f}"
    if abs(value) >= 1:
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return f"{value:.6f}".rstrip("0").rstrip(".")


def build_text(report):
    rows = report.get("setups", [])[:MAX_TELEGRAM_SETUPS]
    counts = report.get("counts", {})

    lines = [
        "🔥 CRYPTO MARKET SETUP HUB",
        "=" * 34,
        f"Scan UTC: {report.get('generated_at_utc')}",
        (
            f"Universe: {report.get('universe_count', 0)} | "
            f"Full PA/SMC: {report.get('full_scan_count', 0)}"
        ),
        (
            "READY "
            f"{counts.get('ENTRY_READY', 0)} | "
            "DEVELOPING "
            f"{counts.get('DEVELOPING', 0)} | "
            "WATCH "
            f"{counts.get('WATCHLIST', 0)}"
        ),
    ]

    if not rows:
        lines += [
            "",
            "Hiện chưa có setup đạt ngưỡng gửi cảnh báo.",
        ]
        return "\n".join(lines)

    icons = {
        "ENTRY_READY": "🔥",
        "DEVELOPING": "⚡",
        "WATCHLIST": "👀",
    }

    for index, item in enumerate(rows, start=1):
        plan = item.get("trade_plan", {})
        entry = plan.get("entry_zone", {})
        targets = plan.get("targets", [])
        setup = item.get("analysis_15m", {}).get("setup", {})

        lines += [
            "",
            (
                f"{icons.get(item['bucket'], '•')} {index}. "
                f"{item['symbol']} · {item['direction'].upper()} · "
                f"{item['score']}/100"
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

        if plan.get("blockers"):
            lines.append("Blocker: " + "; ".join(plan["blockers"][:2]))

    return "\n".join(lines)


def send_telegram(report):
    text = build_text(report)
    TEXT_PATH.parent.mkdir(parents=True, exist_ok=True)
    TEXT_PATH.write_text(text, encoding="utf-8")

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        print("Telegram skipped: missing secrets.")
        return False

    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        },
        timeout=20,
    )

    if response.status_code != 200:
        raise RuntimeError(
            f"Telegram send failed: HTTP {response.status_code} "
            f"{response.text[:500]}"
        )

    print("Market Hub Telegram sent.")
    return True
