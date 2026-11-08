#!/usr/bin/env python3
"""Dispatch ATLAS observed price events using the existing Telegram bot.

Claim/ack is protected by GitHub's OIDC JWT. No exchange orders are placed.
An observed price is not proof of a filled trade.
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.error
import urllib.request

BASE = os.environ.get(
    "ATLAS_URL", "https://atlas-market-terminal.duc-nguyen-ndd127.workers.dev"
).rstrip("/")
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")


def post(path, token, payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        BASE + path, data=data, method="POST",
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
            "User-Agent": "ATLAS-Telegram-Relay/2.0",
        },
    )
    with urllib.request.urlopen(req, timeout=25) as resp:
        return json.load(resp)


def oidc_token():
    url = os.environ["ACTIONS_ID_TOKEN_REQUEST_URL"]
    url += ("&" if "?" in url else "?") + urllib.parse.urlencode(
        {"audience": "atlas-market-terminal"}
    )
    req = urllib.request.Request(
        url, headers={
            "Authorization": "Bearer " + os.environ["ACTIONS_ID_TOKEN_REQUEST_TOKEN"]
        }
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.load(resp)["value"]


def send_telegram(event):
    name = {
        "ENTRY_OBSERVED": "🟡 Giá được quan sát trong vùng Entry",
        "TP1_OBSERVED": "🟢 Giá được quan sát chạm TP1",
        "TP2_OBSERVED": "🟢 Giá được quan sát chạm TP2",
        "SL_OBSERVED": "🔴 Giá được quan sát chạm SL",
    }.get(event["kind"], "Giá biến động")
    message = (
        "ATLAS · " + name + "\n"
        + str(event["symbol"]) + " · " + str(event["direction"]) + "\n"
        + "Giá quan sát: " + str(event.get("observed_price")) + "\n"
        + "UTC: " + str(event.get("observed_at")) + "\n"
        + "Theo dõi mức giá, KHÔNG xác nhận đã khớp lệnh."
        + "\n" + BASE
    )
    body = urllib.parse.urlencode({"chat_id": CHAT, "text": message}).encode()
    req = urllib.request.Request(
        "https://api.telegram.org/bot" + TOKEN + "/sendMessage",
        data=body, method="POST",
    )
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                result = json.load(resp)
            return result.get("ok") is True
        except urllib.error.HTTPError as error:
            if error.code == 429 and attempt == 0:
                retry = error.headers.get("Retry-After")
                time.sleep(min(15, max(2, int(retry or "4"))))
                continue
            print("Telegram API HTTP", error.code)
            return False
        except Exception as error:
            print("Telegram dispatch error", type(error).__name__)
            return False
    return False



def send_watchdog_notice(notice):
    """Send one independently detected Cloudflare scanner incident through the
    existing authenticated GitHub Actions Telegram channel."""
    message = str(notice.get("message") or "")[:3600]
    if not message:
        return False
    body = urllib.parse.urlencode({
        "chat_id": CHAT, "text": message, "disable_web_page_preview": "true"
    }).encode()
    for attempt in range(2):
        req = urllib.request.Request(
            "https://api.telegram.org/bot" + TOKEN + "/sendMessage",
            data=body, method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                reply = json.load(resp)
            return reply.get("ok") is True
        except urllib.error.HTTPError as error:
            if error.code == 429 and attempt == 0:
                time.sleep(min(15, max(2, int(error.headers.get("Retry-After") or "4"))))
                continue
            print("ATLAS watchdog Telegram HTTP", error.code)
            return False
        except Exception as error:
            print("ATLAS watchdog Telegram dispatch error", type(error).__name__)
            return False
    return False


def main():
    if not TOKEN or not CHAT:
        print("ATLAS notifications disabled: existing Telegram secrets unavailable.")
        return 0
    jwt = oidc_token()
    data = post("/api/alerts/claim", jwt, {})
    events = data.get("events") or []
    print("ATLAS notification batch:", len(events))
    delivered = 0
    for event in events:
        if send_telegram(event):
            ack = post("/api/alerts/ack", jwt, {"ids": [event["id"]]})
            if ack.get("acknowledged") == 1:
                delivered += 1
        else:
            print("An event remains leased for retry:", event["id"])
    print("ATLAS Telegram observed-price notifications delivered:", delivered)
    incident_batch = post("/api/watchdog/claim", jwt, {})
    notices = incident_batch.get("notices") or []
    print("ATLAS Cloudflare watchdog incident batch:", len(notices))
    incident_delivered = 0
    for notice in notices:
        if send_watchdog_notice(notice):
            receipt = post("/api/watchdog/ack", jwt, {"ids": [notice["id"]]})
            if receipt.get("acknowledged") == 1:
                incident_delivered += 1
        else:
            print("ATLAS watchdog incident pending retry:", notice["id"])
    print("ATLAS Cloudflare watchdog Telegram delivered:", incident_delivered)
    macro_batch = post("/api/macro/alerts/claim", jwt, {})
    macro_items = macro_batch.get("alerts") or []
    print("ATLAS high-impact macro alert batch:", len(macro_items))
    macro_delivered = 0
    for news in macro_items:
        if send_watchdog_notice(news):
            receipt = post("/api/macro/alerts/ack", jwt, {"ids": [news["id"]]})
            if receipt.get("acknowledged") == 1:
                macro_delivered += 1
        else:
            print("ATLAS macro alert pending retry:", news["id"])
    print("ATLAS macro Telegram delivered:", macro_delivered)
    if delivered != len(events) or incident_delivered != len(notices) or macro_delivered != len(macro_items):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
