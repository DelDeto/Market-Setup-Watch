from pathlib import Path

BASE_URL = "https://api.mexc.com"
QUOTE_COIN = "USDT"

# Stage 1: scan the whole futures universe, then keep the most liquid
# contracts for the expensive 4H/1H/15M PA/SMC pass.
MAX_FULL_SCAN_SYMBOLS = 70
MIN_24H_TURNOVER_USDT = 2_000_000.0

HISTORY_LIMIT = 420
MIN_HISTORY_REQUIRED = 360

# Run shortly after each 15M candle close.
SCAN_CADENCE = "15M"

# Ranking / alert policy.
MAX_TELEGRAM_SETUPS = 8
READY_MIN_SCORE = 78
DEVELOPING_MIN_SCORE = 68
WATCH_MIN_SCORE = 58
MAX_ENTRY_DISTANCE_ATR = 0.25

STATE_PATH = Path("market_hub/state.json")
REPORT_PATH = Path("output/market_hub_report.json")
TEXT_PATH = Path("output/market_hub_update.txt")
