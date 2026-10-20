from pathlib import Path
import json,re,html
from font_coverage import font_codepoints
p=Path(__file__).resolve().parent
scenes=json.loads((p/'content/scenes.json').read_text());ids={s['id'] for s in scenes}
assert scenes and len(ids)==len(scenes)
used=set()
for s in scenes:
 assets=s.get('asset') or []
 for asset in ([assets] if isinstance(assets,str) else assets):assert (p/'assets'/asset).is_file(),asset
 assert float(s.get('scale',1))>0
 art=s.get('art','')
 for target in re.findall(r'data-go=["\x27]([^"\x27]+)',art):assert target in ids,target
 for path in re.findall(r'(?:href|src)=["\x27](assets/[^"\x27]+)',art):assert (p/path).is_file(),path
 used.update(c for c in html.unescape(re.sub('<[^>]*>','',art)+s.get('screenTitle',s['title'])+s.get('subtitle','')) if not c.isspace())
glyphs=font_codepoints(p/'assets/LXGWWenKaiTC-Regular.ttf')
missing=sorted(c for c in used if ord(c) not in glyphs)
assert not missing,'Missing font glyphs: '+''.join(missing)
assert 'SIL OPEN FONT LICENSE' in (p/'assets/OFL-LXGWWenKaiTC.txt').read_text()
print('PASS IDs, targets, local images, font coverage and font license')
