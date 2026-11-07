# ATLAS Terminal — Crypto Market Intelligence

Cloudflare Workers + D1 market terminal for **manual** crypto futures analysis, with GitHub research sources and a built-in Web dashboard. The service is deliberately independent of existing scanner jobs; their Telegram alerts and execution policies stay unchanged.

**Deployment:** `atlas-market-terminal.duc-nguyen-ndd127.workers.dev` (enabled in Cloudflare account).
**Cloudflare Worker:** `atlas-market-terminal`
**D1 database:** `crypto-market-terminal-v1`
**Schedule:** `*/5 * * * *` UTC

## Current features and data provenance

- Market overview: MEXC USDT perpetual ticker snapshot, all available USDT perpetual symbols returned by the exchange. Website refreshes the API every 15 seconds while open. This is HTTP polling, **not** a persistent exchange-wide tick feed.
- Closed-candle charts: MEXC 15m/1h OHLC from the public futures API; the ongoing candle is excluded.
- Latest scanner status from `Market-Setup-Watch/market_hub/state.json`; four buckets, timestamps and published alert signatures. These signatures are **not** proof of current active positions.
- Historical calibration from `market_hub/calibration.json`. Historical win rate is **not live PnL**.
- Research journal: hourly imports of `Crypto_Short/state/m2_live_signals.json`, `Crypto_Short/state/m3_v32_signals.json`, and `vvv-trading-ai/signal_history.json`. Each source remains separate. Old OPEN records are labeled historical, never promoted to current positions.
- D1 historical records, health state, last API error and sync timestamps.
- Protected webhook for a future event publisher; disabled until `PUBLISH_TOKEN` is configured.

## Data pipeline and latency

1. The Worker scheduled event runs every five minutes to fetch MEXC futures tickers, the latest Market-Setup-Watch published state, and its calibration snapshot.
2. Once per hour it also refreshes archive research sources (M2/M3/VVV). Historical imports may be stale.
3. The frontend calls `/api/market` every 15 seconds while open. An independent hourly GitHub Actions watchdog checks market and scheduled-sync freshness and, when existing repository Telegram secrets are configured, sends incident alerts. It calls `/api/dashboard` every minute and `/api/research` every ten minutes. The market endpoint fetches live HTTP data with a database fallback and an explicit freshness label.
4. GitHub Actions scanner continues to run on **closed** 15m candles. Scanner output may lag the market ticker; prices must not be presented as confirmed new strategy signals.

API routes:
- `GET /` — dashboard
- `GET /api/market` — live-on-request futures tickers or last stored snapshot
- `GET /api/chart?symbol=BTC_USDT&tf=15m` — last closed chart candles
- `GET /api/dashboard` — scanner snapshot, calibration, recent source alert signatures, sync health
- `GET /api/research` — historical signal journal from three repositories
- `GET /api/health` — running/stale/not-initialized status based on the last scheduled sync
- `POST /api/ingest` — authenticated optional event ingestion; responds 503 while `PUBLISH_TOKEN` is not configured

## Security

The public API is read-only apart from the protected ingestion endpoint. Never store MEXC order credentials or Telegram bot tokens in this public repository. Deploy credentials as Cloudflare secrets. There is **no automatic exchange order placement**.

To enable `POST /api/ingest`, add a unique secret named `PUBLISH_TOKEN` to the deployed Worker via Cloudflare. The caller must supply `Authorization: Bearer <token>` and JSON with `id`, `source`, `symbol` (e.g. `BTC_USDT`), `direction` (`LONG`/`SHORT`), `bucket`, and optional `entry_low`, `entry_high`. Add the same token to the originating scanner's GitHub Actions secrets if using it as a publisher. The current scanner continues sending its own Telegram signals. The Terminal does **not** claim to be sending Telegram messages itself.

## Verification

- Check D1 schema and data state: `terminal/schema.sql`.
- Check Worker code syntax: `node --check terminal/worker.js`.
- Read `GET /api/health`; require an actual recent `lastSuccess` and no `lastError` before declaring 24/7 ingestion healthy.
- Check `GET /api/market` `mode`. `live-on-request` means the exchange responded; `last-snapshot` means fallback, not live.
- Check `GET /api/chart` returns closed candles and compare a sample to the MEXC exchange.
- Run `Trading Terminal CI` and (for endpoint checks) `Trading Terminal Smoke Test` from Actions.

## What is **not** finished yet

The current deployment is a working foundation, not the final low-latency 24/7 multi-exchange system. Continuous exchange WebSockets, a VPS collector, unified real-time event forwarding from every strategy, verified per-signal forward outcomes, Telegram credentials for the new service, full account-level PnL and automated GitHub-to-Cloudflare deployments are **not configured**. They require additional services and/or explicit credentials. The interface must not display simulated execution, extrapolated results or a zero-latency guarantee.

## Migration and rollback

Existing `market_hub/` scanner Python code and GitHub Actions are unchanged. To roll back the Terminal, roll back the `atlas-market-terminal` Worker deployment; do not delete shared scanner code. D1 remains independent of trading repositories.
