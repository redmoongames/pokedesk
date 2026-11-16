"""Rebuild offline land encounter tables from pinned FireRed source (no network)."""
from pathlib import Path
import json,re,hashlib
ROOT=Path(__file__).resolve().parents[1]
source=ROOT/'vendor/reference/wild_encounters.json';data=json.loads(source.read_text())['wild_encounter_groups'][0]
constants={m[1]:int(m[2]) for m in re.finditer(r'^#define\s+(SPECIES_\w+)\s+(\d+)\b',(ROOT/'vendor/reference/species.h').read_text(),re.M)}
weights=next(f['encounter_rates'] for f in data['fields'] if f['type']=='land_mons')
def map_key(raw):
    # The supported Kanto outdoor names and their split maps are unambiguous.
    raw=raw.removeprefix('MAP_')
    if raw.startswith('ROUTE'):
        parts=raw.split('_');return parts[0].title()+('_'+'_'.join(p.title() for p in parts[1:]) if len(parts)>1 else '')
    return {'VIRIDIAN_FOREST':'ViridianForest','MT_MOON_1F':'MtMoon_1F','MT_MOON_B1F':'MtMoon_B1F','MT_MOON_B2F':'MtMoon_B2F','DIGLETTS_CAVE_B1F':'DiglettsCave_B1F'}.get(raw)
routes={}
for row in data['encounters']:
    name=map_key(row['map'])
    if not name or 'LeafGreen' in row['base_label'] or 'land_mons' not in row:continue
    info=row['land_mons'];mons=[dict(species_id=constants[m['species']],min_level=m['min_level'],max_level=m['max_level'],weight=w) for w,m in zip(weights,info['mons'])]
    assert len(mons)==12 and sum(m['weight'] for m in mons)==100
    assert name not in routes,(name,'ambiguous land table')
    summary={}
    for m in mons:
        a=summary.setdefault(m['species_id'],dict(species_id=m['species_id'],probability=0,min_level=100,max_level=0,levels={}))
        a['probability']+=m['weight'];a['min_level']=min(a['min_level'],m['min_level']);a['max_level']=max(a['max_level'],m['max_level'])
        for level in range(m['min_level'],m['max_level']+1):a['levels'][str(level)]=a['levels'].get(str(level),0)+m['weight']/(m['max_level']-m['min_level']+1)
    routes[name]=dict(map=name,game='FireRed',terrain='cave' if name.startswith(('MtMoon_','DiglettsCave_')) else 'grass',table=row['base_label'],encounter_rate=info['encounter_rate'],mons=mons,population=sorted(summary.values(),key=lambda a:(-a['probability'],a['species_id'])),grass_scope='same land table for every ordinary encounter tile within this exact map; separate floors and map names keep separate tables')
result=dict(source='https://github.com/pret/pokefirered/blob/ce6406d8c2eaf46d543c8a2606de0c3cb1951982/src/data/wild_encounters.json',source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),mechanics='https://github.com/pret/pokefirered/blob/ce6406d8c2eaf46d543c8a2606de0c3cb1951982/src/wild_encounter.c',probability_note='Species percentages are conditional on a regular land encounter; encounter_rate is an engine parameter, not percent chance per step.',routes=routes)
(ROOT/'vendor/reference/grind_routes.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print('Built',len(routes),'FireRed land tables')
