"""Compile RS catalog, encounters, portal candidates and collection provenance.
Pinned source only; no writes to any running emulator or trainer save.
"""
from pathlib import Path
import sys,json,hashlib,re,collections
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from build_location_reference import build as build_locations,constants
from build_hunt_atlas import areas
from pokemon_red.editions import RUBY,SAPPHIRE
from pokemon_red.rom_catalog import build as build_catalog
from pokemon_red.telemetry import parse_symbols,read_map,maps
from pokemon_red.engine import Game

def write(path,data):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(data,ensure_ascii=False,separators=(',',':'))+'\n')
def build(source):
 c=constants(source);refs={}
 for spec in (RUBY,SAPPHIRE):
  sy=parse_symbols((ROOT/'vendor/reference'/spec.symbols).read_text());rom=(ROOT/'ROMs'/f'{spec.name}-Rev2.gba').read_bytes();catalog=build_catalog(rom,sy,spec);write(ROOT/'vendor/catalog'/f'{spec.id}.json',catalog)
  reference=build_locations(source,game=spec.name);refs[spec.id]=reference;out=ROOT/'vendor/reference/editions'/spec.id;write(out/'location_reference.json',reference);write(out/'grind_zones.json',dict(version=1,hubs={},zones={},links=[],object_rules=[]))
  write(out/'wild_encounters.json',json.loads((source/'src/data/wild_encounters.json').read_text()))
  write(out/'heal_locations.json',json.loads((source/'src/data/heal_locations.json').read_text()))
  write(out/'world_topology.json',dict(version=1,source=reference['source'],maps={name:dict(symbol=m['id'],region=m['region'],map_type=m['map_type'],navigation='candidate') for name,m in reference['maps'].items()}))
  region=source/'src/data/region_map';sections=json.loads((region/'region_map_sections.json').read_text())['map_sections']
  cells=re.findall(r'MAPSEC_\w+',(region/'region_map_layout.h').read_text())
  if len(cells)!=28*15:raise ValueError('Unexpected Hoenn Town Map dimensions')
  dungeon=[['MAPSEC_NONE']*28 for _ in range(15)]
  for section in sections:
   if section['id'] in cells:continue
   for y in range(section.get('y',0),min(15,section.get('y',0)+section.get('height',0))):
    for x in range(section.get('x',0),min(28,section.get('x',0)+section.get('width',0))):dungeon[y][x]=section['id']
  aliases=dict(re.findall(r'\{\s*(MAPSEC_\w+),\s*(MAPSEC_\w+)\s*\}',(source/'src/region_map.c').read_text()))
  write(out/'region_map.json',dict(version=1,width=28,height=15,source=reference['source'],names={s['id']:s.get('name',s['id']).replace('{NAME_END}','').title() for s in sections},aliases=aliases,pages=dict(hoenn=dict(map=[cells[y*28:(y+1)*28] for y in range(15)],dungeon=dungeon))))
  # Read only ROM map geometry on an independent blank core.
  import tempfile
  with tempfile.TemporaryDirectory(prefix='RS reference ') as tmp:
   folder=Path(tmp);(folder/'Data').mkdir();(folder/'Data/game.json').write_text(json.dumps(dict(game=spec.id)));(folder/'Data/FireRed.gba').symlink_to(ROOT/'ROMs'/f'{spec.name}-Rev2.gba')
   for name in ('native','vendor','assets'):(folder/name).symlink_to(ROOT/name,target_is_directory=True)
   with Game(folder,resume=False) as game:grids={name:read_map(game,name) for name in maps(folder).values()}
  grids={name:g for name,g in grids.items() if g};byid={v['id']:name for name,v in reference['maps'].items()};links=[];hubs={};zones={}
  def walkable(g,p):
   x,y=p
   return 0<=x<g['width'] and 0<=y<g['height'] and g['tiles'][y][x][0]==0 and not (0x10<=g['tiles'][y][x][1]<=0x1c or 0x30<=g['tiles'][y][x][1]<=0x71)
  directions={'up':(0,-1),'down':(0,1),'left':(-1,0),'right':(1,0)}
  for name,g in grids.items():
   m=reference['maps'][name]
   nurses=[o for o in m['objects'] if o['graphics']=='NURSE']
   if nurses:
    nurse=nurses[0]['point'];hubs[name]=dict(label=name.replace('_PokemonCenter_1F',' Center'),map=name,nurse=[nurse[0],nurse[1]+2])
   for warp in g['warps']:
    dest=warp.get('destination');other=grids.get(dest)
    if not other:continue
    target=next((w for w in other['warps'] if w['index']==warp['destination_warp']),None)
    if target is None:continue
    candidates=[((warp['x']-dx,warp['y']-dy),direction.upper()) for direction,(dx,dy) in directions.items() if walkable(g,(warp['x']-dx,warp['y']-dy))]
    if not candidates:continue
    point,direction=candidates[0];arrival=[target['x'],target['y']]
    if not walkable(other,arrival):
     arrival=next(([target['x']+dx,target['y']+dy] for dx,dy in directions.values() if walkable(other,(target['x']+dx,target['y']+dy))),arrival)
    links.append(dict(source=name,point=list(point),direction=direction,destination=dest,arrival=arrival,kind='warp',warp_id=warp['index']))
   for connection in m['connections']:
    direction=connection['direction'];dest=byid.get(connection['map']);other=grids.get(dest)
    if direction not in directions or other is None:continue
    off=int(connection['offset']);vertical=direction in ('up','down');valid=[]
    for k in range(g['width'] if vertical else g['height']):
     point=(k,0 if direction=='up' else g['height']-1) if vertical else (0 if direction=='left' else g['width']-1,k)
     arrival=(k-off,other['height']-1 if direction=='up' else 0) if vertical else (other['width']-1 if direction=='left' else 0,k-off)
     if walkable(g,point) and walkable(other,arrival):valid.append((k,point,arrival))
    # One portal per contiguous traversable boundary, live cells still validate.
    groups=[]
    for v in valid:
     if not groups or v[0]!=groups[-1][-1][0]+1:groups.append([])
     groups[-1].append(v)
    for group in groups:
     _,point,arrival=group[len(group)//2];links.append(dict(source=name,point=list(point),direction=direction.upper(),destination=dest,arrival=list(arrival),kind='connection'))
  adjacency=collections.defaultdict(set)
  for e in links:adjacency[e['source']].add(e['destination'])
  def near_hubs(start):
   queue=collections.deque([(start,0)]);seen={start};found=[]
   while queue:
    name,depth=queue.popleft()
    if name in hubs:found.append(name)
    if depth>=5:continue
    for other in adjacency[name]-seen:seen.add(other);queue.append((other,depth+1))
   return found
  entries={};routes={};atlas=dict(version=1,rom_sha1=spec.sha1,contract='ROM geometry candidates; live events, permissions and NPCs must revalidate',entries=entries,maps={},species={str(k):dict(gender_ratio=rom[sy['gBaseStats']-0x08000000+28*k+16],national_id=v['national_id']) for k,v in catalog['species'].items()})
  for name,g in grids.items():
   terrain={}
   for label,behavior in [('cave' if reference['maps'][name]['map_type']=='MAP_TYPE_UNDERGROUND' else 'grass',g.get('land_encounter_behaviors',[2,8]))]:
    plain=dict(g,objects=[],obstacles=[],trainers=[],script_triggers=[],warps=[],signs=[],sign_approaches=[]);found=areas(plain,behavior)
    if found:terrain[label]=dict(areas=found,entry_paths=[])
   atlas['maps'][name]=dict(width=g['width'],height=g['height'],geometry=g['static_geometry'],terrain=terrain)
  wild=json.loads((source/'src/data/wild_encounters.json').read_text())
  for group in wild['wild_encounter_groups']:
   if not group.get('for_maps'):continue
   for record in group['encounters']:
    if ('Sapphire' if spec==RUBY else 'Ruby') in record['base_label']:continue
    name=byid.get(record['map'])
    if name not in grids:continue
    for field in group['fields']:
     table=record.get(field['type'])
     if not table:continue
     for method,indexes in (field.get('groups') or {field['type']:range(len(field['encounter_rates']))}).items():
      pop={};mons=[]
      for index in indexes:
       row=table['mons'][index];sid=c[row['species']];weight=field['encounter_rates'][index];mons.append(dict(species_id=sid,min_level=row['min_level'],max_level=row['max_level'],weight=weight));levels=pop.setdefault(sid,{})
       for lv in range(row['min_level'],row['max_level']+1):levels[str(lv)]=levels.get(str(lv),0)+weight/(row['max_level']-row['min_level']+1)
      for sid,levels in pop.items():entries.setdefault(str(sid),[]).append(dict(map=name,method=method,encounter_rate=table['encounter_rate'],levels=levels,probability=sum(levels.values())))
      if method=='land_mons':
       terrain='cave' if reference['maps'][name]['map_type']=='MAP_TYPE_UNDERGROUND' else 'grass';routes[name]=dict(game=spec.name,table=record['base_label'],encounter_rate=table['encounter_rate'],terrain=terrain,mons=mons,population=[dict(species_id=sid,levels=lv,probability=sum(lv.values()),min_level=min(map(int,lv)),max_level=max(map(int,lv))) for sid,lv in pop.items()]);zones[name]=dict(label=name,map=name,hubs=near_hubs(name))
  atlas['version_key']=hashlib.sha256((source/'src/data/wild_encounters.json').read_bytes()+spec.sha1.encode()+Path(__file__).read_bytes()).hexdigest()[:24]
  write(out/'hunt_atlas.json',atlas);write(out/'grind_routes.json',dict(source=reference['source'],routes=routes,mechanics='Gen III original ROM',probability_note='Weighted cartridge encounter slots'));write(out/'grind_zones.json',dict(version=1,hubs=hubs,zones=zones,links=links,object_rules=[],source=reference['source'],policy='ROM-derived portal candidates; story/NPC/badge checks remain live; no water or special-movement edges'))
  print(spec.name,len(catalog['species']),len(grids),len(routes),len(links),len(hubs))
 # Provenance: exact wild tables plus gifts/statics and their evolution closure.
 pools={}
 for spec in (RUBY,SAPPHIRE):
  ref=refs[spec.id];pool={}
  for name,m in ref['maps'].items():
   for encounter in m['encounters']:
    for mon in encounter['population']:pool.setdefault(mon['species_id'],dict(method='wild',trade=False))
   for obj in m['objects']:
    for mon in obj['facts']['pokemon']:pool.setdefault(mon['species_id'],dict(method='gift',trade=False,note='Встреча / подарок · '+name))
  for n in (277,280,283):pool[n]=dict(method='gift',trade=False,note='Один из стартовых Pokémon профессора Birch')
  cat=json.loads((ROOT/'vendor/catalog'/f'{spec.id}.json').read_text())
  while True:
   old=len(pool)
   for n,v in list(pool.items()):
    for evo in cat['species'].get(str(n),{}).get('evolutions',[]):pool.setdefault(evo['target'],dict(method='evolution',parent=n,evolution=evo,trade=v['trade'] or evo['method'] in (5,6)))
   if len(pool)==old:break
  pools[spec.id]=pool
 for spec,other in ((RUBY,SAPPHIRE),(SAPPHIRE,RUBY)):
  cat=json.loads((ROOT/'vendor/catalog'/f'{spec.id}.json').read_text());rows={}
  for n,sp in cat['species'].items():
   local=pools[spec.id].get(int(n));remote=pools[other.id].get(int(n));row=dict(national_id=sp['national_id'],category='firered' if local else 'leafgreen' if remote else 'other')
   if local:row.update(local)
   elif remote:row['leafgreen_method']=remote
   else:row['note']='Нужен обмен из совместимой игры поколения III или особое получение.'
   rows[n]=row
  write(ROOT/'vendor/reference/editions'/spec.id/'dex_availability.json',dict(format=1,game=spec.name,species=rows))
if __name__=='__main__':build(Path(sys.argv[1]))
