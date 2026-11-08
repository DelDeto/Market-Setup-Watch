import unittest
from market_hub.delivery_guard import guarded_notification

class GuardTests(unittest.TestCase):
    def test_success_records_kind(self):
        self.assertEqual(guarded_notification(True,False,lambda: True,lambda: False),
                         (True,"setup_change",None))
    def test_heartbeat_without_setup(self):
        self.assertEqual(guarded_notification(False,True,lambda: False,lambda: True),
                         (True,"heartbeat",None))
    def test_timeout_never_claims_delivery_or_leaks_token(self):
        def fail():
            raise TimeoutError("token-secret-api-URL")
        sent,kind,error=guarded_notification(True,True,fail,lambda:True)
        self.assertEqual((sent,kind,error),(False,"setup_change","TimeoutError"))
        self.assertNotIn("secret",error)
    def test_suppressed_does_not_invoke_sender(self):
        def fail():
            raise RuntimeError("must not be called")
        self.assertEqual(guarded_notification(False,False,fail,fail),(False,None,None))
    def test_no_telegram_credentials_no_confirmed_delivery(self):
        self.assertEqual(guarded_notification(True,False,lambda:False,lambda:True),
                         (False,"setup_change",None))
if __name__ == "__main__":unittest.main()
