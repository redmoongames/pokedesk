"""Render map-data contact sheets for inspecting every precomputed encounter area."""
from pathlib import Path
import argparse,json,sys,math
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--pillow',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();sys.path.insert(0,str(a.pillow))
from PIL import Image,ImageDraw,ImageFont
atlas=json.loads((ROOT/'vendor/reference/hunt_atlas.json').read_text());rom=json.loads((ROOT/'docs/travel/rom-atlas.json').read_text());a.output.mkdir(parents=True,exist_ok=True)
names=list(atlas['maps']);manifest=[]
for page in range(math.ceil(len(names)/32)):
 sheet=Image.new('RGB',(1600,1120),'#101820');draw=ImageDraw.Draw(sheet)
 for i,name in enumerate(names[page*32:(page+1)*32]):
  col,row=i%8,i//8;x0,y0=col*200,row*280;mapdata=atlas['maps'][name];raw=rom['maps'][name];w,h=mapdata['width'],mapdata['height'];scale=min(190/w,230/h);ox=x0+(200-w*scale)/2;oy=y0+35+(235-h*scale)/2
  draw.text((x0+5,y0+4),name[:29],fill='#e3edf7');draw.text((x0+5,y0+18),f'{w}x{h}',fill='#9fb3c7')
  for y,cells in enumerate(raw['tiles']):
   for x,t in enumerate(cells):
    color='#33495b' if t[0] else '#b7c7c0'
    if 0x10<=t[1]<=0x1c:color='#387cba'
    if t[1]==2 and t[3]:color='#30b260'
    if t[1]==8 and t[3]:color='#ba9b63'
    draw.rectangle((ox+x*scale,oy+y*scale,ox+(x+1)*scale,oy+(y+1)*scale),fill=color)
  for terrain in mapdata['terrain'].values():
   for area in terrain['areas']:
    if area['strips']:
     strip=area['strips'][0];start,end=strip['start'],strip['end'];draw.line((ox+(start[0]+.5)*scale,oy+(start[1]+.5)*scale,ox+(end[0]+.5)*scale,oy+(end[1]+.5)*scale),fill='#ff45c4',width=2)
   for route in terrain['entry_paths'][:3]:
    points=[route['entry'],*route['path']]
    if len(points)>1:draw.line([(ox+(x+.5)*scale,oy+(y+.5)*scale) for x,y in points],fill='#ffe000',width=1)
  draw.rectangle((x0,y0,x0+199,y0+279),outline='#526575');manifest.append(dict(map=name,page=page+1,terrain=list(mapdata['terrain']),areas=sum(len(t['areas']) for t in mapdata['terrain'].values())))
 sheet.save(a.output/f'maps-{page+1:02}.png')
(a.output/'audit.json').write_text(json.dumps(dict(maps=len(names),legend=dict(green='grass',brown='cave encounters',blue='water',pink='long straight encounter strip',yellow='precomputed entry path'),maps_detail=manifest),indent=2));print('Rendered',len(names),'maps in',page+1,'sheets')
