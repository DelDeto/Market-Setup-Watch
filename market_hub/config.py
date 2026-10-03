from pathlib import Path

BASE_URL = "https://api.mexc.com"
QUOTE_COIN = "USDT"

# Stage 1 scans the entire MEXC USDT perpetual universe on lightweight 1H data.
# Stage 2 deep-scans the strongest candidates with full 4H/1H/15M PA/SMC.
FAST_SCAN_HISTORY = 72
FAST_SCAN_MIN_HISTORY = 24
FAST_SCAN_WORKERS = 8
DEEP_SCAN_SYMBOLS = 150
FAST_SCAN_LIQUIDITY_RESERVE = 40
FAST_SCAN_VOLATILITY_RESERVE = 40

# If bid/ask are available from MEXC ticker, reject clearly inefficient markets.
# Missing bid/ask does not fail the symbol.
MAX_SPREAD_BPS = 30.0

HISTORY_LIMIT = 420
MIN_HISTORY_REQUIRED = 360

# Run shortly after each 15M candle close.
SCAN_CADENCE = "15M"

# Ranking / alert policy.
MAX_TELEGRAM_SETUPS = 8
TELEGRAM_HEARTBEAT_MINUTES = 60

# Meta-selector: rank a broad setup pool down to a maximum of two high-conviction
# picks. The selector is evaluated against a fixed +2R before -1R objective.
TOP_PICK_COUNT = 2
SELECTOR_TARGET_R = 2.00
SELECTOR_MIN_SCORE = 65.0

# Quality score thresholds. Quality and execution are intentionally separated:
# a structurally strong setup is not automatically an actionable entry.
READY_MIN_SCORE = 70
NEAR_ENTRY_MIN_SCORE = 66
DEVELOPING_MIN_SCORE = 62
WATCH_MIN_SCORE = 52

# Execution score thresholds.
READY_MIN_EXECUTION_SCORE = 70
NEAR_ENTRY_MIN_EXECUTION_SCORE = 55
DEVELOPING_MIN_EXECUTION_SCORE = 40

# Entry timing bands. READY means price is already close to the planned zone.
# NEAR_ENTRY / DEVELOPING are never allowed to stay actionable when price is
# more than 0.80 ATR away from the zone.
MAX_ENTRY_DISTANCE_ATR = 0.35
MAX_NEAR_ENTRY_DISTANCE_ATR = 0.80
MAX_DEVELOPING_ENTRY_DISTANCE_ATR = 0.80

# Tradeability gates.
MIN_DEVELOPING_RR = 1.20
MIN_READY_RR = 1.50

# Forward-journal management observations. These do not place or modify orders;
# they allow us to measure how many raw losses could have been protected.
PROTECT_AT_R = 1.00
PARTIAL_AT_R = 2.00
TRAIL_AT_R = 2.00

# 15M ATR as % of price. Outside this broad band we cap the setup at WATCHLIST.
MIN_ATR_PCT = 0.10
MAX_ATR_PCT = 4.00

# Opposing higher-timeframe zone proximity. If an entry is too close to an
# opposing 1H/4H zone, the setup is capped at WATCHLIST.
HTF_1H_BLOCK_DISTANCE_ATR = 0.75
HTF_4H_BLOCK_DISTANCE_ATR = 0.50

# Correlation suppression: keep at most two similar same-direction theses.
CORRELATION_LOOKBACK_BARS = 96
MAX_RETURN_CORRELATION = 0.80
MAX_CORRELATED_SETUPS = 2

# Adaptive calibration guardrails. Until enough WIN/LOSS outcomes exist,
# adaptive scoring stays OFF and base deterministic weights are preserved.
MIN_CALIBRATION_OUTCOMES = 40
MIN_CALIBRATION_FEATURE_SAMPLES = 15

STATE_PATH = Path("market_hub/state.json")
OUTCOME_PATH = Path("market_hub/outcomes.json")
CALIBRATION_PATH = Path("market_hub/calibration.json")
REPORT_PATH = Path("output/market_hub_report.json")
TEXT_PATH = Path("output/market_hub_update.txt")
