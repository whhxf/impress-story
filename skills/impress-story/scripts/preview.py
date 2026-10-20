#!/usr/bin/env python3
"""Local edit loop: validate, publish a consistent snapshot, reload the same scene.

No third-party packages. Exported index.html stays independent of this server.
"""
import argparse
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit

LIVE_SCRIPT = r"""<script>(()=>{
const key='impress-live-state:'+location.pathname;
try{const s=JSON.parse(sessionStorage.getItem(key)||'null');sessionStorage.removeItem(key);
if(s){if(window.presentationState&&s.reading!==window.presentationState().reading)document.querySelector('#mode')?.click();
for(const id of s.panels||[])if(document.getElementById(id)?.hidden)document.querySelector({'notes':'#note-toggle','resources':'#media-open','chapters':'#chap-toggle'}[id])?.click();
if(s.media){const g=document.querySelector('[data-scene="'+(window.presentationState?.().current||'')+'"]');const b=[...g?.querySelectorAll('[data-media]')||[]].find(b=>b.dataset.media===s.media)||g?.querySelector('[data-media]');b?.dispatchEvent(new MouseEvent('click',{bubbles:true}));}
if(s.reading)requestAnimationFrame(()=>requestAnimationFrame(()=>scrollTo(0,s.scroll||0)));}}
catch{}
let seen=__REVISION__,stopped=false,polling=false,timer;
async function poll(){if(stopped||polling)return;polling=true;try{const r=await fetch('/__revision',{cache:'no-store'}),s=await r.json();
let box=document.getElementById('live-error');if(s.error){if(!box){box=document.createElement('div');box.id='live-error';box.style.cssText='position:fixed;bottom:76px;left:24px;right:24px;z-index:1000;padding:12px 18px;background:#fff3df;color:#652f16;font:15px/1.5 sans-serif;border:1px solid #bd8053';document.body.append(box);}box.textContent='这次修改还没通过检查，仍展示上一版。'+s.error.split('\n').at(-1).slice(0,180);}else box?.remove();
if(s.revision&&s.revision!==seen){stopped=true;try{sessionStorage.setItem(key,JSON.stringify({reading:window.presentationState?.().reading||false,scroll:scrollY,panels:['notes','resources','chapters'].filter(id=>document.getElementById(id)&&!document.getElementById(id).hidden),media:document.querySelector('dialog[open] #large-image')?.getAttribute('src')?.split('/').pop()}));}catch{}location.reload();return;}}
catch{}polling=false;timer=setTimeout(poll,document.hidden?1200:250);}
timer=setTimeout(poll,120);addEventListener('focus',()=>{clearTimeout(timer);poll();});
})();</script>"""


