import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import requests

from .config import BINANCE_CROSSLIST_CACHE_PATH


SPOT_INFO_URL = "https://data-api.binance.vision/api/v3/exchangeInfo"
FUTURES_WEB_URL = (
    "https://www.binance.com/bapi/futures/v1/friendly/future/common/brackets"
)
FUTURES_S3_URL = (
    "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
)
FUTURES_S3_PREFIX = "data/futures/um/daily/klines/"


def normalize_underlying(base):
    value = str(base or "").upper().strip()
    for prefix in ("1000000", "1000"):
        if value.startswith(prefix) and len(value) > len(prefix) + 1:
            return value[len(prefix):]
    return value


def mexc_underlying(symbol):
    value = str(symbol or "").upper()
    if value.endswith("_USDT"):
        value = value[:-5]
    elif value.endswith("USDT"):
        value = value[:-4]
    return normalize_underlying(value)


def _fetch_spot_bases():
    response = requests.get(
        SPOT_INFO_URL,
        headers={"User-Agent": "MarketSetupWatch/1.0"},
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()

    bases = set()
    for row in payload.get("symbols", []):
        if row.get("quoteAsset") != "USDT":
            continue
        if row.get("status") != "TRADING":
            continue
        base = normalize_underlying(row.get("baseAsset"))
        if base:
            bases.add(base)

    if not bases:
        raise RuntimeError("Binance Spot cross-list returned no trading USDT bases")
    return bases


def _fetch_futures_bases_web():
    response = requests.get(
        FUTURES_WEB_URL,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()

    brackets = (
        payload.get("data", {}).get("brackets", [])
        if isinstance(payload, dict)
        else []
    )

    bases = set()
    for row in brackets:
        symbol = str(row.get("symbol") or "").upper()
        if not symbol.endswith("USDT"):
            continue
        base = normalize_underlying(symbol[:-4])
        if base:
            bases.add(base)

    if not bases:
        raise RuntimeError("Binance Futures web cross-list returned no USDT bases")
    return bases


def _fetch_futures_bases_s3():
    bases = set()
    marker = None

    while True:
        params = {
            "delimiter": "/",
            "prefix": FUTURES_S3_PREFIX,
        }
        if marker:
            params["marker"] = marker

        response = requests.get(
            FUTURES_S3_URL,
            params=params,
            headers={"User-Agent": "MarketSetupWatch/1.0"},
            timeout=20,
        )
        response.raise_for_status()

        root = ET.fromstring(response.text)
        ns = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}

        for node in root.findall("s3:CommonPrefixes/s3:Prefix", ns):
            text = node.text or ""
            if not text.startswith(FUTURES_S3_PREFIX):
                continue
            symbol = text[len(FUTURES_S3_PREFIX):].strip("/")
            if not symbol or "_" in symbol or not symbol.endswith("USDT"):
                continue
            base = normalize_underlying(symbol[:-4])
            if base:
                bases.add(base)

        truncated = (
            (root.findtext("s3:IsTruncated", default="false", namespaces=ns))
            .strip()
            .lower()
            == "true"
        )
        if not truncated:
            break

        marker = root.findtext(
            "s3:NextMarker",
            default="",
            namespaces=ns,
        ).strip()
        if not marker:
            raise RuntimeError(
                "Binance Vision S3 listing truncated without NextMarker"
            )

    if not bases:
        raise RuntimeError("Binance Vision S3 futures listing returned no USDT bases")
    return bases


def _load_cache():
    if not BINANCE_CROSSLIST_CACHE_PATH.exists():
        return None

    try:
        payload = json.loads(
            BINANCE_CROSSLIST_CACHE_PATH.read_text(encoding="utf-8")
        )
        bases = {
            normalize_underlying(value)
            for value in payload.get("bases", [])
            if value
        }
        if not bases:
            return None
        return {
            "bases": bases,
            "updated_at_utc": payload.get("updated_at_utc"),
            "source": payload.get("source", "cache"),
            "spot_count": payload.get("spot_count"),
            "futures_count": payload.get("futures_count"),
        }
    except Exception:
        return None


def _save_cache(bases, spot_count, futures_count, source):
    BINANCE_CROSSLIST_CACHE_PATH.write_text(
        json.dumps(
            {
                "updated_at_utc": datetime.now(timezone.utc).isoformat(),
                "source": source,
                "spot_count": spot_count,
                "futures_count": futures_count,
                "crosslisted_count": len(bases),
                "bases": sorted(bases),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def get_binance_crosslisted_bases():
    errors = []

    try:
        spot = _fetch_spot_bases()
    except Exception as exc:
        spot = None
        errors.append(f"spot:{exc}")

    futures = None
    futures_source = None

    try:
        futures = _fetch_futures_bases_web()
        futures_source = "binance_web_futures"
    except Exception as exc:
        errors.append(f"futures_web:{exc}")

    if futures is None:
        try:
            futures = _fetch_futures_bases_s3()
            futures_source = "binance_vision_s3_futures"
        except Exception as exc:
            errors.append(f"futures_s3:{exc}")

    if spot is not None and futures is not None:
        crosslisted = spot & futures
        source = f"binance_spot+{futures_source}"
        _save_cache(
            crosslisted,
            spot_count=len(spot),
            futures_count=len(futures),
            source=source,
        )
        return crosslisted, {
            "active": True,
            "source": source,
            "spot_count": len(spot),
            "futures_count": len(futures),
            "crosslisted_count": len(crosslisted),
            "errors": errors,
        }

    cached = _load_cache()
    if cached is not None:
        return cached["bases"], {
            "active": True,
            "source": "cache",
            "cache_updated_at_utc": cached.get("updated_at_utc"),
            "cache_source": cached.get("source"),
            "spot_count": cached.get("spot_count"),
            "futures_count": cached.get("futures_count"),
            "crosslisted_count": len(cached["bases"]),
            "errors": errors,
        }

    return None, {
        "active": False,
        "source": "fail_open_no_cache",
        "errors": errors,
    }
