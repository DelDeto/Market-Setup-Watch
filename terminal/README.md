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


### V3 operational recovery

An independent 15-minute GitHub Actions watchdog now checks if Market Setup Watch source state is more than 45 minutes old. If no scanner run started in the last 40 minutes, it uses the repository-scoped GitHub Actions GITHUB_TOKEN (actions:write only on the watchdog job) to dispatch **one** existing Market Setup Watch scan. A recent run prevents duplicate recovery dispatches. This is schedule resilience, not a guarantee that GitHub Actions will always start immediately, and it never initiates exchange trades. If the GitHub API is unavailable or dispatch permission is denied, the workflow logs an error and continues health checks.


## ATLAS V3.1 — independent Cloudflare scanner watchdog

**Status route:** /api/watchdog (read-only, does not expose secrets).

- A **separate** Cloudflare Cron runs every three minutes (UTC) regardless of GitHub Actions schedules. It evaluates scanner_snapshots.source_updated_at, not the D1 mirror sync time. A source age greater than 45 minutes is STALE.
- The source transition OK → STALE is journaled exactly once per outage into D1 watchdog_notifications, then OK creates a recovery notification. A durable pending/lease/ack queue avoids repeated alerts across scheduled runs.
- Each stale check consults the **public GitHub Actions workflow runs API** no more often than every 12 minutes. An active GitHub run or a run started in the last 40 minutes prevents duplicate dispatch. A direct dispatch also has its own 40-minute cooldown.
- Direct Cloudflare → GitHub workflow dispatch is **disabled unless** the Worker has the secret GITHUB_RECOVERY_TOKEN (a fine-grained GitHub PAT granting Actions: Read and write **only** to DelDeto/Market-Setup-Watch). Tokens must never be committed, exposed by a public endpoint, or inserted into D1.
- Without that token, the independent Cloudflare watchdog still detects, records and queues incidents. The existing GitHub Actions watchdog remains a fallback recovery dispatcher when GitHub resumes scheduling; it is not fully independent recovery.
- Direct Telegram delivery is optional using Worker secrets WATCHDOG_TELEGRAM_BOT_TOKEN and WATCHDOG_TELEGRAM_CHAT_ID. Without these, the existing GitHub Actions Telegram relay (with its configured GitHub secrets) retrieves queued notices through signed GitHub OIDC endpoints /api/watchdog/claim and /api/watchdog/ack.
- GitHub scheduling is best effort: queued notifications can be delayed if GitHub schedules are skipped. Deploying these Worker secrets later enables genuinely independent GitHub recovery dispatch and direct Telegram alerts without redeploying the source code.

**Worker deployment checklist:** apply only the idempotent V3.1 CREATE TABLE/INDEX statements from terminal/schema.sql to D1; upload all worker modules worker.js, live.js, outcomes.js, publications.js, watchdog.js; preserve DB and LIVE_ROOM bindings. Enable Cron expressions `*/2 * * * *`, `*/3 * * * *`, and `*/5 * * * *`. Verify /api/watchdog after the first separate 3-minute trigger, plus the existing health/tracking/outcome endpoints. Do not treat a successful Workers upload as verification that GitHub dispatch or Telegram delivery actually occurred.


## ATLAS V3.2–V3.5 Macro & News Intelligence

Existing atlas-market-terminal Worker adds macro.js, D1 macro tables, and the Macro & News dashboard. Reuses */5 * * * * Cron without adding another trigger; existing DB, LIVE_ROOM, scanner, watchdog, outcomes and Telegram relay stay in place.

### V3.2 Collection
Official Federal Reserve monetary-policy & speeches RSS, BLS CPI/jobs/PPI RSS. Supplemental Google News RSS macro/crypto-policy aggregations are explicitly marked aggregator and are never treated as official announcements. XML parser uses safe-URL, official-domain, date, age and duplicate checks; each article links to the original source. Feed health records failed or blocked source fetches. Summaries are limited to the supplied headline and feed description; no full-text paywall scraping.

