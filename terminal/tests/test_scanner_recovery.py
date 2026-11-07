import unittest
from terminal.scanner_recovery import needs_recovery

class RecoveryTests(unittest.TestCase):
    def test_healthy_source_no_dispatch(self):
        self.assertFalse(needs_recovery(25*60,[]))
    def test_stale_source_with_recent_run_no_duplicate(self):
        self.assertFalse(needs_recovery(70*60,[35*60,85*60]))
    def test_stale_source_without_recent_run_dispatch(self):
        self.assertTrue(needs_recovery(70*60,[65*60,100*60]))
    def test_no_source_but_recent_run_no_dispatch(self):
        self.assertFalse(needs_recovery(None,[20*60]))
    def test_no_source_and_no_runs_dispatch(self):
        self.assertTrue(needs_recovery(None,[]))
if __name__=='__main__':unittest.main()
