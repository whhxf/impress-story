#!/usr/bin/env python3
"""Check an actual local font cmap without network or browser dependencies."""
from pathlib import Path
import argparse,json,struct,xml.etree.ElementTree as ET

def font_codepoints(font_path):
 glyphs=set()
 b=font_path.read_bytes();n=struct.unpack_from('>H',b,4)[0];tables={}
 for i in range(n):
  tag,checksum,offset,length=struct.unpack_from('>4sIII',b,12+16*i);tables[tag]=offset
 co=tables[b'cmap'];count=struct.unpack_from('>H',b,co+2)[0]
 for i in range(count):
  platform,encoding,sub=struct.unpack_from('>HHI',b,co+4+i*8);off=co+sub;fmt=struct.unpack_from('>H',b,off)[0]
  if fmt==12:
   ng=struct.unpack_from('>I',b,off+12)[0]
   for j in range(ng):
    start,end,gid=struct.unpack_from('>III',b,off+16+j*12)
    if gid:glyphs.update(range(start,end+1))
  if fmt==4:
   seg=struct.unpack_from('>H',b,off+6)[0]//2;endp=off+14;startp=endp+2*seg+2;deltap=startp+2*seg;rangep=deltap+2*seg
   for j in range(seg):
    end=struct.unpack_from('>H',b,endp+2*j)[0];start=struct.unpack_from('>H',b,startp+2*j)[0];delta=struct.unpack_from('>h',b,deltap+2*j)[0];ro=struct.unpack_from('>H',b,rangep+2*j)[0]
    for cp in range(start,end+1):
     if ro:
      gid=struct.unpack_from('>H',b,rangep+2*j+ro+2*(cp-start))[0];gid=((gid+delta)&65535) if gid else 0
     else:gid=(cp+delta)&65535
     if gid:glyphs.add(cp)
 return glyphs


def main():
 ap=argparse.ArgumentParser(description=__doc__)
 ap.add_argument('--font',default=str(Path(__file__).resolve().parents[1]/'assets/fonts/LXGWWenKaiTC-Regular.ttf'))
 ap.add_argument('--text',default='')
 ap.add_argument('--svg')
 a=ap.parse_args();glyphs=font_codepoints(Path(a.font));text=a.text
 if a.svg:
  root=ET.parse(a.svg).getroot();text+=''.join(''.join(e.itertext()) for e in root.iter() if e.tag.endswith('text'))
 missing=sorted({c for c in text if not c.isspace() and ord(c) not in glyphs})
 print(json.dumps(dict(font=a.font,codepoints=len(glyphs),missing=''.join(missing),ok=not missing),ensure_ascii=False))
 raise SystemExit(bool(missing))

if __name__=='__main__':main()
