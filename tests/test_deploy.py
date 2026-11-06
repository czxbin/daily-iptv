import json
import tempfile
import unittest
from pathlib import Path
from iptv.deploy import install_artifacts

class DeploymentTests(unittest.TestCase):
    def test_changed_main_preserves_existing_playlist(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp); target=base/'public'; target.mkdir()
            (target/'live.m3u').write_text('newer valid playlist')
            artifacts=base/'artifact';artifacts.mkdir()
            (artifacts/'status.json').write_text(json.dumps({'schema_version':1,'playlist_count':0}))
            with self.assertRaisesRegex(ValueError,'main changed'):
                install_artifacts('a'*40,'b'*40,artifacts,target)
            self.assertEqual((target/'live.m3u').read_text(),'newer valid playlist')
    def test_matching_main_installs_valid_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);artifacts=base/'artifact';artifacts.mkdir()
            (artifacts/'status.json').write_text(json.dumps({'schema_version':1,'playlist_count':1}))
            (artifacts/'live.m3u').write_text('#EXTM3U\n#EXTINF:-1,A\nhttps://example.com/a\n')
            install_artifacts('a'*40,'a'*40,artifacts,base/'public')
            self.assertTrue((base/'public'/'live.m3u').exists())
    def test_claimed_nonempty_list_without_data_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);artifacts=base/'artifact';artifacts.mkdir()
            (artifacts/'status.json').write_text(json.dumps({'schema_version':1,'playlist_count':3}))
            with self.assertRaises(ValueError): install_artifacts('a'*40,'a'*40,artifacts,base/'public')
    def test_unexpected_artifact_filename_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);artifacts=base/'artifact';artifacts.mkdir()
            (artifacts/'status.json').write_text(json.dumps({'schema_version':1,'playlist_count':0}))
            (artifacts/'evil.sh').write_text('echo no')
            with self.assertRaises(ValueError): install_artifacts('a'*40,'a'*40,artifacts,base/'public')