### V3.3 Impact and AI
Rules classify macro categories and HIGH/MEDIUM/LOW impact. Direction is UNCERTAIN by default, with only POSSIBLE risk-on/off interpretations for unambiguous keywords. There is no invented actual-versus-forecast data or certainty about BTC. Optional Cloudflare Workers AI binding AI uses model @cf/meta/llama-3.1-8b-instruct for up to 6 official/HIGH news summaries per UTC day; every actual AI summary is labeled workers_ai_headline_only. Missing or failing AI uses transparent rule_based text. This call cap does not guarantee account costs remain free; review Workers AI neuron usage.

### V3.4 Market reaction
Track BTC_USDT and ETH_USDT price-level returns in independent 15m/1h/4h/24h windows using MEXC closed candles. Baseline is a full 1m candle that begins after source publication, never a still-forming or pre-publication candle. Values are descriptive returns at specified observation windows, not proof of causation. No auto-trading.

### V3.5 Signal context and Telegram
High-impact news in a four-hour lookback from a sent READY/SWING plan creates macro_signal_context relations POTENTIAL_ALIGNMENT, POTENTIAL_CONFLICT or INDETERMINATE. It does not modify the scanner, risk plan, direction or any executed order.

Only new (<45 minutes old when first ingested) high-impact OFFICIAL articles create macro Telegram alerts, capped at 8/day and handled by existing signed GitHub Actions claim/ack. Historical backfill never triggers "breaking news" alerts. Telegram may lag GitHub Actions scheduling and must not be reported as real-time guaranteed.

### APIs, tests and migration
GET /api/macro?limit=36&impact=HIGH&category=INFLATION&source=bls_cpi; POST /api/macro/alerts/claim and /api/macro/alerts/ack require GitHub OIDC exact workflow verification. Source/audit health fields are part of the macro GET response. Apply only V3.2–V3.5 CREATE IF NOT EXISTS section of terminal/schema.sql on an existing database. Deploy worker.js, live.js, outcomes.js, publications.js, watchdog.js, macro.js and preserve D1 and LIVE_ROOM bindings, optionally add binding {type:ai,name:AI}.

Verify a real official RSS fetch, stored item, correct source URL, price observations, macro-signal context and signed Telegram relay independently. Empty results do not count as a completed news feed integration. Do not fabricate samples. Check usage and MEXC rate limits after adding sources.


### V3.5.1 production feed/AI audit

The first production Cron (2026-11-08 09:00 UTC) successfully fetched 5 official Fed/BLS feeds and inserted 2 real items, but both Google News RSS queries returned HTTP 503. V3.5.1 replaces those unstable sources with SEC official releases RSS, ECB press RSS, CoinDesk editorial RSS and Cointelegraph regulation RSS. SEC/ECB links are source-host-validated; editorial publisher items are clearly tiered aggregator/secondary and filtered for macro relevance. Official Fed/BLS remain the foundation. Subsequent health checks must confirm each replacement separately; a configured feed is not evidence of a successful fetch.

Cloudflare Workers AI returns a structured JSON object from the Workers binding for the chosen model. Initial code treated the object as a string and stored rule-based fallback (2 quota attempts). V3.5.1 parses either object or JSON string, includes tests and re-enriches at most 2 earlier fallback official HIGH items per pass while respecting the 6-call UTC-day D1 cap. This hotfix does not modify any scanner or trade plan. Closed-candle price reactions now avoid an unnecessary additional 15-minute wait for 1-minute horizons.


### V3.5.2 calendar completion and source quality audit

