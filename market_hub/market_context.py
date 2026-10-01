def _bias_from_analysis(analysis_4h, analysis_1h):
    labels = [
        str((analysis_4h or {}).get("regime") or "").upper(),
        str((analysis_1h or {}).get("regime") or "").upper(),
        str((analysis_4h or {}).get("trend") or "").upper(),
        str((analysis_1h or {}).get("trend") or "").upper(),
    ]

    bull = sum("BULL" in value or "UP" in value for value in labels)
    bear = sum("BEAR" in value or "DOWN" in value for value in labels)

    if bull > bear and bull >= 2:
        return "BULLISH"
    if bear > bull and bear >= 2:
        return "BEARISH"
    return "MIXED"


def derive_market_context(benchmark_items):
    btc = benchmark_items.get("BTC_USDT") or {}
    eth = benchmark_items.get("ETH_USDT") or {}

    btc_bias = _bias_from_analysis(
        btc.get("analysis_4h"),
        btc.get("analysis_1h"),
    ) if btc else "UNKNOWN"

    eth_bias = _bias_from_analysis(
        eth.get("analysis_4h"),
        eth.get("analysis_1h"),
    ) if eth else "UNKNOWN"

    if btc_bias == eth_bias and btc_bias in ("BULLISH", "BEARISH"):
        regime = btc_bias
        confidence = "HIGH"
    elif "UNKNOWN" in (btc_bias, eth_bias):
        regime = "MIXED"
        confidence = "LOW"
    else:
        regime = "MIXED"
        confidence = "MEDIUM"

    return {
        "regime": regime,
        "confidence": confidence,
        "btc_bias": btc_bias,
        "eth_bias": eth_bias,
    }


def market_context_points(direction, context, symbol=None):
    if not context or symbol in ("BTC_USDT", "ETH_USDT"):
        return 0

    regime = context.get("regime")
    if regime == "BULLISH":
        return 5 if direction == "long" else -6
    if regime == "BEARISH":
        return 5 if direction == "short" else -6
    return 0
