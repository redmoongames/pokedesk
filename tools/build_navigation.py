"""Extend pinned ROM-validated navigation with ordinary Kanto walking routes, including the eastern road to Fuchsia.

Optionally pass the pinned pret/pokefirered checkout; otherwise use the checked-in
map reference and preserve reviewed object rules. No runtime
network dependency; keep the checked-in registry in portable distributions.
"""
from pathlib import Path
import json,re,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.engine import Game
from pokemon_red.telemetry import read_map
from pokemon_red.training import walk_neighbors
SOURCE=Path(sys.argv[1]) if len(sys.argv)>1 else None;PIN='ce6406d8c2eaf46d543c8a2606de0c3cb1951982'
path=ROOT/'vendor/reference/grind_zones.json';spec=json.loads(path.read_text())
# Rebuild only generated links so the reviewed early-game portals retain coordinates.
spec['links']=[e for e in spec['links'] if not e.get('generated')]
extra={f'Route{i}' for i in range(5,12)}|{'Route24','Route25','VermilionCity','LavenderTown','CeladonCity','SaffronCity','SaffronCity_Connection','RockTunnel_1F','RockTunnel_B1F','CeruleanCity_House1'}
extra|={f'UndergroundPath_{x}' for x in ('NorthEntrance','SouthEntrance','NorthSouthTunnel','EastEntrance','WestEntrance','EastWestTunnel')}
extra|={'DiglettsCave_NorthEntrance','DiglettsCave_SouthEntrance','DiglettsCave_B1F','Route2_EastBuilding'}
extra|={f'Route{i}' for i in range(12,16)}|{'Route11_EastEntrance_1F','Route11_EastEntrance_2F','Route12_NorthEntrance_1F','Route12_NorthEntrance_2F','Route12_FishingHouse','Route15_WestEntrance_1F','Route15_WestEntrance_2F','FuchsiaCity'}
extra|={'FuchsiaCity_'+suffix for suffix in ('Mart','SafariZone_Office','Gym','House1','WardensHouse','House2','House3')}
extra|={'Route5_SouthEntrance','Route6_NorthEntrance','Route7_EastEntrance','Route8_WestEntrance'}
centers={'Vermilion':'VermilionCity_PokemonCenter_1F','Lavender':'LavenderTown_PokemonCenter_1F','Celadon':'CeladonCity_PokemonCenter_1F','Saffron':'SaffronCity_PokemonCenter_1F','Route10':'Route10_PokemonCenter_1F','Fuchsia':'FuchsiaCity_PokemonCenter_1F'}
for key,name in centers.items():extra.add(name);spec['hubs'][key]=dict(label=key+' Center',map=name,nurse=[7,4])
for n,hubs in {5:['Cerulean','Vermilion'],6:['Vermilion'],7:['Celadon'],8:['Lavender'],9:['Route10','Cerulean'],10:['Route10','Lavender'],11:['Vermilion']}.items():spec['zones']['Route'+str(n)]=dict(label='Route '+str(n),map='Route'+str(n),hubs=hubs)
spec['zones']['DiglettsCave_B1F']=dict(label='Diglett’s Cave · B1F',map='DiglettsCave_B1F',hubs=['Vermilion','Pewter','Viridian'],terrain='cave')
# Route24/25 are transit only: the player's current location may be north of Cerulean.
names=extra|{e[k] for e in spec['links'] for k in ('source','destination')}
reference=json.loads((ROOT/'vendor/reference/location_reference.json').read_text())['maps']
meta={n:json.loads((SOURCE/'data/maps'/n/'map.json').read_text()) if SOURCE else reference[n] for n in names};ids={m['id']:n for n,m in meta.items()}

def clear(g,p):
 x,y=p
 if not(0<=x<g['width'] and 0<=y<g['height']):return False
 c,b,_,_=g['tiles'][y][x];return not c and not(0x10<=b<=0x1c or 0x30<=b<=0x71)

def approach(g,w):
 x,y=w['x'],w['y'];behavior=g['tiles'][y][x][1]
 # Exterior animated doors and cave openings approach upward; interior exit
 # mats approach downward. Stair tiles are approached from a clear adjacent cell.
 choices=[((x,y+1),'UP'),((x,y-1),'DOWN'),((x-1,y),'RIGHT'),((x+1,y),'LEFT')]
 directional={0x62:2,0x63:3,0x64:0,0x65:1,0x6c:2,0x6d:3,0x6e:2,0x6f:3}
 if behavior in directional:choices=[choices[directional[behavior]]]
 elif y>=g['height']-1:choices=[choices[1],choices[0],*choices[2:]]
 for p,d in choices:
  if clear(g,p):return p,d
 raise ValueError(('No portal approach',w))

