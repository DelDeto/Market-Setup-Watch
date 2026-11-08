-- ATLAS Market Terminal: Cloudflare D1 schema (deployed 2026-11-07)
CREATE TABLE IF NOT EXISTS snapshots(id INTEGER PRIMARY KEY CHECK(id=1),fetched_at TEXT NOT NULL,source TEXT NOT NULL,items_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS scanner_snapshots(id INTEGER PRIMARY KEY CHECK(id=1),source_updated_at TEXT,synced_at TEXT NOT NULL,counts_json TEXT NOT NULL,market_context_json TEXT,signatures_json TEXT NOT NULL,swing_json TEXT);
CREATE TABLE IF NOT EXISTS signals(id TEXT PRIMARY KEY,source TEXT NOT NULL,symbol TEXT NOT NULL,direction TEXT NOT NULL,bucket TEXT NOT NULL,entry_low REAL,entry_high REAL,source_updated_at TEXT,first_seen_at TEXT NOT NULL,last_seen_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_signals_last ON signals(last_seen_at DESC);
CREATE TABLE IF NOT EXISTS metrics(id INTEGER PRIMARY KEY CHECK(id=1),closed_samples INTEGER,baseline_win_rate REAL,active INTEGER NOT NULL DEFAULT 0,fetched_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS health(id INTEGER PRIMARY KEY CHECK(id=1),last_success_at TEXT,last_attempt_at TEXT,last_error TEXT,synced_sources TEXT);
CREATE TABLE IF NOT EXISTS research_signals(id TEXT PRIMARY KEY,source TEXT NOT NULL,model TEXT,symbol TEXT NOT NULL,direction TEXT,recorded_at TEXT,outcome_status TEXT,outcome TEXT,entry REAL,stop REAL,tp1 REAL,net_r REAL,detail_json TEXT,imported_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_research_date ON research_signals(recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_research_source ON research_signals(source);
CREATE TABLE IF NOT EXISTS research_sources(source TEXT PRIMARY KEY,updated_at TEXT,imported_at TEXT NOT NULL,total_signals INTEGER,imported_signals INTEGER,closed_signals INTEGER,net_r_sum REAL,last_error TEXT);

-- ATLAS V2 — price-observation only, never exchange executions.
CREATE TABLE IF NOT EXISTS signal_monitors (
 id TEXT PRIMARY KEY,symbol TEXT NOT NULL,source TEXT NOT NULL,
 direction TEXT NOT NULL CHECK(direction IN ('LONG','SHORT')),
 bucket TEXT NOT NULL,score REAL,entry_low REAL NOT NULL,entry_high REAL NOT NULL,
 stop REAL NOT NULL,tp1 REAL NOT NULL,tp2 REAL,
 created_at TEXT NOT NULL,updated_at TEXT NOT NULL,valid_until TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'WAIT_ENTRY',
 last_price REAL,last_tick_at TEXT,entry_observed_at TEXT,tp1_observed_at TEXT,
 tp2_observed_at TEXT,sl_observed_at TEXT,ended_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_signal_monitors_status ON signal_monitors(status,valid_until);
CREATE TABLE IF NOT EXISTS signal_events (
 id TEXT PRIMARY KEY,signal_id TEXT NOT NULL,kind TEXT NOT NULL,symbol TEXT NOT NULL,
 direction TEXT NOT NULL,observed_price REAL,observed_at TEXT NOT NULL,
 details_json TEXT NOT NULL DEFAULT '{}',delivery_status TEXT NOT NULL DEFAULT 'pending',
 leased_until TEXT,delivered_at TEXT,UNIQUE(signal_id,kind)
);
CREATE INDEX IF NOT EXISTS idx_signal_events_delivery ON signal_events(delivery_status,observed_at);
CREATE TABLE IF NOT EXISTS live_feed_health (
 id INTEGER PRIMARY KEY CHECK(id=1),updated_at TEXT,mode TEXT,last_error TEXT,instrument_count INTEGER
);


-- ATLAS V3: upgrade existing V2 schema in-place (ALTER statements apply once).
CREATE TABLE IF NOT EXISTS signal_publications (
 id TEXT PRIMARY KEY,source TEXT NOT NULL,symbol TEXT NOT NULL,
 direction TEXT NOT NULL,bucket TEXT NOT NULL,
 notification_kind TEXT NOT NULL,scan_at TEXT NOT NULL,sent_at TEXT NOT NULL,
 is_trackable INTEGER NOT NULL DEFAULT 0,eligibility_reason TEXT NOT NULL,
 monitor_id TEXT,entry_low REAL,entry_high REAL,stop REAL,tp1 REAL,tp2 REAL,
 received_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_publications_sent ON signal_publications(sent_at DESC);
CREATE INDEX IF NOT EXISTS idx_publications_bucket ON signal_publications(bucket,source);
ALTER TABLE signal_monitors ADD COLUMN last_candle_at TEXT;
ALTER TABLE signal_monitors ADD COLUMN outcome_quality TEXT;
ALTER TABLE signal_monitors ADD COLUMN monitor_error TEXT;
CREATE TABLE IF NOT EXISTS outcome_health (
 id INTEGER PRIMARY KEY CHECK(id=1),last_attempt_at TEXT,last_success_at TEXT,
 last_error TEXT,evaluated_count INTEGER NOT NULL DEFAULT 0,
 pending_count INTEGER NOT NULL DEFAULT 0,scanned_candles INTEGER NOT NULL DEFAULT 0
);


-- ATLAS V3.1: independent Cloudflare Cron scanner watchdog.
-- These CREATE statements are idempotent and may be safely applied to existing D1.
CREATE TABLE IF NOT EXISTS watchdog_state (
 id INTEGER PRIMARY KEY CHECK(id=1),
 checked_at TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('OK','STALE')),
 scanner_source_at TEXT,
 scanner_age_seconds INTEGER,
 last_healthy_at TEXT,
 github_checked_at TEXT,
 github_run_at TEXT,
 github_run_status TEXT,
 last_dispatch_at TEXT,
 last_dispatch_status TEXT,
 last_dispatch_error TEXT,
 direct_recovery_configured INTEGER NOT NULL DEFAULT 0,
 direct_telegram_configured INTEGER NOT NULL DEFAULT 0,
 note TEXT
);
CREATE TABLE IF NOT EXISTS watchdog_notifications (
 id TEXT PRIMARY KEY,
 kind TEXT NOT NULL,
 created_at TEXT NOT NULL,
 source_at TEXT,
 message TEXT NOT NULL,
 delivery_status TEXT NOT NULL DEFAULT 'pending',
 leased_until TEXT,
 delivered_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_watchdog_delivery ON watchdog_notifications(delivery_status,created_at);
CREATE INDEX IF NOT EXISTS idx_watchdog_kind ON watchdog_notifications(kind,created_at DESC);


-- ATLAS V3.2–V3.5: Macro/news archive, source health, real market response and context.
-- All statements below are CREATE IF NOT EXISTS, idempotent on existing D1.
CREATE TABLE IF NOT EXISTS macro_news (
 id TEXT PRIMARY KEY,source_key TEXT NOT NULL,source_name TEXT NOT NULL,
 tier TEXT NOT NULL CHECK(tier IN ('official','aggregator')),
 title TEXT NOT NULL,source_url TEXT NOT NULL UNIQUE,description TEXT,
 published_at TEXT NOT NULL,ingested_at TEXT NOT NULL,
 category TEXT NOT NULL,impact TEXT NOT NULL,bias TEXT NOT NULL,confidence TEXT NOT NULL,
 summary_vi TEXT NOT NULL,rationale_vi TEXT NOT NULL,
 summary_method TEXT NOT NULL,forecast_available INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_macro_date ON macro_news(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_macro_impact ON macro_news(impact,published_at DESC);
CREATE TABLE IF NOT EXISTS macro_feed_health (
 source_key TEXT PRIMARY KEY,source_name TEXT NOT NULL,tier TEXT NOT NULL,
 last_attempt_at TEXT NOT NULL,last_success_at TEXT,last_error TEXT,new_count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS macro_ai_usage (date TEXT PRIMARY KEY,calls INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS macro_engine_health (
 id INTEGER PRIMARY KEY CHECK(id=1),checked_at TEXT,
 source_success INTEGER,source_total INTEGER,new_count INTEGER,latest_error TEXT
);
CREATE TABLE IF NOT EXISTS macro_reactions (
 news_id TEXT NOT NULL,symbol TEXT NOT NULL,horizon TEXT NOT NULL CHECK(horizon IN ('15m','1h','4h','24h')),
 baseline_at TEXT NOT NULL,baseline_price REAL NOT NULL,
 observed_at TEXT NOT NULL,observed_price REAL NOT NULL,
 change_pct REAL NOT NULL,computed_at TEXT NOT NULL,method TEXT NOT NULL,
 PRIMARY KEY(news_id,symbol,horizon)
);
CREATE INDEX IF NOT EXISTS idx_macro_react_news ON macro_reactions(news_id);
CREATE TABLE IF NOT EXISTS macro_signal_context (
 signal_id TEXT NOT NULL,news_id TEXT NOT NULL,relation TEXT NOT NULL,linked_at TEXT NOT NULL,
 PRIMARY KEY(signal_id,news_id)
);
CREATE TABLE IF NOT EXISTS macro_alerts (
 id TEXT PRIMARY KEY,news_id TEXT NOT NULL UNIQUE,created_at TEXT NOT NULL,
 message TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',
 leased_until TEXT,delivered_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_macro_alert_status ON macro_alerts(status,created_at);
