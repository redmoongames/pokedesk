"""One immutable checkpoint, private core, no input or live save writes."""
from pathlib import Path
import sys, json
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pokemon_red.engine import Game
from pokemon_red.installation_versions import wrap_response
from pokemon_red.telemetry import read_state, read_map, read_field_badges
from pokemon_red.models import read_inventory
from pokemon_red.planning_state import planning_grid
from pokemon_red.party_management import roster_plan

if __name__ == '__main__':
    root = Path(sys.argv[1])
    with Game(root) as game:
        state = read_state(game)
        inventory = read_inventory(game)
        inventory['field_badges'] = read_field_badges(game)
        grids = {}
        def provider(name):
            if name not in grids:
                grids[name] = planning_grid(read_map(game, name))
            return grids[name]
        print(json.dumps(wrap_response(roster_plan(root, state, inventory, provider,
                                    json.loads(sys.argv[2]))), ensure_ascii=False), flush=True)