class Publisher:
    def __init__(self, root, port):
        self.root = Path(root).resolve()
        self.port = port
        self.lock = threading.Lock()
        self.published = {}
        self.cache = {}
        self.state = dict(pid=os.getpid(), project=str(self.root), port=port,
                          url=f'http://127.0.0.1:{port}/', revision=None,
                          busy=False, error=None, build_ms=None, built_at=0, serving=False,
                          heartbeat_at=time.time())
        self.state_file = self.root / '.preview-state.json'

    def save_state(self):
        tmp = self.state_file.with_suffix('.tmp')
        tmp.write_text(json.dumps(self.state, ensure_ascii=False))
        tmp.replace(self.state_file)

    def source_files(self):
        for name in ('build.py', 'verify.py', 'styles.css', 'presentation.js'):
            if (self.root / name).is_file():
                yield self.root / name
        if not (self.root / 'build.py').exists():
            yield from self.root.glob('*.html')
        content = self.root / 'content'
        for f in sorted(content.glob('*.json')):
            if f.name != 'assets.json':
                yield f
        if (content / 'script.md').is_file():
            yield content / 'script.md'
        for f in sorted((self.root / 'assets').rglob('*')):
            if f.is_file() and f.name != 'map-motion.svg':
                yield f

    def fingerprint(self):
        h = hashlib.sha256()
        for f in self.source_files():
            stat = f.stat()
            h.update(str(f.relative_to(self.root)).encode())
            if f.suffix in ('.py', '.json', '.js', '.css', '.html', '.md'):
                h.update(f.read_bytes())
            else:
                h.update(f'{stat.st_size}:{stat.st_mtime_ns}'.encode())
        return h.hexdigest()

    def read_cached(self, f):
        stat = f.stat()
        key = (stat.st_size, stat.st_mtime_ns)
        old = self.cache.get(f)
        if old and old[0] == key:
            return old[1], old[2]
        data = f.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        self.cache[f] = (key, data, digest)
        return data, digest

    def compile_publish(self):
        start = time.perf_counter()
        scene_file = self.root / 'content/scenes.json'
        scene_hash = hashlib.sha256(scene_file.read_bytes()).hexdigest() if scene_file.exists() else None
        self.state.update(busy=True, error=None, attempt_scene_hash=scene_hash,
                          heartbeat_at=time.time())
        self.save_state()
        try:
            commands = []
            for name in ('build.py', 'verify.py'):
                if (self.root / name).exists():
                    commands.append([sys.executable, name])
            if shutil.which('node') and (self.root / 'presentation.js').exists():
                commands.append(['node', '--check', 'presentation.js'])
            for cmd in commands:
                r = subprocess.run(cmd, cwd=self.root, capture_output=True,
                                   text=True, timeout=30)
                if r.returncode:
                    raise RuntimeError((r.stderr or r.stdout).strip()[-900:])
            files = [f for f in self.root.iterdir()
                     if f.is_file() and f.suffix in ('.html', '.css', '.js', '.svg')]
            for name in ('assets', 'vendor'):
                files += [f for f in (self.root / name).rglob('*') if f.is_file()]
            pending = {}
            revision = hashlib.sha256()
            for f in sorted(files):
                name = f.relative_to(self.root).as_posix()
                data, digest = self.read_cached(f)
                pending[name] = (data, digest)
                revision.update(name.encode())
                revision.update(digest.encode())
            if 'index.html' not in pending:
                raise RuntimeError('index.html is missing')
            with self.lock:
                self.published = pending
                self.state.update(revision=revision.hexdigest()[:16],
                                  built_at=time.time(), scene_hash=scene_hash, error=None)
        except Exception as e:
            self.state['error'] = str(e)
        finally:
            self.state.update(busy=False,
                              build_ms=round((time.perf_counter()-start)*1000, 2),
                              heartbeat_at=time.time())
            self.save_state()
        return self.state['error'] is None

    def handler(self):
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                path = unquote(urlsplit(self.path).path)
                if path == '/__revision':
                    data = json.dumps(owner.state, ensure_ascii=False).encode()
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json; charset=utf-8')
                    self.send_header('Cache-Control', 'no-store')
                else:
                    name = path.lstrip('/') or 'index.html'
                    with owner.lock:
                        item = owner.published.get(name)
                        rev = owner.state['revision']
                    if not item:
                        self.send_error(404)
                        return
                    data, digest = item
                    if name.endswith('.html'):
                        script = LIVE_SCRIPT.replace('__REVISION__', json.dumps(rev))
                        data = data.replace(b'</body>', script.encode()+b'</body>')
                        digest = hashlib.sha256(data).hexdigest()
                    etag = '"'+digest+'"'
                    if self.headers.get('If-None-Match') == etag:
                        self.send_response(304)
                        self.send_header('ETag', etag)
                        self.end_headers()
                        return
                    self.send_response(200)
                    mime = mimetypes.guess_type(name)[0] or 'application/octet-stream'
                    if name.endswith(('.html', '.css', '.js', '.svg')):
                        mime += '; charset=utf-8'
                    self.send_header('Content-Type', mime)
                    self.send_header('Cache-Control', 'no-cache')
                    self.send_header('ETag', etag)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                try:
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        return Handler

    def watch(self, stop, previous=None):
        previous = previous or self.fingerprint()
        while not stop.wait(.12):
            try:
                if time.time()-self.state['heartbeat_at'] > 2:
                    self.state['heartbeat_at'] = time.time()
                    self.save_state()
                current = self.fingerprint()
                if current == previous:
                    continue
                if stop.wait(.08):
                    break
                previous = self.fingerprint()
                self.compile_publish()
            except OSError:
                continue


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--project', default=str(Path.cwd()))
    ap.add_argument('--port', type=int, default=8767)
    args = ap.parse_args()
    pub = Publisher(args.project, args.port)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), pub.handler())
    pub.port = server.server_address[1]
    pub.state.update(port=pub.port, url=f'http://127.0.0.1:{pub.port}/')
    initial = pub.fingerprint()
    if not pub.compile_publish():
        server.server_close()
        raise SystemExit(pub.state['error'])
    stop = threading.Event()
    pub.state['serving'] = True
    pub.save_state()
    watcher = threading.Thread(target=pub.watch, args=(stop, initial), daemon=True)
    watcher.start()
    def shutdown(*_):
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    print(pub.state['url'], flush=True)
    try:
        server.serve_forever(poll_interval=.1)
    finally:
        stop.set()
        server.server_close()
        try:
            if json.loads(pub.state_file.read_text()).get('pid') == os.getpid():
                pub.state_file.unlink()
        except (OSError, ValueError):
            pass


if __name__ == '__main__':
    main()
