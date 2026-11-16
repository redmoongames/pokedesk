"""Export exact ROM cells for all maps and precompute reviewed portal corridors.

Supply a copied checkpoint: no save/checkpoint files are written by this tool.
The SQLite paths are conditioned on this save's actual flags and obstacles.
Unreviewed world nodes are descriptive only, never navigation permissions.
"""
from pathlib import Path
from types import SimpleNamespace
import argparse,json,sys,time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.engine import Game,ROM_SHA1
from pokemon_red.telemetry import read_map,read_state,maps
from pokemon_red.navigation import Navigator
from pokemon_red.walking_route import waypoints

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--state',required=True,type=Path);ap.add_argument('--output',required=True,type=Path);a=ap.parse_args();began=time.monotonic()
    atlas=dict(version=1,rom_sha1=ROM_SHA1,tile_format=['collision','behavior','elevation','encounter'],maps={},corridors=[],contract='All ROM cells; only reviewed links are executable. Corridors are save-conditioned, revalidated live; no Surf, cycling, story or trainer unlock inferred.')
    with Game(ROOT,resume=False) as g:
        g.load_state(a.state);state=read_state(g);grids={}
        def grid(name=None):
            name=name or state['map']['name']
            if name not in grids:grids[name]=read_map(g,name)
            return grids[name]
        nav=Navigator(SimpleNamespace(root=ROOT,bot=SimpleNamespace(map=grid),state=lambda:state))
        for name in maps(ROOT).values():
            m=grid(name)
            if not m:continue
            reviewed=nav.portals.nodes[name]
            atlas['maps'][name]=dict(width=m['width'],height=m['height'],geometry=m['static_geometry'],tiles=m['tiles'],reviewed_nodes=sorted(reviewed),warp_nodes=[dict(point=[w['x'],w['y']],kind='warp',status='descriptive') for w in m.get('warps',[])])
        for name,nodes in nav.portals.nodes.items():
            if not nodes:continue
            for start in sorted(nodes):
                for goal in sorted(nodes):
                    if goal==start:continue
                    try:path=nav.local_path(name,start,goal)
                    except RuntimeError:continue
                    atlas['corridors'].append(dict(map=name,start=start,goal=goal,path=path,waypoints=waypoints(start,path)))
            print('Connected',name,len(nodes),'nodes',flush=True)
        atlas.update(reviewed_transitions=nav.spec['links'],source_map=state['map']['name'],seconds=time.monotonic()-began)
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(atlas,separators=(',',':'))+'\n')
    print('Maps',len(atlas['maps']),'corridors',len(atlas['corridors']),'seconds',atlas['seconds'],flush=True)
if __name__=='__main__':main()
