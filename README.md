# Market Setup Watch

Standalone market-wide scanner for MEXC USDT perpetual futures using deterministic multi-timeframe Price Action / SMC logic.

## Analysis flow

1. Load the tradable MEXC USDT perpetual universe.
2. Filter by 24H liquidity/notional.
3. Run the expensive analysis pass on the most liquid contracts.
4. Fetch 420 fully closed candles for 4H, 1H and 15M.
5. Analyze:
   - HH / HL / LH / LL
   - BOS / CHoCH
   - Supply / Demand V3
   - BSL / SSL and liquidity sweeps
   - displacement
   - FVG
   - retests
   - market regime
   - multi-timeframe alignment
6. Build a deterministic trade map.
7. Rank setups from 0–100.
8. Classify each symbol as `ENTRY_READY`, `DEVELOPING`, `WATCHLIST`, or `IGNORE`.
9. Send Telegram only when an actionable/developing candidate is new or materially changed.

The scanner uses **closed candles only** for signal calculation. Live ticker price is used only to measure distance to a previously calculated entry zone.

AI is not required for scanning, ranking, or trade-map generation.

## Run locally

```bash
pip install -r requirements.txt
python -m market_hub.main
```

## GitHub Actions

Workflow: `.github/workflows/market-setup-watch.yml`

It runs four times per hour, shortly after the expected 15M candle closes, and can also be started manually with `workflow_dispatch`.

### Required repository secrets

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

## Main modules

- `market_hub/mexc_market.py` — MEXC universe, ticker and closed-kline retrieval.
- `smc_analysis.py` — deterministic PA/SMC engine.
- `trade_plan.py` — deterministic entry/invalidation/target map.
- `market_hub/ranker.py` — scoring and setup buckets.
- `market_hub/scanner.py` — per-symbol MTF orchestration.
- `market_hub/notifier.py` — Telegram formatting and delivery.
- `market_hub/main.py` — market-wide scan orchestration.
