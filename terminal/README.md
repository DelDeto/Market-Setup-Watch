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

## ATLAS V2 upgrade: server-push market feed and observed-level alerts

**Status:** V2 preview first, deploy to main Worker only after passing CI and E2E. Only the Market Setup Watch scanner is wired to the authenticated *live* signal publish workflow. Crypto Short M2/M3 and VVV are still historical journal sources, not real-time publishers.

- **Frontend:** `GET /api/ws` upgrades to a Cloudflare Durable Object WebSocket. It broadcasts a full-MEXC USDT perpetual futures ticker *snapshot* every ~10 seconds while browsers connect; the DO checks every ~30 seconds without viewers. Upstream remains public REST `/api/v1/contract/ticker` — **not** exchange tick-by-tick WebSocket. HTTP fallback remains.
- **Durable Object:** singleton `AtlasLiveRoom` bound as `LIVE_ROOM` (SQLite migration `v1-atlas-live` on production, preview has independent namespace). An alarm re-arms itself, with error logging and restarts on scheduled cron/connection. Existing 5-minute cron continues the source-state sync as a safety net.
- **Scanner integration:** `.github/workflows/market-setup-watch.yml` gains `id-token: write`, then calls `python terminal/publish_scan.py` after the existing Telegram sender. The publisher uses a signed GitHub Actions OIDC JWT. Cloudflare checks RS256 signature against GitHub JWKS and verifies exact issuer, audience, repository, branch and authorized workflow before importing confirmed ENTRY_READY plans. No shared user secret is embedded in public files.
- **Price tracking:** `GET /api/tracking` reads only newly published, verified source plans. Server periodically checks **sampled last price** against Entry/Stop/TP; it cannot observe prices between samples. States include WAIT_ENTRY, ENTRY_OBSERVED, TP1_OBSERVED, TP2_OBSERVED, SL_OBSERVED and EXPIRED. This does not prove real order execution, fills or live PnL.
- **Telegram event relay:** GitHub workflow `atlas-event-dispatch.yml` runs every ~5 minutes and uses the existing repo's Telegram bot secrets. It claims pending observation events with GitHub OIDC (`POST /api/alerts/claim`) and acknowledges successful sends (`POST /api/alerts/ack`). A failed send is retried after a lease timeout. Scheduled job starts can be delayed; updates are not guaranteed immediate.
- **Health:** `GET /api/live-health` returns last live feed success/error, total subscribers and alarm schedule; existing `/api/health` shows 5-minute background snapshots; the independent GitHub watchdog should monitor both sources.
- **Safety:** no exchange trading API keys, no auto-entry, no claims of actual trading profits. The system sends observations, not financial promises. Limited frontend/websocket rate is by design; low-latency exchange WebSocket consumption needs dedicated reliable upstream services and additional setup.

### Deploy manifest (Cloudflare API)

The GitHub source is two ES modules: `terminal/worker.js` and `terminal/live.js`. Configure Worker upload metadata with `main_module: worker.js`, `compatibility_date: 2026-11-07`, `bindings: [{type: d1, name: DB, id: <DATABASE_ID>}, {type: durable_object_namespace, name: LIVE_ROOM, class_name: AtlasLiveRoom}]`, and on the **first** DO deployment only: `migrations: {new_tag: v1-atlas-live, new_sqlite_classes: [AtlasLiveRoom]}`. Existing production migrations must not be reapplied under the same tag. Cloudflare managed Worker deployments via API are used here; GitHub CI performs validation, not implicit production deploys.

### Operational acceptance

1. `node --check terminal/worker.js && node --check terminal/live.js` and `node --test terminal/tests/live.test.mjs` pass.
2. Preview GitHub E2E test receives a nonempty WebSocket `market` frame and rejects unauthenticated POST to `/api/ingest/github`.
3. Production `/api/live-health` timestamp remains fresh, with MEXC instruments >50 and no recent errors after several scheduled polls.
4. Next actual scanner run must show an OIDC publish step accepted and only verified plans imported. With zero ENTRY_READY signals, `0 accepted` is expected; no artificial signals are created.
5. Telegram event workflow should be tested with genuine observed-level events; without genuine events, delivery is **not verified**, even if its job passes. Event notifications must not be invented to prove the test.


## V3: Audited Telegram Publication Ledger and Closed-Candle Outcomes

The V2 prototype sampled last prices and only ingested ENTRY_READY plans, so its signal history did not match every sent message. V3 separates the confirmed Telegram receipt ledger, actionable source plans, and candle-based outcome observations.

- market_hub/main.py persists delivery metadata in the full scanner report only after all Telegram destinations confirm success. It records the same text items as the notifier's sorting and limits. Heartbeats are reference-only.
- terminal/publish_scan.py publishes deterministic IDs for confirmed text references, including ENTRY_READY, NEAR_ENTRY, DEVELOPING, WATCHLIST and SWING_TOP_PICK. Only valid, execution-ready READY/SWING plans create price-level monitors.
- The source's Telegram selector_tp1 takes precedence for TOP PICKs. Structural first targets are not substituted for the published 2R target.
- /api/tracking reports publications, monitors and events separately. /api/outcomes reports TP1-first versus SL-first among unambiguous resolved candle observations, not live portfolio PnL or exchange fills.
- Closed MEXC Min1 (intraday) or Min15 (swing) candles are evaluated chronologically, excluding pre-publication and still-forming candles. Missing a candle is DATA_GAP; same-candle entry/stop/target conflicts are AMBIGUOUS and never guessed.
- The outcome scheduler runs every two minutes, independent from the five-minute background market/scanner/research source sync. The hourly watchdog checks price freshness, scanner freshness and outcome health.

**Upgrade SQL:** apply only the ATLAS V3 section of terminal/schema.sql to an existing database; ALTER TABLE statements are not repeatable.

**Provenance limitation:** the confirmed Telegram receipt ledger begins with V3. Old scanner signatures are not proof of which messages were sent. Crypto Short and VVV are historical research inputs until source-specific verified publishers are connected. Results are theoretical price-level conditions, not actual trades, broker fills or realized profits.