- BLS official iCalendar https://www.bls.gov/schedule/news_release/bls.ics is fetched with a two-hour minimum refresh interval and recorded into macro_calendar_events and macro_calendar_health. CPI, Employment Situation (NFP), PPI, JOLTS, ECI are filtered. Eastern local time and DST are converted to UTC and browser displays both local and UTC. Only verified published schedule records are displayed; no invented forecast/actual numbers. FOMC calendar is not included in this BLS-only feed.
- New endpoint GET /api/macro/calendar provides next scheduled releases and source health; user-facing Macro tab displays the schedule. No new Cloudflare Cron trigger; reuses five-minute source sync.
- Editorial macro classifier now requires relevance from headline rather than descriptive article boilerplate. Official ECB and BLS employment articles are classified by source to avoid false FED_POLICY descriptions.
- Workers AI structured response uses JSON Schema with strict summary_vi and rationale_vi fields and Vietnamese output validation. AI remains quota limited; previous failed summary attempts are not falsely marked as successful. Check persisted summary_method after the next UTC-day quota reset before declaring AI production delivery proven.


### ATLAS V3.5.4 — Verified BLS iCal timezones and scanner Telegram fault isolation

On 2026-11-08, the real BLS iCalendar feed returned 313 events with `DTSTART;TZID=US-Eastern`. Earlier parsing only allowed `US/Eastern` and `America/New_York` and therefore produced no calendar rows. The converter now maps real `US-Eastern` to IANA `America/New_York` with US DST. The new unit test replicates the observed official field, and production D1 must contain an actual future CPI/PPI/jobs event before the calendar feature is called live. Official BLS calendar: https://www.bls.gov/schedule/news_release/bls.ics.

The 2026-11-08 Market Setup Watch scanner computed a full market report but failed when Telegram returned `ReadTimeout`. The safe delivery guard now catches notification transport errors, persists the complete scanner report, and does **not** mark ambiguous/partial Telegram sends as confirmed. On unconfirmed sends, the state retains previously notified intraday/swing signatures so the next scan can retry; duplicate text may still be possible when Telegram accepted a message but its acknowledgment was lost. Error reports expose only the exception class, never URL strings or bot token information. This change does not auto-trade.


## ATLAS V3.5.6 — Vietnam time zone display (ICT, UTC+7)

- The web terminal defaults to **Vietnam time** using the IANA `Asia/Ho_Chi_Minh` time zone, with exact `DD/MM/YYYY HH:mm:ss ICT` formatting. This is independent of the viewer's browser/system clock time zone.
- The top bar includes a **Việt Nam · UTC+7 / UTC · UTC+0** selector, with the choice saved in the browser as `localStorage['atlas.display_time_zone']`. If storage is disabled, the UI remains usable and defaults to ICT on reload.
- A single `formatStamp()` function is used by the live feed, scanner timestamps, signal publications, entry/TP/SL tracking, research journal, macro articles and source health, BLS economic calendar, watchdog and live sidebar clock. Refreshes existing public APIs when switching, without mutating any server records.
- **All source timestamps stay UTC ISO 8601 in D1, Cloudflare Workers, GitHub Actions, Cron, MEXC OHLCV, and outcome calculations.** The timezone control is purely presentation. No scanner rules, candle windows, prices, signals, triggers or Telegram sending schedules are shifted.
- Example: BLS CPI release `2026-11-10T13:30:00Z` appears as `10/11/2026 20:30:00 ICT` by default and `10/11/2026 13:30:00 UTC` when switched. All headlines retain their original UTC publication timestamp in the API.
- Test coverage includes day/year rollover, invalid timestamps, both time zones, timezone selector persistence, dashboard JS syntax and Preview/production HTML smoke checks.


## V3.6: Pair Relationship Lab

