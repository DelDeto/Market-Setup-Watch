#!/usr/bin/env python3
"""Publish verified MEXC scanner plans to ATLAS using GitHub Actions OIDC.

No secret is stored here. The source scanner's Telegram behavior is unchanged.
This program never places an order.
"""
import hashlib
import json
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
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def plan_to_signal(item, swing=False):
    if item.get("correlation_suppressed"):
        return None
    if swing:
        if not item.get("swing_top_pick_rank"):
            return None
        plan = item
        zone = item.get("entry_zone") or {}
        bucket = "SWING_TOP_PICK"
        stop = item.get("stop_loss")
        tp1 = item.get("tp1")
        tp2 = item.get("tp2")
        score = item.get("swing_score")
    else:
        if item.get("bucket") != "ENTRY_READY":
            return None
        plan = item.get("trade_plan") or {}
        if not plan.get("execution_ready"):
            return None
        zone = plan.get("entry_zone") or {}
        bucket = "ENTRY_READY"
        stop = plan.get("stop_loss")
        targets = plan.get("targets") or []
        tp1 = targets[0].get("price") if targets else None
        tp2 = targets[1].get("price") if len(targets) > 1 else None
        score = item.get("selector_score") or item.get("score")
    symbol = item.get("symbol")
    direction = str(item.get("direction") or "").upper()
    lo, hi = number(zone.get("lower")), number(zone.get("upper"))
    stop, tp1, tp2 = number(stop), number(tp1), number(tp2)
    if (not symbol or not symbol.endswith("_USDT")
            or direction not in ("LONG", "SHORT")
            or None in (lo, hi, stop, tp1) or lo > hi):
        return None
    if direction == "LONG" and not (stop < lo and tp1 > hi):
        return None
    if direction == "SHORT" and not (stop > hi and tp1 < lo):
        return None
    if tp2 is not None and (tp2 <= tp1 if direction == "LONG" else tp2 >= tp1):
        tp2 = None
    payload = {
        "symbol": symbol,
        "direction": direction,
        "bucket": bucket,
        "score": score,
        "entry_low": lo,
        "entry_high": hi,
        "stop": stop,
        "tp1": tp1,
        "tp2": tp2,
    }
    key = "|".join(
        str(payload[k])
        for k in ("symbol", "direction", "entry_low", "entry_high", "stop", "tp1")
    )
    payload["id"] = "setup-" + hashlib.sha256(key.encode()).hexdigest()[:30]
    return payload


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
        print("ATLAS publisher: scanner report not found; skipping.")
        return 0
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    at = report.get("generated_at_utc")
    if not at:
        print("ATLAS publisher: report timestamp missing; skipping.")
        return 0
    candidates = []
    for item in report.get("setups") or []:
        result = plan_to_signal(item)
        if result:
            candidates.append(result)
    for item in (report.get("swing") or {}).get("top_picks") or []:
        result = plan_to_signal(item, swing=True)
        if result:
            candidates.append(result)
    unique = list({x["id"]: x for x in candidates}.values())[:50]
    payload = json.dumps({"generatedAt": at, "signals": unique}).encode()
    token = oidc_token()
    req = urllib.request.Request(
        ENDPOINT, method="POST", data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + token,
            "User-Agent": "ATLAS-Market-Setup-Publisher/2.0",
        }
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
    if not data.get("ok"):
        raise RuntimeError("ATLAS publisher rejected scanner report")
    print(
        "ATLAS published", data["accepted"], "verified plans (",
        data.get("rejected", 0), "rejected ) from", at
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
