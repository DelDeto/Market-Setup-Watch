import unittest
import sqlite3
import re
from pathlib import Path

SOURCE = (Path(__file__).parents[1] / "worker.js").read_text(encoding="utf-8")
SQL = re.search(r"const SIGNAL_FEED_SQL=`([^\`]+)`;", SOURCE, re.DOTALL)
assert SQL, "Signal Feed SQL not found"

class SignalFeedJoinTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
        CREATE TABLE signals (id TEXT PRIMARY KEY, symbol TEXT, direction TEXT, bucket TEXT, entry_low REAL, entry_high REAL, source_updated_at TEXT, last_seen_at TEXT);
        CREATE TABLE signal_publications (id TEXT PRIMARY KEY, symbol TEXT, direction TEXT, bucket TEXT, scan_at TEXT, sent_at TEXT, is_trackable INTEGER, monitor_id TEXT);
        CREATE TABLE signal_monitors (id TEXT PRIMARY KEY, entry_low REAL, entry_high REAL, stop REAL, tp1 REAL, tp2 REAL, status TEXT, valid_until TEXT);
        """)
        self.db.executemany("INSERT INTO signals VALUES (?,?,?,?,?,?,?,?)", [
            ("matched","KORU_USDT","LONG","ENTRY_READY",7.69,7.82,"scan-1","now"),
            ("old","KORU_USDT","LONG","ENTRY_READY",7.60,7.70,"scan-old","before"),
            ("no-confirm","AVAX_USDT","LONG","DEVELOPING",8.62,8.68,"scan-1","now"),
            ("wrong-zone","BAN_USDT","LONG","ENTRY_READY",0.041,0.042,"scan-1","now"),
        ])
        self.db.executemany("INSERT INTO signal_monitors VALUES (?,?,?,?,?,?,?,?)", [
            ("mon-good",7.69,7.82,7.68,7.91,7.99,"WAIT_ENTRY","future"),
            ("mon-old",7.60,7.70,7.58,7.81,7.90,"EXPIRED","past"),
            ("mon-wrong-zone",0.046,0.047,0.045,0.052,None,"WAIT_ENTRY","future"),
        ])
        self.db.executemany("INSERT INTO signal_publications VALUES (?,?,?,?,?,?,?,?)", [
            ("pub-good","KORU_USDT","LONG","ENTRY_READY","scan-1","sent-1",1,"mon-good"),
            ("pub-old","KORU_USDT","LONG","ENTRY_READY","scan-old","sent-0",1,"mon-old"),
            ("pub-unverified","AVAX_USDT","LONG","DEVELOPING","scan-1","sent-1",0,None),
            ("pub-zone","BAN_USDT","LONG","ENTRY_READY","scan-1","sent-1",1,"mon-wrong-zone"),
        ])

    def test_level_join_is_exact_to_source_publication_and_zone(self):
        rows = {r["id"]: dict(r) for r in self.db.execute(SQL.group(1))}
        self.assertEqual(len(rows),4)
        self.assertEqual(rows["matched"]["stop_loss"],7.68)
        self.assertEqual(rows["matched"]["tp1"],7.91)
        self.assertEqual(rows["matched"]["tp2"],7.99)
        self.assertEqual(rows["matched"]["publication_id"],"pub-good")
        self.assertEqual(rows["old"]["publication_id"],"pub-old")
        self.assertEqual(rows["old"]["stop_loss"],7.58)
        self.assertIsNone(rows["no-confirm"]["stop_loss"])
        self.assertIsNone(rows["wrong-zone"]["stop_loss"])

    def test_display_requires_verified_published_plan(self):
        self.assertIn("x.publication_id&&x.stop_loss!=null&&x.tp1!=null",SOURCE)
        self.assertIn("Not validated",SOURCE)
        self.assertIn("R:R is estimated from the midpoint",SOURCE)

if __name__ == "__main__":
    unittest.main()
