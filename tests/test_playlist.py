import unittest
from datetime import date
from iptv.playlist import parse_m3u, classify, select_candidates, render_m3u

class PlaylistTests(unittest.TestCase):
    def test_parse_preserves_unicode_and_comma_names(self):
        items = parse_m3u('#EXTM3U\n#EXTINF:-1 tvg-id="CCTV1.cn" tvg-logo="https://example.com/a.png",央视,综合\nhttps://example.com/a.m3u8\n', 'source', 'CN')
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].name, '央视,综合')
        self.assertEqual(items[0].category, '央视')
        self.assertEqual(items[0].source, 'source')
    def test_rejects_modified_authenticated_or_unsupported_urls(self):
        for url in ('rtmp://example.com/a', 'https://u:p@example.com/a', 'https://example.com/a|User-Agent=x', 'file:///etc/passwd'):
            self.assertEqual(parse_m3u('#EXTM3U\n#EXTINF:-1,X\n'+url, 's', 'CN'), [])
    def test_category_uses_region_and_name(self):
        self.assertEqual(classify('CCTV-13 新闻', 'CCTV13.cn', 'CN'), '央视')
        self.assertEqual(classify('凤凰卫视', 'Phoenix.hk', 'HK'), '港澳台')
        self.assertEqual(classify('湖南卫视', 'Hunan.cn', 'CN'), '卫视')
        self.assertEqual(classify('BBC News', 'BBCNews.uk', 'GB'), '海外')
    def test_round_robin_caps_duplicates_and_is_deterministic(self):
        text = '#EXTM3U\n' + ''.join(f'#EXTINF:-1 tvg-id="CCTV{i//3}.cn",CCTV {i//3}\nhttps://example.com/{i}.m3u8\n' for i in range(90))
        items = parse_m3u(text, 's', 'CN')
        selected = select_candidates(items+items, {'央视': 10}, date(2026,11,6), 2)
        self.assertEqual(len(selected), 10)
        self.assertEqual(selected, select_candidates(items, {'央视': 10}, date(2026,11,6), 2))
        self.assertNotEqual(selected, select_candidates(items, {'央视': 10}, date(2026,11,7), 2))
        self.assertEqual(len(set(i.url for i in selected)), 10)
    def test_render_does_not_inject_m3u_directives(self):
        item = parse_m3u('#EXTM3U\n#EXTINF:-1 tvg-id="x",Name\nhttps://example.com/a', 's','US')[0]
        item.name = 'Bad\n#EXTVLCOPT:evil'
        out = render_m3u([item], '2026-11-06T00:00:00Z')
        self.assertEqual(out.count('\n#EXTVLCOPT'),0)
        self.assertIn('group-title="海外"',out)
        self.assertTrue(out.startswith('#EXTM3U\n'))

if __name__ == '__main__': unittest.main()

class ModernIdTests(unittest.TestCase):
    def test_region_suffix_and_variant_key(self):
        items=parse_m3u('#EXTM3U\n#EXTINF:-1 tvg-id="ABNChina.us@SD",ABN China\nhttps://example.com/a\n#EXTINF:-1 tvg-id="HunanTV.cn@HD",Hunan TV\nhttps://example.com/b\n','s','CN')
        self.assertEqual(items[0].region,'US')
        self.assertEqual(items[0].category,'海外')
        self.assertEqual(items[1].category,'卫视')

class SatelliteIdsTests(unittest.TestCase):
    def test_known_provincial_ids(self):
        for name in ('ZhejiangTV','BeijingTV','JiangsuTV','ShandongTV','AnhuiTV','HenanTV','JiangxiTV','HubeiTV','SichuanTV','GuangxiTV'):
            self.assertEqual(classify(name,name+'.cn@HD','CN'),'卫视')
