"""Compile the LeafGreen encounter/index overlay from pinned original sources."""
from pathlib import Path
import json,hashlib,re,copy,argparse
from build_location_reference import build as build_locations
from build_dex_reference import build as build_dex
ROOT=Path(__file__).resolve().parents[1]

def build(source):
    out=ROOT/'vendor/reference/editions/leafgreen';out.mkdir(parents=True,exist_ok=True)
    reference=build_locations(source,game='LeafGreen');(out/'location_reference.json').write_text(json.dumps(reference,separators=(',',':'))+'\n')
    (out/'dex_availability.json').write_text(json.dumps(build_dex(ROOT,game='LeafGreen'),ensure_ascii=False,separators=(',',':'))+'\n')
    constants={n:int(v) for n,v in re.findall(r'^#define\s+(SPECIES_\w+)\s+(\d+)\b',(ROOT/'vendor/reference/species.h').read_text(),re.M)}
    names={v['id']:k for k,v in reference['maps'].items()};wild=json.loads((ROOT/'vendor/reference/wild_encounters.json').read_text());entries={};routes={}
    existing=json.loads((ROOT/'vendor/reference/grind_routes.json').read_text());atlas=json.loads((ROOT/'vendor/reference/hunt_atlas.json').read_text())
    for group in wild['wild_encounter_groups']:
        if not group.get('for_maps'):continue
        for record in group['encounters']:
            if 'FireRed' in record['base_label']:continue
            name=names.get(record['map'])
            if not name:continue
            for field in group['fields']:
                table=record.get(field['type'])
                if not table:continue
                for method,indexes in (field.get('groups') or {field['type']:range(len(field['encounter_rates']))}).items():
                    pop={};mons=[]
                    for index in indexes:
                        row=table['mons'][index];sid=constants.get(row['species'])
                        if not sid:continue
                        weight=field['encounter_rates'][index];mons.append(dict(species_id=sid,min_level=row['min_level'],max_level=row['max_level'],weight=weight));levels=pop.setdefault(sid,{})
                        for lv in range(row['min_level'],row['max_level']+1):levels[str(lv)]=levels.get(str(lv),0)+weight/(row['max_level']-row['min_level']+1)
                    for sid,levels in pop.items():entries.setdefault(str(sid),[]).append(dict(map=name,method=method,encounter_rate=table['encounter_rate'],levels=levels,probability=sum(levels.values())))
                    if method=='land_mons' and name in existing['routes']:
                        item=copy.deepcopy(existing['routes'][name]);item.update(game='LeafGreen',table=record['base_label'],encounter_rate=table['encounter_rate'],mons=mons,population=[dict(species_id=sid,levels=lv,probability=sum(lv.values()),min_level=min(map(int,lv)),max_level=max(map(int,lv))) for sid,lv in pop.items()]);routes[name]=item
    existing['routes']=routes;(out/'grind_routes.json').write_text(json.dumps(existing,separators=(',',':'))+'\n')
    atlas.update(entries=entries,rom_sha1='7862c67bdecbe21d1d69ce082ce34327e1c6ed5e',geometry_origin='Shared FR/LG layout candidates; every live cell revalidated',version_key=hashlib.sha256((atlas['version_key']+'LeafGreen').encode()).hexdigest()[:24]);(out/'hunt_atlas.json').write_text(json.dumps(atlas,separators=(',',':'))+'\n')
    print(json.dumps(dict(maps=len(reference['maps']),routes=len(routes),wild_species=len(entries))))
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('source',type=Path);build(parser.parse_args().source)
