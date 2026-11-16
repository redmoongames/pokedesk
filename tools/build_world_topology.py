"""Index every pinned ROM map without declaring unverified routes traversable.

Usage: bundled-python tools/build_world_topology.py /path/to/pinned/pokefirered
This index describes topology and script evidence. Navigator uses only reviewed
links from grind_zones.json and actual save/terrain conditions.
"""
from pathlib import Path
import hashlib
import json
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
PIN='ce6406d8c2eaf46d543c8a2606de0c3cb1951982'

def main(source):
    groups=json.loads((ROOT/'vendor/reference/map_groups.json').read_text())
    spec=json.loads((ROOT/'vendor/reference/grind_zones.json').read_text())
    supported={e[k] for e in spec['links'] for k in ('source','destination')}
    by_name={};by_id={};sources={}
    for group,key in enumerate(groups['group_order']):
        for number,name in enumerate(groups[key]):
            path=source/'data/maps'/name/'map.json'
            raw=path.read_bytes();m=json.loads(raw);sources[name]=hashlib.sha256(raw).hexdigest()
            by_name[name]=dict(map_id=[group,number],symbol=m['id'],region=m['region_map_section'],
                map_type=m['map_type'],requires_flash=m['requires_flash'],floor=m.get('floor_number'),
                navigation='reviewed' if name in supported else 'known_only',metadata=m)
            by_id[m['id']]=name
    flags={n:int(v,16) for n,v in re.findall(r'#define\s+(FLAG_\w+)\s+(0x[0-9A-Fa-f]+)',(source/'include/constants/flags.h').read_text())}
    edges=[]
    for name,record in by_name.items():
        m=record.pop('metadata');record['obstacles']=[]
        for i,o in enumerate(m.get('object_events',[]),1):
            script=o.get('script','')
            if script=='EventScript_CutTree' or 'Snorlax' in script:
                record['obstacles'].append(dict(local_id=i,point=[o['x'],o['y']],script=script,
                    hidden_flag=o.get('flag'),hidden_flag_id=flags.get(o.get('flag')),
                    action='cut' if script=='EventScript_CutTree' else 'manual_story_battle',
                    scope='object_or_local_connection'))
        record['coordinate_events']=[dict(point=[e['x'],e['y']],variable=e['var'],value=e['var_value'],script=e['script']) for e in m.get('coord_events',[])]
        for c in m.get('connections') or []:
            edges.append(dict(source=name,destination=by_id.get(c['map']),destination_symbol=c['map'],kind='boundary',direction=c['direction'],offset=c['offset'],status='topology_only'))
        for i,w in enumerate(m.get('warp_events',[])):
            dest=by_id.get(w['dest_map']);index=w['dest_warp_id']
            edges.append(dict(source=name,source_warp=i,point=[w['x'],w['y']],destination=dest,
                destination_symbol=w['dest_map'],destination_warp=index,kind='warp',
                status='topology_only' if dest is not None and str(index).isdigit() and int(index)<127 else 'dynamic_or_scripted'))
    wild=json.loads((ROOT/'vendor/reference/wild_encounters.json').read_text())
    for g in wild['wild_encounter_groups']:
        for row in g.get('encounters',[]):
            name=by_id.get(row['map'])
            if name and 'LeafGreen' not in row['base_label']:
                by_name[name].setdefault('encounter_tables',[]).append(dict(label=row['base_label'],methods=[k for k in row if k.endswith('_mons')]))
    rules=[dict(maps=['Route5_SouthEntrance','Route6_NorthEntrance','Route7_EastEntrance','Route8_WestEntrance'],scope='gate_passage',condition='VAR_MAP_SCENE_ROUTE5_ROUTE6_ROUTE7_ROUTE8_GATES == 1',preparation='Manual Tea conversation; owning Tea alone does not imply passage is already open'),
        dict(maps=['Route16_NorthEntrance_1F','Route17','Route18_EastEntrance_1F'],scope='cycling_passage',condition='Bicycle and supported cycling executor required; guards and forced-bike scripts checked separately'),
        dict(maps=['Route19','Route20','Route21_North','Route21_South'],scope='water_path',condition='Soul Badge + Surf in current party + supported Surf executor; map adjacency alone is insufficient'),
        dict(maps=['RockTunnel_1F','RockTunnel_B1F'],scope='visibility',condition='Flash affects visibility; do not treat requires_flash as a hard walking lock for a RAM navigator')]
    result=dict(version=1,source='https://github.com/pret/pokefirered/tree/'+PIN+'/data/maps',
        contract='Topology-only index. No edge grants navigation permission; local geometry, save conditions and executor support must be proved.',
        maps=by_name,edges=edges,reviewed_navigation_maps=len(supported),map_source_sha256=sources,review_notes=rules)
    path=ROOT/'vendor/reference/world_topology.json';path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print('Indexed',len(by_name),'maps and',len(edges),'declared directed connections;',len(supported),'navigation maps reviewed')

if __name__=='__main__':main(Path(sys.argv[1]))
