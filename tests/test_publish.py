import json
import tempfile
import unittest
from pathlib import Path
from iptv.playlist import Channel
from iptv.probe import Result
from iptv.publish import publish

def results(n,ok=True):
    return [Result(Channel(f'CCTV-{i}',f'https://example.com/{i}',category='央视',region='CN',source='source').to_dict(),ok,'decoded_video_frame' if ok else 'network_timeout',5,{'decoded_frames':1} if ok else {}) for i in range(n)]

class PublishTests(unittest.TestCase):
    def test_success_publishes_playlist_and_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            report=publish(Path(tmp),results(2),[{'ok':True}], '2026-11-06T00:00:00Z',5)
            self.assertTrue(report['published'])
            self.assertEqual(report['passed'],2)
            self.assertIn('CCTV-0',(Path(tmp)/'live.m3u').read_text())
            self.assertEqual(json.loads((Path(tmp)/'status.json').read_text())['playlist_count'],2)
    def test_all_failed_keeps_previous_bytes_and_last_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp); publish(p,results(2),[{'ok':True}],'2026-11-05T00:00:00Z',3)
            before=(p/'live.m3u').read_bytes()
            report=publish(p,results(0),[{'ok':False}],'2026-11-06T00:00:00Z',3)
            self.assertEqual((p/'live.m3u').read_bytes(),before)
            self.assertFalse(report['published'])
            self.assertTrue(report['stale'])
            self.assertEqual(report['last_success_utc'],'2026-11-05T00:00:00Z')
    def test_first_empty_run_does_not_create_fake_playlist(self):
        with tempfile.TemporaryDirectory() as tmp:
            report=publish(Path(tmp),[],[{'ok':True}],'2026-11-06T00:00:00Z',0)
            self.assertFalse((Path(tmp)/'live.m3u').exists())
            self.assertEqual(report['playlist_count'],0)
    def test_major_drop_or_source_outage_preserves_valid_playlist(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp); publish(p,results(20),[{'ok':True}],'2026-11-05T00:00:00Z',30)
            report=publish(p,results(3),[{'ok':True}],'2026-11-06T00:00:00Z',30)
            self.assertFalse(report['published'])
            self.assertEqual(report['hold_reason'],'large_count_drop')
            report=publish(p,results(20),[{'ok':True}]+[{'ok':False}]*3,'2026-11-07T00:00:00Z',30)
            self.assertEqual(report['hold_reason'],'source_outage')
    def test_history_keeps_only_latest_thirty_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)
            for i in range(35): publish(p,results(2),[{'ok':True}],f'2026-11-06T00:00:{i:02d}Z',2)
            self.assertEqual(len(list((p/'history').glob('*.json'))),30)

if __name__=='__main__': unittest.main()

class CategoryProtectionTests(unittest.TestCase):
    def test_cctv_loss_preserves_cctv_while_international_refreshes(self):
        overseas=Result(Channel('News','https://example.com/news',category='海外',region='US',source='s').to_dict(),True,'decoded_video_frame',5,{'decoded_frames':1})
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)
            publish(p,results(2)+[overseas],[{'ok':True}],'2026-11-05T00:00:00Z',10)
            old=(p/'cctv.m3u').read_bytes()
            report=publish(p,[overseas],[{'ok':True}],'2026-11-06T00:00:00Z',10)
            self.assertTrue(report['published'])
            self.assertTrue(report['stale'])
            self.assertTrue(report['category_status']['央视']['stale'])
            self.assertFalse(report['category_status']['海外']['stale'])
            self.assertEqual(report['category_status']['央视']['last_success_utc'],'2026-11-05T00:00:00Z')
            self.assertEqual((p/'cctv.m3u').read_bytes(),old)
            self.assertIn('旧源',(p/'live.m3u').read_text())
            self.assertEqual(report['playlist_count'],3)
