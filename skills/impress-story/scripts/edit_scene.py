#!/usr/bin/env python3
"""Edit one scene or an atomic batch; build and refresh once."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unicodedata


def wrap_title(title, limit=28):
    """Conservative two-line guard for the existing 1060-unit heading area."""
    lines, line, width = [], '', 0
    for ch in title:
        units = 2 if unicodedata.east_asian_width(ch) in ('W', 'F') else 1
        if ch == '\n' or (line and width+units > limit):
            lines.append(line.rstrip())
            line, width = '', 0
            if ch == '\n':
                continue
        line += ch
        width += units
    if line:
        lines.append(line.rstrip())
    if len(lines) > 2:
        raise ValueError('Title needs more than two lines; shorten it or change the layout.')
    return '\n'.join(lines) if len(lines) > 1 else None


def locate(scenes, scene_id=None, page=None, query=None, prefer_next=False):
    if scene_id:
        matches = [s for s in scenes if s['id'] == scene_id]
    elif page:
        pages = [page+1, page] if prefer_next else [page]
        matches = [scenes[n-1] for n in pages if 1 <= n <= len(scenes)]
        if query:
            matches = [s for s in matches if query in json.dumps(s, ensure_ascii=False)]
        matches = matches[:1]
    else:
        matches = [s for s in scenes if query and query in json.dumps(s, ensure_ascii=False)]
    if len(matches) != 1:
        raise ValueError('Cannot identify one scene; use --scene with a stable ID.')
    return matches[0]


def apply_changes(scene, changes):
    allowed = {'title', 'subtitle', 'notes', 'labels', 'asset', 'screenTitle', 'emphasis'}
    if not isinstance(changes, dict) or not changes or set(changes)-allowed:
        raise ValueError('Each edit needs supported, nonempty changes')
    changes = dict(changes)
    if 'labels' in changes and not (isinstance(changes['labels'], list)
                                   and all(isinstance(x, str) for x in changes['labels'])):
        raise ValueError('labels must be a JSON string array')
    for key in ('title', 'subtitle', 'notes', 'screenTitle'):
        if key in changes and not isinstance(changes[key], str):
            raise ValueError(key+' must be a string')
    if 'asset' in changes and not (changes['asset'] is None or isinstance(changes['asset'], str)
        or isinstance(changes['asset'], list) and all(isinstance(x, str) for x in changes['asset'])):
        raise ValueError('asset must be a string, string array or null')
    if all(scene.get(k) == v for k, v in changes.items()):
        return False
    if 'title' in changes and 'screenTitle' not in changes:
        wrapped = wrap_title(changes['title'])
        scene.pop('screenTitle', None)
        if wrapped:
            changes['screenTitle'] = wrapped
    scene.update(changes)
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--project', default=str(Path.cwd()))
    ap.add_argument('--scene')
    ap.add_argument('--batch', help='JSON list of {scene: stable_id, changes: {...}}')
    ap.add_argument('--page', type=int)
    ap.add_argument('--query')
    ap.add_argument('--prefer-next', action='store_true')
    for key in ('title', 'subtitle', 'notes', 'labels', 'asset'):
        ap.add_argument('--'+key)
    ap.add_argument('--set', action='append', default=[], metavar='FIELD=JSON')
    ap.add_argument('--timeout', type=float, default=10)
    args = ap.parse_args()
    root = Path(args.project).resolve()
    source = root / 'content/scenes.json'
    scenes = json.loads(source.read_text())
    changes = {k: getattr(args, k) for k in ('title', 'subtitle', 'notes', 'asset')
               if getattr(args, k) is not None}
    if args.labels is not None:
        changes['labels'] = json.loads(args.labels)
    for item in args.set:
        key, value = item.split('=', 1)
        changes[key] = json.loads(value)
    if args.batch:
        if changes or args.scene or args.page or args.query or args.prefer_next:
            raise ValueError('--batch cannot be mixed with single-scene options')
        edits = json.loads(Path(args.batch).read_text())
        if not isinstance(edits, list) or not edits:
            raise ValueError('Batch must be a nonempty JSON list')
        ids = [e.get('scene') for e in edits if isinstance(e, dict)]
        if len(ids) != len(edits) or any(not isinstance(x, str) for x in ids) or len(set(ids)) != len(ids):
            raise ValueError('Batch requires unique stable scene IDs')
        jobs = [(locate(scenes, scene_id=e['scene']), e.get('changes')) for e in edits]
    else:
        scene = locate(scenes, args.scene, args.page, args.query, args.prefer_next)
        if not changes:
            print(json.dumps(dict(page=scenes.index(scene)+1, scene=scene), ensure_ascii=False, indent=2))
            return
        jobs = [(scene, changes)]
    start = time.perf_counter()
    changed = [scene for scene, patch in jobs if apply_changes(scene, patch)]
    if not changed:
        print(json.dumps(dict(scenes=[scene['id'] for scene, _ in jobs], changed=False), ensure_ascii=False))
        return
    if not any((root/name).is_file() for name in ('build.py', 'verify.py')):
        raise RuntimeError('No build.py or verify.py; configure the project before editing')
    scene = changed[0]
    data = (json.dumps(scenes, ensure_ascii=False, indent=2)+'\n').encode()
    tmp = source.with_suffix('.tmp')
    tmp.write_bytes(data)
    tmp.replace(source)
    expected = hashlib.sha256(data).hexdigest()
    live = None
    state_file = root / '.preview-state.json'
    try:
        live = json.loads(state_file.read_text())
        os.kill(live['pid'], 0)
        if (live['project'] != str(root) or not live.get('serving')
                or live.get('port', 0) <= 0
                or time.time()-live.get('heartbeat_at', 0) > (35 if live.get('busy') else 6)):
            live = None
    except (OSError, ValueError, KeyError):
        live = None
    if live:
        deadline = time.monotonic()+args.timeout
        while time.monotonic() < deadline:
            state = json.loads(state_file.read_text())
            if state.get('scene_hash') == expected and not state['busy'] and not state.get('error'):
                break
            if state.get('error') and not state['busy'] and state.get('attempt_scene_hash') == expected:
                raise RuntimeError(state['error'])
            time.sleep(.03)
        else:
            raise TimeoutError('Preview has not validated this change; check .preview-state.json')
    else:
        for name in ('build.py', 'verify.py'):
            if (root / name).exists():
                subprocess.run([sys.executable, name], cwd=root, check=True, stdout=subprocess.DEVNULL)
    print(json.dumps(dict(scene=scene['id'] if len(changed)==1 else None,
                          scenes=[s['id'] for s in changed],
                          pages=[scenes.index(s)+1 for s in changed],
                          page=scenes.index(scene)+1 if len(changed)==1 else None, changed=True,
                          validated=True, elapsed_ms=round((time.perf_counter()-start)*1000, 2),
                          preview=(live['url']+'#/'+scene['id']) if live else None), ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError, TimeoutError, OSError) as e:
        raise SystemExit(str(e))
