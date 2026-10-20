"""Build freeform SVG scenes over a shared impress.js world; no slide templates."""
from pathlib import Path
import html,json,re,xml.etree.ElementTree as ET
p=Path(__file__).resolve().parent
scenes=json.loads((p/'content/scenes.json').read_text());E=html.escape
assert scenes and len({s['id'] for s in scenes})==len(scenes)
steps=[];reader=[];speech=[]
for s in scenes:
 assert re.fullmatch(r'[a-z][a-z0-9-]*',s['id']),s['id']
 art=s.get('art','');ET.fromstring('<svg xmlns="http://www.w3.org/2000/svg">'+art+'</svg>')
 # art is authored by the agent, not executed from an untrusted attachment.
 heading=''
 if s.get('showTitle',True):
  lines=s.get('screenTitle',s['title']).split('\n');x=s.get('titleX',-520);y=s.get('titleY',-285 if len(lines)>1 else -240);size=s.get('titleSize',60)
  heading=''.join(f'<text x="{x}" y="{y+i*size*1.27}" font-size="{size}">{E(line)}</text>' for i,line in enumerate(lines))
 subtitle=f'<text x="-520" y="-140" font-size="30">{E(s.get("subtitle",""))}</text>' if s.get('subtitle') else ''
 attrs=' '.join(f'data-{k}="{float(s.get(k,1 if k=="scale" else 0))}"' for k in ['x','y','z','scale','rotate-x','rotate-y','rotate-z'])
 svg='<svg class="scene-svg" xmlns="http://www.w3.org/2000/svg" viewBox="-600 -375 1200 750">'+heading+subtitle+art+'</svg>'
 steps.append(f'<section class="step" id="{s["id"]}" {attrs}><h1 tabindex="-1" class="sr-only">{E(s["title"])}</h1>'+svg+'</section>')
 reader.append('<article><h2>'+E(s['title'])+'</h2><p>'+E(s.get('notes','')).replace('\n','<br>')+'</p></article>')
 speech.append('## '+s['id']+' · '+s['title']+'\n\n'+s.get('notes',''))
config=json.dumps(scenes,ensure_ascii=False).replace('</','<\\/')
page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>空间演示</title><link rel="stylesheet" href="styles.css"><body><header><button id="home">地图 ↗</button><div><button id="note-toggle" aria-expanded="false">讲稿</button><button id="mode">阅读版</button></div></header><main id="impress" data-width="1440" data-height="900" data-transition-duration="750">'''+''.join(steps)+'''</main><section id="reader">'''+''.join(reader)+'''</section><aside id="notes" hidden><div id="note-content"></div></aside><footer><button id="prev" aria-label="上一步">←</button><span id="progress"></span><button id="next">下一步 →</button></footer><script>window.sceneConfig='''+config+''';</script><script src="vendor/impress-pinned.js"></script><script src="presentation.js"></script></body></html>'''
(p/'index.html').write_text(page)
(p/'content/speech.md').write_text('# 讲稿\n\n'+'\n\n'.join(speech))
print('Built',len(scenes),'freeform scenes')
