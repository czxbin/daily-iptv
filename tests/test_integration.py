import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from iptv.playlist import Channel
from iptv.probe import decode_sample, probe

class DecoderIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        p=Path(cls.temp.name)/'sample.ts'
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=160x90:rate=10','-t','1','-c:v','mpeg2video','-f','mpegts',str(p)],check=True,timeout=15)
        cls.sample=p.read_bytes()
    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()
    def test_actually_decodes_a_video_frame(self):
        info=decode_sample(self.sample)
        self.assertEqual(info['decoded_frames'],1)
        self.assertEqual((info['width'],info['height']),(160,90))
    def test_full_hls_probe_resolves_then_decodes_media(self):
        data={'https://example.com/master.m3u8':b'#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=300000\nlow/live.m3u8', 'https://example.com/low/live.m3u8':b'#EXTM3U\n#EXTINF:2,\nchunk.ts','https://example.com/low/chunk.ts':self.sample}
        def get(url,limit,deadline=None): return data[url],url
        with patch('iptv.probe.fetch',side_effect=get):
            result=probe(Channel('Test','https://example.com/master.m3u8'))
        self.assertTrue(result.ok,result.reason)
        self.assertEqual(result.media['decoded_frames'],1)