with Game(ROOT,resume=False) as game:
 grids={n:read_map(game,n) for n in sorted(names)}
 for name,m in sorted(meta.items()):
  g=grids[name]
  for c in m.get('connections') or []:
   dest=ids.get(c['map'])
   if not dest or name not in extra and dest not in extra:continue
   other=grids[dest];direction=c['direction'].upper();off=c['offset']
   points=[]
   for k in range(g['width'] if direction in ('UP','DOWN') else g['height']):
    if direction=='UP':p=(k,0);a=(k-off,other['height']-1)
    elif direction=='DOWN':p=(k,g['height']-1);a=(k-off,0)
    elif direction=='LEFT':p=(0,k);a=(other['width']-1,k-off)
    else:p=(g['width']-1,k);a=(0,k-off)
    if clear(g,p) and clear(other,a):points.append((p,a))
   # Each contiguous opening gets its own representative. A wide opening cannot
   # conceal an isolated ledge region; keep one representative per four cells.
   run=[];runs=[]
   for pair in points:
    if run and abs(pair[0][0]-run[-1][0][0])+abs(pair[0][1]-run[-1][0][1])!=1:runs.append(run);run=[]
    run.append(pair)
   if run:runs.append(run)
   for run in runs:
    for i in range(0,len(run),4):
     p,a=run[min(i+1,len(run)-1)];spec['links'].append(dict(source=name,point=p,direction=direction,destination=dest,arrival=a,kind='boundary',generated=True))
  for index,w in enumerate(g['warps']):
   if g['tiles'][w['y']][w['x']][1] not in (0x60,0x61,0x62,0x63,0x64,0x65,0x67,0x69,0x6c,0x6d,0x6e,0x6f):continue
   dest=w['destination']
   if dest not in names or name not in extra and dest not in extra:continue
   # Only verified reciprocal/static destinations; dynamic return indices rejected.
   dw=w['destination_warp']
   if dw>=len(grids[dest]['warps']):continue
   destination=grids[dest]['warps'][dw]
   if destination['destination']!=name:continue
   p,d=approach(g,w);a,_=approach(grids[dest],destination)
   edge=dict(source=name,point=p,direction=d,destination=dest,arrival=a,kind='warp',warp_index=index,destination_warp=dw,generated=True)
   if not any(all(e.get(k)==edge[k] for k in ('source','point','direction','destination','arrival')) for e in spec['links']):spec['links'].append(edge)
 # Transition scripts can move a permanent blocking NPC from its ROM template.
 # These declarative rules mirror the pinned source, applied using save flags.
 if SOURCE:
  flags={k:int(v,16) for k,v in re.findall(r'#define\s+(FLAG_\w+)\s+(0x[0-9A-Fa-f]+)',(SOURCE/'include/constants/flags.h').read_text())}
  rules=[]
  for name,m in sorted(meta.items()):
   script=(SOURCE/'data/maps'/name/'scripts.inc').read_text();locals={o.get('local_id'):i+1 for i,o in enumerate(m.get('object_events',[])) if o.get('local_id')}
   for flag,label in re.findall(r'call_if_unset\s+(FLAG_\w+),\s*(\w+)',script):
    if flag not in flags:continue
    body=re.search(r'^'+re.escape(label)+r'::\n(.*?)(?=^\w+::|\Z)',script,re.M|re.S)
    if not body:continue
    for local,x,y in re.findall(r'setobjectxyperm\s+(\w+),\s*(\d+),\s*(\d+)',body[1]):
     if local in locals:rules.append(dict(map=name,local_id=locals[local],flag_unset=flags[flag],x=int(x),y=int(y),reason='Сюжетный проход Cerulean закрыт: сначала получи S.S. Ticket у Билла' if name=='CeruleanCity' else 'Сюжетный проход закрыт · '+name,source=label))
  spec['object_rules']=rules
 spec['version']=5;spec['source']='https://github.com/pret/pokefirered/tree/'+PIN+'/data/maps';spec['policy']='Directed ordinary walking only; live save flags, map-local temp flags and scripted NPC relocation. Re-check every transition, avoid trainer sight and active story triggers. Cut requires Cascade Badge and a provider in the active party; Surf, Fly, guard tea and story interactions require the player. A farm needs a safe clinic round trip.'
 path.write_text(json.dumps(spec,ensure_ascii=False,indent=2)+'\n')
 topology_path=ROOT/'vendor/reference/world_topology.json'
 topology=json.loads(topology_path.read_text());reviewed={e[k] for e in spec['links'] for k in ('source','destination')}
 for name,record in topology['maps'].items():record['navigation']='reviewed' if name in reviewed else 'known_only'
 topology['reviewed_navigation_maps']=len(reviewed)
 topology_path.write_text(json.dumps(topology,ensure_ascii=False,indent=2)+'\n')
 print('Generated',len(spec['zones']),'zones',len(spec['hubs']),'clinics',len(spec['links']),'links',len(names),'maps',len(spec.get('object_rules',[])),'scripted object rules')
