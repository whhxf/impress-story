"""Focused checks for publication safety and the single-edit path."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from preview import Publisher
from edit_scene import locate, wrap_title
from init_project import initialize
from font_coverage import font_codepoints


class FastEditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root/'AGENTS.md').write_text('Temporary test fixture. content/ holds source JSON; build outputs index.html. Delete with the fixture.\n')
        (self.root/'content').mkdir()
        (self.root/'assets').mkdir()
        self.source = self.root/'content/scenes.json'
        self.source.write_text(json.dumps([dict(id='one', title='Before', asset=None)]))
        (self.root/'build.py').write_text("from pathlib import Path\nimport json\np=Path('.')\ns=json.loads((p/'content/scenes.json').read_text())[0]\n(p/'index.html').write_text('<body>'+s['title']+'</body>')\n")
        (self.root/'verify.py').write_text("from pathlib import Path\nimport json\ns=json.loads(Path('content/scenes.json').read_text())[0]\nassert not s['asset'] or (Path('assets')/s['asset']).exists(),'Missing asset'\n")
        self.pub = Publisher(self.root, 0)
        self.assertTrue(self.pub.compile_publish())

    def tearDown(self):
        self.tmp.cleanup()

    def edit(self, **changes):
        s=json.loads(self.source.read_text())
        s[0].update(changes)
        self.source.write_text(json.dumps(s))

    def test_source_edit_publishes_new_html(self):
        self.edit(title='After')
        self.assertTrue(self.pub.compile_publish())
        self.assertIn(b'After', self.pub.published['index.html'][0])

    def test_rejected_asset_keeps_last_good_snapshot(self):
        previous=self.pub.published.copy()
        self.edit(title='Do not publish', asset='missing.png')
        self.assertFalse(self.pub.compile_publish())
        self.assertEqual(previous, self.pub.published)
        self.assertIn('Missing asset', self.pub.state['error'])

    def test_broken_json_keeps_snapshot_and_recovers(self):
        previous=self.pub.published.copy()
        self.source.write_text('{')
        self.assertFalse(self.pub.compile_publish())
        self.assertEqual(previous, self.pub.published)
        self.source.write_text(json.dumps([dict(id='one', title='Recovered', asset=None)]))
        self.assertTrue(self.pub.compile_publish())
        self.assertIsNone(self.pub.state['error'])
        self.assertIn(b'Recovered', self.pub.published['index.html'][0])

    def test_invalid_javascript_is_not_published(self):
        (self.root/'presentation.js').write_text('function (')
        self.assertFalse(self.pub.compile_publish())
        self.assertNotIn('presentation.js', self.pub.published)

    def test_generated_outputs_do_not_trigger_rebuild_loop(self):
        before=self.pub.fingerprint()
        self.pub.compile_publish()
        self.assertEqual(before, self.pub.fingerprint())

    def test_scene_locator_prefers_next_page_and_uses_content(self):
        scenes=[dict(id='a',title='Alpha'),dict(id='b',title='Beta')]
        self.assertEqual(locate(scenes,page=1,prefer_next=True)['id'],'b')
        self.assertEqual(locate(scenes,page=1,query='Alpha',prefer_next=True)['id'],'a')
        with self.assertRaises(ValueError):
            locate(scenes,query='id')

    def test_edit_command_works_without_preview(self):
        r=subprocess.run([sys.executable,str(ROOT/'scripts/edit_scene.py'),'--project',str(self.root),'--scene','one','--title','欢迎大家'],capture_output=True,text=True)
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertTrue(json.loads(r.stdout)['validated'])
        self.assertIn('欢迎大家',(self.root/'index.html').read_text())

    def batch_command(self, edits):
        edits_file=self.root/'edits.json'
        edits_file.write_text(json.dumps(edits))
        return subprocess.run([sys.executable,str(ROOT/'scripts/edit_scene.py'),'--project',str(self.root),'--batch',str(edits_file)],capture_output=True,text=True)

    def test_batch_updates_two_scenes_and_builds_once(self):
        self.source.write_text(json.dumps([dict(id='one',title='Before',asset=None),dict(id='two',title='Other',asset=None)]))
        f=self.root/'build.py'
        f.write_text(f.read_text()+"\nc=Path('build-count');c.write_text(str(int(c.read_text())+1) if c.exists() else '1')\n")
        r=self.batch_command([dict(scene='one',changes=dict(title='First')),dict(scene='two',changes=dict(subtitle='Second'))])
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(json.loads(r.stdout)['scenes'],['one','two'])
        scenes=json.loads(self.source.read_text())
        self.assertEqual(scenes[0]['title'],'First')
        self.assertEqual(scenes[1]['subtitle'],'Second')
        self.assertEqual((self.root/'build-count').read_text(),'1')

    def test_invalid_batch_leaves_all_source_bytes_unchanged(self):
        before=self.source.read_bytes()
        r=self.batch_command([dict(scene='one',changes=dict(title='Must not save')),dict(scene='missing',changes=dict(subtitle='No'))])
        self.assertNotEqual(r.returncode,0)
        self.assertEqual(self.source.read_bytes(),before)
        r=self.batch_command([dict(scene='one',changes=dict(labels=[7]))])
        self.assertNotEqual(r.returncode,0)
        self.assertEqual(self.source.read_bytes(),before)

    def test_batch_noop_does_not_rebuild(self):
        r=self.batch_command([dict(scene='one',changes=dict(title='Before'))])
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertFalse(json.loads(r.stdout)['changed'])

    def test_no_validator_cannot_claim_success_or_write(self):
        (self.root/'build.py').unlink();(self.root/'verify.py').unlink()
        before=self.source.read_bytes()
        r=self.batch_command([dict(scene='one',changes=dict(title='No'))])
        self.assertNotEqual(r.returncode,0)
        self.assertEqual(self.source.read_bytes(),before)

    def test_initializer_builds_offline_and_refuses_existing_work(self):
        child=self.root/'new-deck'
        result=initialize(child)
        self.assertTrue(result['validated'])
        self.assertTrue((child/'vendor/impress-pinned.js').is_file())
        self.assertTrue((child/'assets/OFL-LXGWWenKaiTC.txt').is_file())
        self.assertIn('window.sceneConfig',(child/'index.html').read_text())
        before=(child/'content/scenes.json').read_bytes()
        with self.assertRaises(ValueError):initialize(child)
        self.assertEqual(before,(child/'content/scenes.json').read_bytes())

    def test_complete_local_font_covers_new_chinese_words(self):
        glyphs=font_codepoints(ROOT/'assets/fonts/LXGWWenKaiTC-Regular.ttf')
        self.assertGreater(len(glyphs),20000)
        self.assertTrue(all(ord(c) in glyphs for c in '欢迎大家一起做产品，赢得客户信任。'))

    def test_long_title_wraps_without_changing_its_words(self):
        title='只有 10% 的外贸老板有做市场的认知'
        wrapped=wrap_title(title)
        self.assertEqual(wrapped.replace('\n',''),title)
        self.assertEqual(wrapped.count('\n'),1)
        self.assertIsNone(wrap_title('我是 Conan。'))
        with self.assertRaises(ValueError):
            wrap_title('这是一个过长的标题'*10)


if __name__=='__main__':
    unittest.main()
