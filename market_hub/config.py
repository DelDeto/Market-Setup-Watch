from pathlib import Path

BASE_URL = "https://api.mexc.com"
QUOTE_COIN = "USDT"

# Stage 1: whole-universe liquidity / quality pre-filter.
MAX_FULL_SCAN_SYMBOLS = 70
MIN_24H_TURNOVER_USDT = 2_000_000.0

# If bid/ask are available from MEXC ticker, reject clearly inefficient markets.
# Missing bid/ask does not fail the symbol.
MAX_SPREAD_BPS = 30.0

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

# Tradeability gates.
MIN_DEVELOPING_RR = 1.0
MIN_READY_RR = 1.5

# 15M ATR as % of price. Outside this broad band we cap the setup at WATCHLIST.
MIN_ATR_PCT = 0.10
MAX_ATR_PCT = 4.00

# Opposing higher-timeframe zone proximity. If an entry is too close to an
# opposing 1H/4H zone, the setup is capped at WATCHLIST.
HTF_1H_BLOCK_DISTANCE_ATR = 0.75
HTF_4H_BLOCK_DISTANCE_ATR = 0.50

STATE_PATH = Path("market_hub/state.json")
REPORT_PATH = Path("output/market_hub_report.json")
TEXT_PATH = Path("output/market_hub_update.txt")
