# Market Setup Watch scanner package

The `market_hub` package orchestrates the standalone Market Setup Watch service.

## V3: entry-centric ranking

V3 separates two questions that were previously mixed into one score:

- **Quality score (Q)** — structure, displacement, retest/sweep context, Supply/Demand quality, MTF alignment, HTF location, participation and broad market context.
- **Execution score (E)** — live distance to entry, first-target R:R, entry-zone quality and whether the deterministic execution map is already clear.

A high-quality setup can therefore remain WATCHLIST if price is too far from its entry zone. This prevents a visually strong but late setup from outranking a slightly lower-Q setup that is actually tradeable now.

## Buckets

- 🔥 **ENTRY_READY** — deterministic gate passes, Q/E thresholds pass, first target is at least 1.5R, and price is within 0.35 ATR of the selected entry zone.
- 🎯 **NEAR_ENTRY** — strong setup within 0.80 ATR of entry with acceptable R:R; it is close enough to monitor actively but not yet a full READY signal.
- ⚡ **DEVELOPING** — valid structure within 0.80 ATR of entry but still missing a soft execution condition.
- 👀 **WATCHLIST** — useful market context or a strong setup that is still too far from entry / blocked for execution.
- **IGNORE** — below watch threshold.

## Entry selection

The trade plan no longer selects entry candidates using a fixed source priority. Retest, Supply/Demand, FVG and structure-reclaim candidates are compared using:

- correct-side retracement geometry,
- Supply/Demand grade,
- first-target R:R,
- distance to live price,
- risk width in ATR,
- source quality.

The highest-scoring candidate becomes the active entry zone.

## Management observations

The forward journal keeps the original raw WIN/LOSS result unchanged, while also recording whether the trade reached:

- +1.0R: protection / breakeven threshold,
- +1.5R: partial-protection threshold,
- +2.0R: trailing-management threshold.

This lets calibration measure how many raw stop-outs first offered meaningful favorable excursion without inventing intrabar execution order.

## State

`market_hub/state.json` stores compact signatures of current READY/NEAR_ENTRY/DEVELOPING candidates to suppress duplicate Telegram messages.
