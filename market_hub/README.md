# Crypto Market Setup Hub

A market-wide MEXC USDT perpetual scanner built on the same deterministic PA/SMC V2 engine used by the VVV monitor.

## Architecture

1. Retrieve the full MEXC futures contract universe.
2. Apply a liquidity/notional filter.
3. Keep the most liquid contracts for the expensive full scan.
4. Fetch **420 fully closed candles** for 4H, 1H and 15M.
5. Run the existing deterministic engine:
   - HH / HL / LH / LL
   - BOS / CHoCH
   - Supply / Demand V3
   - BSL / SSL and sweep
   - displacement
   - FVG
   - retest
   - Market Regime
   - MTF Alignment
   - Trade Plan
6. Rank setups from 0–100.
7. Telegram only new/changed **ENTRY_READY** or **DEVELOPING** setups.

## Alert buckets

- 🔥 **ENTRY_READY** — Python execution gate passes, MTF is not CONFLICT, setup score is high, and live price is inside/near the deterministic entry zone.
- ⚡ **DEVELOPING** — strong setup but still waiting for one or more execution conditions.
- 👀 **WATCHLIST** — valid context, not yet strong enough to alert by default.

## Deterministic ranking

Ranking uses structure/setup completeness, Supply/Demand grade, sweep, displacement, structure break, retest, MTF alignment, first-target RR and live distance to entry.

AI is intentionally not required for market selection. The scanner must remain functional even when OpenRouter is rate-limited.

## Schedule

GitHub Actions scans every 15 minutes, shortly after a 15M candle close. Signal calculations use closed candles only; live ticker price is used only to determine distance to the already-computed entry zone.

## Telegram

The first version reuses the existing:
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

A separate Telegram group/chat can be added later by changing only the Market Hub workflow secret name.
