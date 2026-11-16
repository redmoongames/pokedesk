"""Prove safe Route 2 transit against the actual bundled ROM's map tables."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.engine import Game
from pokemon_red.telemetry import read_map
from pokemon_red.training import path_to,trainer_zones

class RouteMapTests(unittest.TestCase):
    def test_route2_clinic_transit_avoids_grass_and_forest_trainers(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'Data').mkdir();(root/'Data/FireRed.gba').symlink_to(ROOT/'Data/FireRed.gba')
            for name in ('native','vendor'):(root/name).symlink_to(ROOT/name,target_is_directory=True)
            with Game(root,resume=False) as game:
                route=read_map(game,'Route2');self.assertFalse(route['trainers'])
                for start,end in [((12,54),(8,79)),((8,79),(5,52))]:
                    path=path_to(route,start,end)
                    self.assertFalse(any(route['tiles'][y][x][3] for x,y in path))
                farm=path_to(route,(8,79),(6,60))
                self.assertEqual(sum(bool(route['tiles'][y][x][3]) for x,y in farm),1)
                forest=read_map(game,'ViridianForest');self.assertEqual(len(forest['trainers']),5)
                path=path_to(forest,(14,53),(29,61));self.assertFalse(set(path)&trainer_zones(forest))
                # Sammy covers the full narrow northern corridor until defeated.
                with self.assertRaises(RuntimeError):path_to(forest,(6,10),(29,61))
                next(t for t in forest['trainers'] if t['local_id']==5)['defeated']=True
                path=path_to(forest,(6,10),(29,61));self.assertFalse(set(path)&trainer_zones(forest))

    def test_route22_eastern_patch_avoids_scripted_rival_coordinates(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'Data').mkdir();(root/'Data/FireRed.gba').symlink_to(ROOT/'Data/FireRed.gba')
            for name in ('native','vendor'):(root/name).symlink_to(ROOT/name,target_is_directory=True)
            with Game(root,resume=False) as game:
                route=read_map(game,'Route22');self.assertEqual(route['width'],48)
                triggers=set(map(tuple,route['script_triggers']));self.assertTrue({(33,4),(33,5),(33,6)}<=triggers)
                path=path_to(route,(47,7),(38,13));self.assertFalse(set(path)&triggers)
                self.assertEqual(sum(bool(route['tiles'][y][x][3]) for x,y in path),1)
