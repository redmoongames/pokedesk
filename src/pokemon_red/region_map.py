"""Offline Town Map coordinates, shared by every floor of a region section."""
from functools import lru_cache
from pathlib import Path
import json
from .pokemon_sources import location_title
from .editions import reference_path

PAGE_NAMES={'hoenn':'Хоэнн','kanto':'Канто','sevii_123':'Севии · острова 1–3','sevii_45':'Севии · острова 4–5','sevii_67':'Севии · острова 6–7'}
ALIASES={'MAPSEC_S_S_ANNE':('MAPSEC_VERMILION_CITY','Корабль S.S. Anne находится в порту Вермилиона.')}
for chamber in ('MONEAN','LIPTOO','WEEPTH','DILFORD','SCUFIB','RIXY','VIAPOIS'):
    ALIASES['MAPSEC_'+chamber+'_CHAMBER']=('MAPSEC_TANOBY_RUINS','Выделены руины Таноби: выбранная палата находится в этом архипелаге.')

@lru_cache(maxsize=8)
def atlas(root):return json.loads(reference_path(root,'region_map.json').read_text())

@lru_cache(maxsize=8)
def topology(root):return json.loads(reference_path(root,'world_topology.json').read_text())['maps']

def positions(layers,section,layer=None):
    return [(x,y) for key,rows in layers.items() if layer is None or key==layer for y,row in enumerate(rows) for x,value in enumerate(row) if value==section]

def section_label(root,section):
    if section=='MAPSEC_INDIGO_PLATEAU':return 'Плато Индиго'
    maps=topology(Path(root))
    # Prefer the outdoor map name for translated town/route names.
    candidates=[n for n,m in maps.items() if m['region']==section and m['map_type'] in ('MAP_TYPE_TOWN','MAP_TYPE_CITY','MAP_TYPE_ROUTE')]
    name=min(candidates,key=lambda n:(n.count('_'),len(n))) if candidates else None
    return location_title(name) if name else atlas(Path(root))['names'].get(section,section.replace('MAPSEC_','').replace('_',' ').title()).title()

def destination(root,name):
    root=Path(root);record=topology(root).get(name)
    if not record:return None
    section=record['region'];target,note=ALIASES.get(section,(atlas(root).get('aliases',{}).get(section,section),''))
    for key,layers in atlas(root)['pages'].items():
        points=sorted(set(positions(layers,target)))
        if not points:continue
        towns=[];seen=set()
        for town,m in topology(root).items():
            if m['map_type'] not in ('MAP_TYPE_TOWN','MAP_TYPE_CITY') or m['region'] in seen:continue
            seen.add(m['region'])
            tp=positions(layers,m['region'],'map')
            if tp:
                distance=min((x-a)**2+(y-b)**2 for x,y in points for a,b in tp)
                towns.append((distance,section_label(root,m['region'])))
        towns=sorted(set(towns))
        return dict(name=name,title=location_title(name),section=section,target=target,page=key,page_title=PAGE_NAMES[key],points=points,
                    note=note,nearby=[label for _,label in towns[:3]])
    return None
