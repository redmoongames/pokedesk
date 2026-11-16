"""Compile ROM encounter areas, entry polylines and weighted level tables once.
All stored routes are geometry candidates; live NPCs/story/ownership must validate.
"""
from pathlib import Path
from collections import deque
import argparse,hashlib,json,re,sys,time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.engine import Game,ROM_SHA1
from pokemon_red.catalog import catalog
from pokemon_red.telemetry import read_map,maps,symbols
from pokemon_red.portal_graph import PortalGraph
from pokemon_red.zones import zone_spec
from pokemon_red.training import walk_neighbors
from pokemon_red.navigation import safe_grass_pair
from pokemon_red.walking_route import waypoints


def areas(grid,behavior):
    behaviors={behavior} if isinstance(behavior,int) else set(behavior)
    cells={(x,y) for y,row in enumerate(grid['tiles']) for x,tile in enumerate(row) if not tile[0] and tile[1] in behaviors and tile[3]}
    result=[]
    while cells:
        start=min(cells);pending=deque([start]);cells.remove(start);component={start}
        while pending:
            p=pending.popleft()
            for other in walk_neighbors(grid,p,set()):
                if other in cells and p in walk_neighbors(grid,other,set()):cells.remove(other);component.add(other);pending.append(other)
        strips=[]
        for dx,dy in ((1,0),(0,1)):
            for p in sorted(component):
                if (p[0]-dx,p[1]-dy) in component:continue
                line=[];q=p
                while q in component:
                    if line and (q not in walk_neighbors(grid,line[-1],set()) or line[-1] not in walk_neighbors(grid,q,set())):break
                    line.append(q);q=(q[0]+dx,q[1]+dy)
                if len(line)>=2:strips.append(dict(start=line[0],end=line[min(len(line),17)-1],length=min(len(line),17)))
        strips=sorted(strips,key=lambda s:(-s['length'],s['start']))[:64]
        result.append(dict(cells=sorted(component),strips=strips))
    return sorted(result,key=lambda a:(-len(a['cells']),a['cells'][0]))


def main(output):
    began=time.monotonic();data=catalog(ROOT);constants={n:int(v) for n,v in re.findall(r'^#define\s+(SPECIES_\w+)\s+(\d+)\b',(ROOT/'vendor/reference/species.h').read_text(),re.M)}
    wild=json.loads((ROOT/'vendor/reference/wild_encounters.json').read_text());names={v['id']:k for k,v in json.loads((ROOT/'vendor/reference/location_reference.json').read_text())['maps'].items()};entries={}
    for group in wild['wild_encounter_groups']:
        if not group.get('for_maps'):continue
        for record in group['encounters']:
            if 'LeafGreen' in record['base_label']:continue
            name=names.get(record['map'])
            if not name:continue
            for field in group['fields']:
                table=record.get(field['type'])
                if not table:continue
                for method,indexes in (field.get('groups') or {field['type']:range(len(field['encounter_rates']))}).items():
                    population={}
                    for index in indexes:
                        row=table['mons'][index];sid=constants.get(row['species'])
                        if not sid:continue
                        weights=population.setdefault(sid,{})
                        for level in range(row['min_level'],row['max_level']+1):weights[level]=weights.get(level,0)+field['encounter_rates'][index]/(row['max_level']-row['min_level']+1)
                    for sid,levels in population.items():entries.setdefault(str(sid),[]).append(dict(map=name,method=method,encounter_rate=table['encounter_rate'],levels=levels,probability=sum(levels.values())))
    atlas=dict(version=1,rom_sha1=ROM_SHA1,contract='Geometry candidates only; live route and event revalidation required',entries=entries,maps={},species={})
    portals=PortalGraph(zone_spec(ROOT))
    with Game(ROOT,resume=False) as g:
        base=symbols(ROOT)['gSpeciesInfo']
        atlas['species']={key:dict(gender_ratio=g.read8(base+28*int(key)+16),national_id=sp['national_id']) for key,sp in data['species'].items()}
        for name in maps(ROOT).values():
            grid=read_map(g,name)
            if not grid:continue
            plain=dict(grid,objects=[],trainers=[],obstacles=[],script_triggers=[],portal_points=[],warps=[],signs=[],sign_approaches=[])
            terrain={}
            for label,behavior in (('grass',2),('cave',8)):
                found=areas(plain,behavior)
                if found:
                    paths=[]
                    for entry in sorted(portals.nodes.get(name,())):
                        try:
                            farm=safe_grass_pair(plain,entry,terrain=label)
                            paths.append(dict(entry=entry,path=farm['path'],waypoints=waypoints(entry,farm['path']),pair=farm['pair'],strip=farm['strip']))
                        except RuntimeError:pass
                    terrain[label]=dict(areas=found,entry_paths=paths)
            atlas['maps'][name]=dict(width=grid['width'],height=grid['height'],geometry=grid['static_geometry'],terrain=terrain)
    atlas['version_key']=hashlib.sha256((ROOT/'vendor/reference/wild_encounters.json').read_bytes()+Path(__file__).read_bytes()+ROM_SHA1.encode()).hexdigest()[:24]
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(atlas,separators=(',',':'))+'\n')
    print(json.dumps(dict(maps=len(atlas['maps']),encounter_maps=sum(bool(m['terrain']) for m in atlas['maps'].values()),species=len(entries),areas=sum(len(t['areas']) for m in atlas['maps'].values() for t in m['terrain'].values()),entry_paths=sum(len(t['entry_paths']) for m in atlas['maps'].values() for t in m['terrain'].values()),seconds=time.monotonic()-began)))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,default=ROOT/'vendor/reference/hunt_atlas.json');main(p.parse_args().output)
