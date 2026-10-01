import os

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


def _fmt_signed(value):
    if value is None:
        return "-"
    value = int(value)
    return f"{value:+d}"


def build_text(report):
    rows = report.get("setups", [])[:MAX_TELEGRAM_SETUPS]
    counts = report.get("counts", {})

    lines = [
        "🔥 MARKET SETUP WATCH",
        "=" * 30,
        f"Scan UTC: {report.get('generated_at_utc')}",
        (
            f"Universe: {report.get('universe_count', 0)} | "
            f"Quality+Liquid: "
            f"{report.get('quality_liquid_universe_count', 0)} | "
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
            "Hiện chưa có setup đạt ngưỡng giữ lại.",
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
        breakdown = item.get("score_breakdown", {})
        filters = item.get("filters", {})
        htf = filters.get("htf_location", {})

        direction = (item.get("direction") or "-").upper()

        lines += [
            "",
            (
                f"{icons.get(item['bucket'], '•')} {index}. "
                f"{item['symbol']} · {direction} · "
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
                "Score: "
                f"Setup {_fmt_signed(breakdown.get('setup_completeness'))}, "
                f"Conf {_fmt_signed(breakdown.get('confirmed'))}, "
                f"Disp {_fmt_signed(breakdown.get('displacement'))}, "
                f"Struct {_fmt_signed(breakdown.get('structure'))}, "
                f"Retest {_fmt_signed(breakdown.get('retest'))}, "
                f"Sweep {_fmt_signed(breakdown.get('sweep'))}, "
                f"Zone {_fmt_signed(breakdown.get('zone_quality'))}, "
                f"MTF {_fmt_signed(breakdown.get('mtf_alignment'))}, "
                f"RR {_fmt_signed(breakdown.get('first_target_rr'))}, "
                f"HTF {_fmt_signed(breakdown.get('htf_location'))}"
            ),
        ]

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


def send_telegram(report):
    text = build_text(report)
    TEXT_PATH.parent.mkdir(parents=True, exist_ok=True)
    TEXT_PATH.write_text(text, encoding="utf-8")

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        print("Telegram skipped: missing secrets.")
        return False

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

    print(
        f"Market Setup Watch Telegram sent "
        f"({len(chunks)} message(s))."
    )
    return True
