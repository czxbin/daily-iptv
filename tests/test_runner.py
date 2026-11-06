import unittest
from unittest.mock import patch
from iptv.runner import load_source, bounded_config

class RunnerTests(unittest.TestCase):
    def test_source_success_parses_metadata(self):
        with patch('iptv.runner.fetch',return_value=(b'#EXTM3U\n#EXTINF:-1 tvg-id="CCTV1.cn@SD",CCTV1\nhttps://example.com/live','https://example.com/source')):
            channels,report=load_source({'name':'test','url':'https://example.com/source','region':'CN'})
        self.assertTrue(report['ok']); self.assertEqual(len(channels),1)
    def test_html_source_is_reported_failed(self):
        with patch('iptv.runner.fetch',return_value=(b'<html>OK</html>','https://example.com/source')):
            channels,report=load_source({'name':'test','url':'https://example.com/source','region':'CN'})
        self.assertFalse(report['ok']); self.assertEqual(channels,[])
    def test_config_rejects_excessive_budget_and_unknown_categories(self):
        for data in ({'workers':100,'quotas':{'央视':10}},{'workers':4,'quotas':{'央视':99999}},{'workers':4,'quotas':{'typo':1}}):
            with self.assertRaises(ValueError): bounded_config(data)

class WallClockProbeTests(unittest.TestCase):
    def test_hard_timeout_is_reported_without_throwing(self):
        import subprocess
        from iptv.runner import bounded_probe
        from iptv.playlist import Channel
        with patch('iptv.runner.subprocess.run',side_effect=subprocess.TimeoutExpired('probe',35)):
            result=bounded_probe(Channel('Test','https://example.com/live'))
        self.assertFalse(result.ok)
        self.assertEqual(result.reason,'probe_wall_timeout')
