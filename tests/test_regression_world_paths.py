"""Long directed planning contracts on a fixed real-ROM/world snapshot."""
from pathlib import Path
from types import SimpleNamespace
import shutil
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.engine import Game
from pokemon_red.telemetry import read_state,read_map,read_field_badges
from pokemon_red.models import read_inventory
from pokemon_red.navigation import Navigator


class LongWorldPathTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);(self.root/'Data').mkdir()
        for name in ('native','vendor'):(self.root/name).symlink_to(ROOT/name)
        (self.root/'Data/FireRed.gba').symlink_to(ROOT/'Data/FireRed.gba')
        shutil.copy2(ROOT/'tests/fixtures/fire_red/route5.state',self.root/'Data/FireRed.state')
        self.game=Game(self.root);self.state=read_state(self.game);self.inventory=read_inventory(self.game)
        self.inventory['field_badges']=read_field_badges(self.game)
    def tearDown(self):
        self.game.close();self.temp.cleanup()
    def navigator(self):
        trainer=SimpleNamespace(root=self.root,state=lambda:self.state,bot=SimpleNamespace(map=lambda name=None:read_map(self.game,name)))
        nav=Navigator(trainer);nav.configure_tools(self.inventory,'party');return nav
    def test_route5_to_viridian_and_back_uses_valid_directed_cave_edges(self):
        nav=self.navigator()
        for source,point,destination,goal in [('Route5',(31,32),'ViridianCity_PokemonCenter_1F',(7,4)),('ViridianCity_PokemonCenter_1F',(7,4),'Route5',(31,32))]:
            with self.subTest(source=source):
                plan=nav.plan(source,point,destination,goal)
                self.assertGreaterEqual(len(plan['links']),10)
                self.assertTrue(any(e['destination']=='DiglettsCave_B1F' for e in plan['links']))
                self.assertEqual(plan['links'][0]['source'],source)
                self.assertEqual(plan['links'][-1]['destination'],destination)
                existing={(e['source'],e['destination'],tuple(e['point']),tuple(e['arrival'])) for e in nav.spec['links']}
                for e in plan['links']:self.assertIn((e['source'],e['destination'],tuple(e['point']),tuple(e['arrival'])),existing)
                self.assertEqual(self.game.frame,self.state['frame'],'planning advanced the emulator')

    def test_eastern_road_has_directed_links_to_fuchsia_and_its_clinic(self):
        from pokemon_red.topology import WorldTopology
        nav=self.navigator();topology=WorldTopology(nav.spec['links'])
        for start,goal in [('LavenderTown','FuchsiaCity'),('FuchsiaCity','LavenderTown'),('Route11','FuchsiaCity'),('Route15','FuchsiaCity_PokemonCenter_1F')]:
            self.assertIn(goal,topology.distances(topology.forward,start))
        self.assertEqual(nav.spec['hubs']['Fuchsia']['map'],'FuchsiaCity_PokemonCenter_1F')

    def test_route15_can_prepare_at_fuchsia_and_return_without_advancing_game(self):
        from pokemon_red.travel import navigator,destination_plan
        from pokemon_red.planning_state import planning_grid
        state=dict(self.state,map=dict(name='Route15'),position=dict(x=4,y=11))
        provider=lambda name:planning_grid(read_map(self.game,name))
        nav=navigator(self.root,state,self.inventory,provider)
        permitted=navigator(self.root,state,self.inventory,provider,True)
        frame=self.game.frame
        row=destination_plan(nav,permitted,provider,self.inventory,'FuchsiaCity_PokemonCenter_1F')
        self.assertTrue(row['reachable'],row.get('reason'))
        self.assertEqual(row['legs'][0]['clinic'],'Fuchsia')
        self.assertEqual(row['battles'],0)
        plan=nav.plan('FuchsiaCity_PokemonCenter_1F',(7,4),'Route15',(4,11))
        self.assertTrue(plan['links']);self.assertEqual(self.game.frame,frame)


if __name__=='__main__':unittest.main()
