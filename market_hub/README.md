# Market Setup Watch scanner package

The `market_hub` package orchestrates the standalone Market Setup Watch service.

## Buckets

- 🔥 **ENTRY_READY** — deterministic execution gate passes, MTF is not CONFLICT, score is high enough, and live price is inside/near the precomputed entry zone.
- ⚡ **DEVELOPING** — strong setup that still needs one or more execution conditions.
- 👀 **WATCHLIST** — valid context that is not yet strong enough for default alerts.
- **IGNORE** — below watch threshold.

## Ranking inputs

The deterministic score uses setup completeness, Supply/Demand grade, liquidity sweep, displacement, structure break, retest, MTF alignment, first-target R:R, and live distance to entry.

## State

`market_hub/state.json` stores compact signatures of current READY/DEVELOPING candidates to suppress duplicate Telegram messages.