- Compare any two MEXC USDT Perpetual instruments (BTC/ZEC, ETH/BTC) from historical CLOSED 1h/4h/1d candles; source: MEXC public futures API. Endpoint: GET /api/relationship?a=BTC&b=ZEC&tf=4h. Requires >=22 common closed price observations.
- For BTC/DXY, DXY is an INDICATIVE RECONSTRUCTED daily six-FX basket (not ICE licensed real-time DXY). ECB euro reference FX rates 90-day XML is primary; Frankfurter redistributing ECB rates is an explicitly labeled fallback. DXY forces timeframe 1D. ECB source has weekday fixings; MEXC closes are grouped by UTC dates, not perfectly synchronized with ECB reference rate instant. Weekends and holidays are not forward filled.
- Metrics: Pearson correlation on matched log returns, 20-bar rolling correlation, beta (A relative to B), index-to-100 price visualization, comparative percentage returns, vol ratio, sample coverage and source disclosure. No inferred causality or automatic trading.
- New /assets/relationship.js is a same-origin classic browser script drawing normalized price and rolling correlation canvases with read-only API fetches. UI has presets for BTC/ZEC, BTC/DXY and ETH/BTC.
- Source failures, invalid symbols/timeframes, mismatched timestamps and constant price histories cannot become fake correlations. Limits: only symbols with available MEXC Futures contracts or ECB proxy DXY; not arbitrary equities or commodities. Test with terminal/tests/relationships.test.mjs and Preview/production smoke.


### V3.6.2 — Searchable Pair Relationship asset dropdowns

Both Asset A and Asset B controls are native `<select>` dropdowns (previously free-text inputs) with independent text-search filters. On first opening the tab, the browser populates both selectors from the same-origin `GET /api/market` live/cached MEXC USDT Futures instruments (more than 1,000), plus an explicit `DXY · ECB reference (1D)` option. `BTC`, `ETH`, `ZEC` and `DXY` remain as safe minimal fallback options when upstream data fails. User selections are preserved when filters change or when the live symbol catalog loads. Preset buttons continue to select BTC/ZEC, BTC/DXY, or ETH/BTC; the selected symbol is still validated by the existing read-only relationship API. Neither the trading scanner, D1 data, market calculations nor the time-zone selector changes. Independent filter inputs are intentionally displayed so 1,000+ native options remain searchable on mobile and desktop.


## V4.0 Research Intelligence — staged read-only add-ons

This build adds `GET /api/intelligence` (D1-backed market diagnostics) and
`GET /api/intelligence/risk?equity=1000&entry=100&stop=98&riskPct=0.5&maxExposurePct=20&direction=LONG`.
The new **V4 Intelligence** tab is read-only except for the user's own hypothetical inputs. All D1 source timestamps remain UTC while the existing website time-zone control is unchanged.

**Implemented data-backed research diagnostics:**
- 24h breadth/BTC+ETH market-regime proxy (scanner context only if <45 minutes old).
- Cross-sectional 24h price + turnover anomaly radar.
- MEXC snapshot funding extremes, explicitly **without** OI, order-flow, smart-money attribution or liquidation map.
- Partial curated 24h sector leadership; unknown tokens are not assigned invented sectors.
- Score bands for monitored signals, explicitly **not** calibrated probabilities.
- Candle-observed TP1-first vs SL-first journal with ambiguity exclusions and insufficient-sample flags.
- Hypothetical risk/position size calculator with stop-direction checks, 0–5% risk input and exposure cap; no fees, gap or liquidation modeling.
- D1 snapshot/scanner/outcome/macro **freshness audit**, not proof that Telegram delivered or a trade filled.
- Module capability audit labeling research proxies and integrations that still need data.

**Already present, reused without duplication:** macro/news calendar and historical reactions; full Pair Relationship Lab with BTC/ZEC, BTC/DXY, correlation and beta; server-push market snapshots; D1 publication and candle outcome tracking; separate Cloudflare/GitHub scanner watchdogs.

**Not shipped as completed V4/V5 capabilities:** order-book liquidation heatmap, verified OI/taker flows, full sector taxonomy, statistically calibrated win-probability engine, strategy OOS tournament, lead/lag prediction, generative AI Copilot, forecast-volatility model, self-adjusting strategy engine, actual account PnL. The API exposes these limitations rather than faking values.

**Safety / deployment:** no order API, scanner logic, Telegram recipients, secrets, Cron, database schema or DO bindings are changed by this patch. Production deployment requires CI, controlled Worker upload with the existing bindings, and smoke checks on /api/intelligence, /api/health and the existing scanner/tracking/macro endpoints. No Worker deployment is implied by a GitHub commit/PR.
