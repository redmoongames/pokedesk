"""Offline location encounter tables; no engine reads or movement from Tk."""
from functools import lru_cache
from pathlib import Path
from .pokemon_sources import encounter_index
from .capture_target import hunt_atlas
from .editions import edition

@lru_cache(maxsize=8)
def populations(root):
    root=Path(root);game=edition(root)
    if not game.automation:return {}
    result={}
    for number,rows in encounter_index(root,game.name).items():
        for row in rows:result.setdefault(row['map'],{}).setdefault(row['method'],[]).append(dict(row,species_id=number))
    for groups in result.values():
        for rows in groups.values():rows.sort(key=lambda r:(-r['probability'],r['species_id']))
    return result

@lru_cache(maxsize=256)
def land_tiles(root,name):
    terrain=hunt_atlas(Path(root))['maps'].get(name,{}).get('terrain',{})
    return {tuple(p):kind for kind,entry in terrain.items() for area in entry['areas'] for p in area['cells']}
