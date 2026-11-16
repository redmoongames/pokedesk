"""Read-only capture planner; owns a disposable Game, never UI or live Data."""
from pathlib import Path
from types import SimpleNamespace
import sys,json
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from pokemon_red.engine import Game
from pokemon_red.installation_versions import wrap_response
from pokemon_red.telemetry import read_state,read_map,read_field_badges
from pokemon_red.models import read_inventory
from pokemon_red.player_inventory import read_player_inventory
from pokemon_red.planning_state import planning_grid
from pokemon_red.capture_target import CaptureTarget
from pokemon_red.hunt_planning import HuntPlanner

if __name__=='__main__':
    root=Path(sys.argv[1]);target=CaptureTarget.parse(json.loads(sys.argv[2]),root)
    with Game(root) as game:
        state=read_state(game);inventory=read_inventory(game);inventory['field_badges']=read_field_badges(game);inventory['bag']=read_player_inventory(game);grids={}
        def grid(name):
            if name not in grids:grids[name]=planning_grid(read_map(game,name))
            return grids[name]
        trainer=SimpleNamespace(root=root,state=lambda:state,bot=SimpleNamespace(map=grid))
        rows=HuntPlanner(trainer,inventory).choices(target)
        print(json.dumps(wrap_response(dict(rows=rows,target=target.as_dict(),origin=state['map']['name'],position=state['position'])),ensure_ascii=False),flush=True)
