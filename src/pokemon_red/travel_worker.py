"""One read-only reachability pass in a private core, never on the UI thread."""
from pathlib import Path
import sys,json
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from pokemon_red.engine import Game
from pokemon_red.installation_versions import wrap_response
from pokemon_red.telemetry import read_state,read_map,read_field_badges
from pokemon_red.models import read_inventory
from pokemon_red.planning_state import planning_grid
from pokemon_red.travel import destinations

if __name__=='__main__':
    root=Path(sys.argv[1]);allow=sys.argv[2]=='1'
    with Game(root) as g:
        state=read_state(g);inventory=read_inventory(g);inventory['field_badges']=read_field_badges(g);grids={}
        def provider(name):
            if name not in grids:grids[name]=planning_grid(read_map(g,name))
            return grids[name]
        print(json.dumps(wrap_response(destinations(root,state,inventory,provider,allow)),ensure_ascii=False),flush=True)
