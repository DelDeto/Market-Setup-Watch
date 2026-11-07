#!/usr/bin/env python3
"""Record *confirmed Telegram-delivered* setup references in ATLAS.

GitHub Actions OIDC signs the request. No exchange orders are placed.
Heartbeat mentions and unready setups are journaled, never simulated as trades.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import urllib.parse
import urllib.request

REPORT = Path("output/market_hub_report.json")
AUDIENCE = "atlas-market-terminal"
ENDPOINT = os.environ.get(
    "ATLAS_URL", "https://atlas-market-terminal.duc-nguyen-ndd127.workers.dev"
).rstrip("/") + "/api/ingest/github"


def number(value):
    try:
        f = float(value)
        return f if math.isfinite(f) and f > 0 else None
    except (TypeError, ValueError):
        return None


def details(item, mode):
    if mode == "SWING":
        plan = item
        zone = plan.get("entry_zone") or {}
        first = plan.get("tp1")
        second = plan.get("tp2")
        score = plan.get("swing_score")
        ready = bool(plan.get("swing_top_pick_rank"))
    else:
        plan = item.get("trade_plan") or {}
        zone = plan.get("entry_zone") or {}
        targets = plan.get("targets") or []
        # The Telegram TOP PICK explicitly publishes selector_tp1 = +2R.
        # The structural target in targets[0] is NOT a substitute for it.
        first = (item.get("selector_tp1") if item.get("top_pick_rank")
                 else (targets[0].get("price") if targets else None))
        position = item.get("position_plan") or {}
        second = (position.get("runner_target_price") if item.get("top_pick_rank")
                  else (targets[1].get("price") if len(targets) > 1 else None))
        score = item.get("selector_score") or item.get("score")
        ready = bool(plan.get("execution_ready"))
    lo, hi = number(zone.get("lower")), number(zone.get("upper"))
    stop, first, second = number(plan.get("stop_loss")), number(first), number(second)
    return {"entry_low": lo, "entry_high": hi, "stop": stop,
            "tp1": first, "tp2": second, "score": score,
            "source_ready": ready}


def serialize_publication(message, scan_at, sent_at, kind, report):
    mode = str(message.get("mode") or "INTRADAY")
    symbol = str(message.get("symbol") or "")
    direction = str(message.get("direction") or "").upper()
    bucket = str(message.get("bucket") or "")
    source = ((report.get("swing") or {}).get("top_picks") or []
              if mode == "SWING" else report.get("setups") or [])
    match = next((x for x in source
                  if x.get("symbol") == symbol
                  and str(x.get("direction") or "").upper() == direction
                  and (mode == "SWING" or x.get("bucket") == bucket)), None)
    if match is None:
        return None
    values = details(match, mode if mode == "SWING" else "INTRADAY")
    trackable = (
        kind == "setup_change"
        and (bucket == "SWING_TOP_PICK"
             or bucket == "ENTRY_READY" and values["source_ready"])
        and all(values[x] is not None for x in (
            "entry_low", "entry_high", "stop", "tp1"
        ))
    )
    if mode == "HEARTBEAT_REFERENCE":
        trackable = False
        reason = "HEARTBEAT_REFERENCE_ONLY"
    elif bucket in ("NEAR_ENTRY", "DEVELOPING", "WATCHLIST"):
        trackable = False
        reason = "PREPARATORY_SIGNAL_NOT_EXECUTION"
    elif not trackable:
        reason = "PLAN_NOT_VALIDATED"
    else:
        reason = "VALIDATED_PLAN_PRICE_OBSERVATION"
    key = "|".join((scan_at, sent_at, mode, symbol, bucket, direction))
    identifier = "tg-" + hashlib.sha256(key.encode()).hexdigest()[:40]
    return {"id": identifier, "symbol": symbol, "direction": direction,
            "bucket": bucket, "mode": mode, "is_trackable": bool(trackable),
            "reason": reason,
            **{k: values[k] for k in ("score", "entry_low", "entry_high",
                                      "stop", "tp1", "tp2")}}


def oidc_token():
    root = os.environ["ACTIONS_ID_TOKEN_REQUEST_URL"]
    endpoint = root + ("&" if "?" in root else "?") + urllib.parse.urlencode(
        {"audience": AUDIENCE}
    )
    req = urllib.request.Request(
        endpoint,
        headers={
            "Authorization": "Bearer " + os.environ["ACTIONS_ID_TOKEN_REQUEST_TOKEN"],
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.load(resp)["value"]


def main():
    if not REPORT.is_file():
        print("ATLAS: scanner report missing; publication journal skipped")
        return 0
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    delivery = report.get("telegram_delivery") or {}
    if delivery.get("confirmed") is not True:
        print("ATLAS: no confirmed Telegram delivery; no published signal to track")
        return 0
    scan_at = report.get("generated_at_utc")
    sent_at = delivery.get("sent_at_utc")
    if not scan_at or not sent_at:
        raise ValueError("Telegram delivery evidence incomplete")
    kind = str(delivery.get("kind") or "")
    if kind not in ("setup_change", "heartbeat"):
        raise ValueError("Unexpected delivery kind")
    publications = [
        record for message in delivery.get("items") or []
        if (record := serialize_publication(
            message, scan_at, sent_at, kind, report
        )) is not None
    ]
    # Empty confirmed Telegram heartbeat is valid and need not create a trade.
    payload = json.dumps({
        "generatedAt": scan_at, "sentAt": sent_at,
        "notificationKind": kind, "publications": publications[:30]
    }, allow_nan=False).encode()
    req = urllib.request.Request(
        ENDPOINT, method="POST", data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + oidc_token(),
            "User-Agent": "ATLAS-Market-Setup-Publisher/3.0",
        }
    )
    with urllib.request.urlopen(req, timeout=35) as resp:
        data = json.load(resp)
    if not data.get("ok"):
        raise RuntimeError("ATLAS rejected confirmed Telegram delivery")
    print("ATLAS: confirmed publications:", data.get("published"),
          "trackable:", data.get("tracked"),
          "rejected:", data.get("rejected"),
          "Telegram delivery:", kind)
    return 0


if __name__ == "__main__":
    sys.exit(main())
