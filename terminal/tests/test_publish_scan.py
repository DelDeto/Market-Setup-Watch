import unittest
from terminal.publish_scan import serialize_publication

class PublicationLedgerTest(unittest.TestCase):
    def setUp(self):
        self.report = {
            'setups': [{
                'symbol': 'BTC_USDT', 'direction': 'short',
                'bucket': 'ENTRY_READY', 'top_pick_rank': 1,
                'selector_tp1': 90.0,
                'position_plan': {'runner_target_price': 80.0},
                'trade_plan': {
                    'execution_ready': True, 'entry_zone': {'lower':98,'upper':100},
                    'stop_loss':105, 'targets':[{'price': 87}]}
            }, {
                'symbol': 'ETH_USDT','direction':'long',
                'bucket': 'NEAR_ENTRY',
                'trade_plan': {'execution_ready': False},
            }]
        }
        self.scan = '2026-11-07T16:00:00Z'
        self.sent = '2026-11-07T16:02:00Z'
    def test_top_pick_tracks_exact_telegram_tp1_not_structural_target(self):
        p=serialize_publication({'symbol':'BTC_USDT','direction':'SHORT','bucket':'ENTRY_READY','mode':'INTRADAY'},self.scan,self.sent,'setup_change',self.report)
        self.assertEqual(p['tp1'],90.0)
        self.assertEqual(p['tp2'],80.0)
        self.assertTrue(p['is_trackable'])
    def test_near_entry_is_journaled_but_never_a_trade(self):
        p=serialize_publication({'symbol':'ETH_USDT','direction':'LONG','bucket':'NEAR_ENTRY','mode':'INTRADAY'},self.scan,self.sent,'setup_change',self.report)
        self.assertFalse(p['is_trackable'])
        self.assertEqual(p['reason'],'PREPARATORY_SIGNAL_NOT_EXECUTION')
    def test_heartbeat_only_references(self):
        p=serialize_publication({'symbol':'BTC_USDT','direction':'SHORT','bucket':'ENTRY_READY','mode':'HEARTBEAT_REFERENCE'},self.scan,self.sent,'heartbeat',self.report)
        self.assertFalse(p['is_trackable'])
    def test_deterministic_pub_id(self):
        msg={'symbol':'BTC_USDT','direction':'SHORT','bucket':'ENTRY_READY','mode':'INTRADAY'}
        a=serialize_publication(msg,self.scan,self.sent,'setup_change',self.report)
        b=serialize_publication(msg,self.scan,self.sent,'setup_change',self.report)
        self.assertEqual(a['id'],b['id'])

if __name__=='__main__': unittest.main()
