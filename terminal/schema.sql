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
