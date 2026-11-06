import unittest
from iptv.probe import public_addresses, hls_target, media_format, ProbeError, decode_sample
from unittest.mock import patch

class ProbeTests(unittest.TestCase):
    def test_private_and_mixed_dns_are_rejected(self):
        for addresses in [('127.0.0.1',), ('8.8.8.8','10.1.2.3'), ('::1',), ('169.254.169.254',)]:
            with patch('socket.getaddrinfo',return_value=[(2,1,6,'',(a,443)) for a in addresses]):
                with self.assertRaises(ProbeError): public_addresses('https://example.com/live')
    def test_public_dns_accepted_and_other_protocol_blocked(self):
        with patch('socket.getaddrinfo',return_value=[(2,1,6,'',('8.8.8.8',443))]):
            self.assertEqual(public_addresses('https://example.com/live'), ['8.8.8.8'])
        with self.assertRaises(ProbeError): public_addresses('file:///etc/passwd')
    def test_master_selects_lower_bandwidth_variant(self):
        target=hls_target('#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=2000\nhigh/a.m3u8\n#EXT-X-STREAM-INF:BANDWIDTH=1000\nlow/a.m3u8','https://example.com/live/master.m3u8')
        self.assertEqual(target,('playlist','https://example.com/live/low/a.m3u8',None))
    def test_media_segment_and_init_resolve_relative_urls(self):
        self.assertEqual(hls_target('#EXTM3U\n#EXT-X-MAP:URI="init.mp4"\n#EXTINF:4,\n1.m4s\n#EXTINF:4,\n2.m4s\n','https://example.com/live/m.m3u8'),('media','https://example.com/live/1.m4s','https://example.com/live/init.mp4'))
    def test_encrypted_empty_byterange_or_vod_are_not_live_candidates(self):
        for manifest in ('#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="key"\n#EXTINF:2,\na.ts','#EXTM3U','#EXTM3U\n#EXT-X-BYTERANGE:2@0\n#EXTINF:2,\na.ts','#EXTM3U\n#EXTINF:2,\na.ts\n#EXT-X-ENDLIST'):
            with self.assertRaises(ProbeError): hls_target(manifest,'https://example.com/x')
    def test_html_is_not_media_and_fake_ts_does_not_decode(self):
        with self.assertRaises(ProbeError): media_format(b'<html>OK</html>')
        with self.assertRaises(ProbeError): decode_sample((b'\x47'+b'\x00'*187)*5)
    def test_recognizes_mp4_and_transport_stream(self):
        self.assertEqual(media_format(b'\x00\x00\x00\x18ftyp'+b'x'*100),'mov')
        self.assertEqual(media_format((b'\x47'+b'x'*187)*5),'mpegts')

if __name__=='__main__': unittest.main()

class HLSStateTests(unittest.TestCase):
    def test_tags_between_extinf_and_segment_are_allowed(self):
        text='#EXTM3U\n#EXTINF:4,\n#EXT-X-PROGRAM-DATE-TIME:2026-11-06T00:00:00Z\nvideo.ts'
        self.assertEqual(hls_target(text,'https://example.com/live.m3u8'),('media','https://example.com/video.ts',None))
    def test_init_map_belongs_to_selected_segment(self):
        text='#EXTM3U\n#EXT-X-MAP:URI="old.mp4"\n#EXTINF:4,\na.m4s\n#EXT-X-MAP:URI="new.mp4"\n#EXTINF:4,\nb.m4s'
        self.assertEqual(hls_target(text,'https://example.com/live.m3u8'),('media','https://example.com/a.m4s','https://example.com/old.mp4'))

class PinnedTransportTests(unittest.TestCase):
    def test_connects_to_validated_ip_not_hostname(self):
        from iptv.probe import open_connection
        from unittest.mock import MagicMock
        sock=MagicMock()
        with patch('socket.create_connection',return_value=sock) as connect:
            connection=open_connection('http://example.com/live',['8.8.8.8'],3)
        connect.assert_called_once_with(('8.8.8.8',80),timeout=3)
        self.assertIs(connection.sock,sock)
