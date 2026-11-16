"""Audit directed farm-to-farm reachability using an isolated save, never writing it.

Use bundled Python: tools/audit_navigation.py --state /copy/FireRed.state --output /tmp/audit.json
The matrix applies actual story/trainer flags. Cut variant requires real ownership
and badge; no_cut is a counterfactual restriction. This is planning, not input replay.
"""
from pathlib import Path
from types import SimpleNamespace
import argparse,json,shutil,sys,tempfile,time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.engine import Game
from pokemon_red.telemetry import read_map,read_state,read_field_badges
from pokemon_red.models import read_inventory
from pokemon_red.navigation import Navigator

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--state',required=True,type=Path);p.add_argument('--output',required=True,type=Path);a=p.parse_args()
    with tempfile.TemporaryDirectory(prefix='Pokemon route audit ') as d:
        root=Path(d);(root/'Data').mkdir();shutil.copy2(a.state,root/'Data/FireRed.state')
        for name in ('vendor','native'):(root/name).symlink_to(ROOT/name)
        (root/'Data/FireRed.gba').symlink_to(ROOT/'Data/FireRed.gba')
        with Game(root) as g:
            inv=read_inventory(g);inv['field_badges']=read_field_badges(g);state=read_state(g);cache={}
            def grid(name=None):
                name=name or state['map']['name']
                if name not in cache:cache[name]=read_map(g,name)
                return cache[name]
            t=SimpleNamespace(root=root,bot=SimpleNamespace(map=grid),state=lambda:state)
            nav=Navigator(t).configure_tools(inv);anchors={};unavailable={};began=time.monotonic()
            for key in nav.spec['zones']:
                try:
                    farm=nav.choose_farm(key);anchors[key]=dict(map=nav.spec['zones'][key]['map'],point=farm['pair'][0],hub=farm['hub'],strip=farm.get('strip',farm['pair']))
                except RuntimeError as e:unavailable[key]=str(e)
            matrices={}
            for mode in ('owned_tools','no_cut'):
                nav=Navigator(t).configure_tools(inv)
                if mode=='no_cut':nav.cut_enabled=False
                rows=[]
                for origin,x in anchors.items():
                    for destination,y in anchors.items():
                        try:
                            plan=nav.plan(x['map'],x['point'],y['map'],y['point'],diagnose=False)
                            row=dict(origin=origin,destination=destination,reachable=True,steps=plan['cost'][1],encounter_tiles=plan['cost'][0],maps=[x['map'],*[e['destination'] for e in plan['links']]],cuts=plan['field_actions'])
                        except RuntimeError as e:row=dict(origin=origin,destination=destination,reachable=False,reason=str(e))
                        rows.append(row)
                    print(mode,origin,'complete',flush=True)
                matrices[mode]=rows
            out=dict(source_frame=state['frame'],source_map=state['map'],badges=inv['field_badges'],cut_available=Navigator(t).configure_tools(inv).cut_enabled,anchors=anchors,unavailable=unavailable,matrices=matrices,seconds=time.monotonic()-began,note='Actual saved flags; representative safe farm anchors only, not proof for every tile or live replay of every pair.')
            a.output.write_text(json.dumps(out,ensure_ascii=False,indent=2))
            print(json.dumps(dict(anchors=len(anchors),unavailable=unavailable,seconds=out['seconds'],reachable={k:sum(r['reachable'] for r in v) for k,v in matrices.items()}),ensure_ascii=False),flush=True)
if __name__=='__main__':main()
