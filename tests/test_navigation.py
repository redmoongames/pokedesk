"""Portal routing, encounter versioning and safe farming use real ROM data."""
from pathlib import Path
import sys,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.engine import Game
from pokemon_red.telemetry import read_map
from pokemon_red.navigation import Navigator,safe_grass_pair
from pokemon_red.catalog import catalog
from pokemon_red.zones import SUPPORTED,zone_spec
from pokemon_red.planning import make_plan
from test_grind import mon

class NavigationTests(unittest.TestCase):
    def test_supported_registry_and_fire_red_encounter_probabilities(self):
        data=catalog();self.assertEqual(len(SUPPORTED),17)
        for key in SUPPORTED:
            entry=data['routes'][key];self.assertIn('FireRed',entry['table']);self.assertNotIn('LeafGreen',entry['table']);self.assertEqual(sum(m['weight'] for m in entry['mons']),100);self.assertAlmostEqual(sum(m['probability'] for m in entry['population']),100)
        three={m['species_id']:m for m in data['routes']['Route3']['population']};self.assertEqual(three[21]['probability'],35);self.assertEqual(three[39]['probability'],10);self.assertEqual((three[39]['min_level'],three[39]['max_level']),(3,7))
        forest={m['species_id']:m['probability'] for m in data['routes']['ViridianForest']['population']};self.assertEqual(forest[25],5);self.assertEqual(forest[10],40)
    def test_team_prefers_six_owned_members_and_four_real_attackers(self):
        team=[mon(11,8,'target',[106]),mon(19,10,'rat',[98],ability_id=50),mon(25,14,'p',[84]),mon(21,16,'s',[64]),mon(12,14,'b',[93]),mon(56,14,'m',[2]),mon(1,13,'v',[22])]
        inventory=dict(ready=True,party=team[:6],boxes=[dict(team[6],location='box')]);plan=make_plan(inventory,dict(route='Route3',strategy='switch',trainee='target',target=15),ROOT)
        self.assertEqual(len(plan['team']),6);self.assertEqual(len(plan['fighters']),4);self.assertNotIn('rat',plan['fighters']);self.assertNotIn('target',plan['fighters'])
        solo=make_plan(inventory,dict(route='ViridianForest',strategy='solo',trainee='s',target=20),ROOT);self.assertEqual(len(solo['team']),6);self.assertEqual(solo['fighters'],['s']);self.assertEqual(len(solo['reserves']),4)
    def test_real_map_graph_finds_moon_clinic_and_forest_farm_without_trainers(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'Data').mkdir();(root/'Data/FireRed.gba').symlink_to(ROOT/'Data/FireRed.gba')
            for name in ('vendor','native'):(root/name).symlink_to(ROOT/name)
            with Game(root,resume=False) as game:
                class Client:
                    def map(self,name=None):return read_map(game,name)
                class Trainer:
                    def __init__(self):self.root=root;self.bot=Client()
                    def state(self):return dict(map={'name':'Route4_PokemonCenter_1F'},position={'x':7,'y':4})
                nav=Navigator(Trainer());nearest,_=nav.nearest_clinic();self.assertEqual(nearest,'MtMoon');farm=nav.choose_farm('Route3');self.assertEqual(farm['hub'],'MtMoon');self.assertGreater(farm['pair'][0][0],60)
                # No trainer flags are defeated in a fresh fixture. Northern
                # forest grass is still reachable from Pewter without crossing Sammy.
                class ForestTrainer(Trainer):
                    def state(self):return dict(map={'name':'PewterCity_PokemonCenter_1F'},position={'x':7,'y':4})
                f=Navigator(ForestTrainer()).choose_farm('ViridianForest');self.assertEqual(f['hub'],'Pewter');self.assertLess(f['pair'][0][1],22)
                city=read_map(game,'PewterCity');self.assertIn([20,31],city['sign_approaches'])
                # The tile is usable from the side; arriving northward reads the sign.
                from pokemon_red.training import walk_neighbors
                self.assertNotIn((20,31),list(walk_neighbors(city,(20,32),set())))
                self.assertIn((20,31),list(walk_neighbors(city,(19,31),set())))

    def test_floor_tables_and_exact_level_gaps(self):
        from pokemon_red.encounters import level_label
        data=catalog()['routes'];self.assertEqual(len(data),29)
        one={m['species_id']:m for m in data['MtMoon_1F']['population']}
        middle={m['species_id']:m for m in data['MtMoon_B1F']['population']}
        lower={m['species_id']:m for m in data['MtMoon_B2F']['population']}
        self.assertEqual(one[41]['probability'],69);self.assertEqual(middle[46]['probability'],100);self.assertEqual(lower[35]['probability'],6)
        self.assertEqual(level_label(dict(levels={'3':1,'5':5,'7':4})), '3, 5, 7')

    def test_ledge_is_directed_and_floor_nodes_remain_disconnected(self):
        from pokemon_red.training import path_to
        grid=dict(width=3,height=1,obstacles=[],tiles=[[[0,0,3,0],[1,0x38,0,0],[0,0,3,0]]])
        self.assertEqual(path_to(grid,(0,0),(2,0)),[(2,0)])
        with self.assertRaises(RuntimeError):path_to(grid,(2,0),(0,0))
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'Data').mkdir();(root/'Data/FireRed.gba').symlink_to(ROOT/'Data/FireRed.gba')
            for name in ('vendor','native'):(root/name).symlink_to(ROOT/name)
            with Game(root,resume=False) as game:
                class Client:
                    def map(self,name=None):return read_map(game,name)
                class Trainer:
                    def __init__(self):self.root=root;self.bot=Client()
                    def state(self):return dict(map={'name':'Route4_PokemonCenter_1F'},position={'x':7,'y':4})
                nav=Navigator(Trainer())
                for floor in ('1F','B1F','B2F'):
                    farm=nav.choose_farm('MtMoon_'+floor);self.assertEqual(farm['hub'],'MtMoon')
                    self.assertTrue(nav.plan(farm['map'],farm['pair'][0],'Route4_PokemonCenter_1F',(7,4))['links'])
                # Eastern Route4 can reach Cerulean, but cannot walk back up its ledges.
                self.assertTrue(nav.plan('Route4',(85,17),'CeruleanCity_PokemonCenter_1F',(7,4))['links'])
                with self.assertRaises(RuntimeError):nav.plan('Route4',(85,17),'Route1',(12,0))

    def test_route4_after_story_and_portals_match_exact_rom_warp_indices(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'Data').mkdir();(root/'Data/FireRed.gba').symlink_to(ROOT/'Data/FireRed.gba')
            for name in ('vendor','native'):(root/name).symlink_to(ROOT/name)
            with Game(root,resume=False) as game:
                for edge in zone_spec(root)['links']:
                    if edge.get('kind')!='warp':continue
                    warp=read_map(game,edge['source'])['warps'][edge['warp_index']]
                    self.assertEqual(warp['destination'],edge['destination']);self.assertEqual(warp['destination_warp'],edge['destination_warp'])
                # Isolated graph fixture models already cleared story/trainers;
                # production always reads their actual flags and active triggers.
                class Client:
                    def map(self,name=None):
                        grid=read_map(game,name);return dict(grid,trainers=[],script_triggers=[],objects=[],obstacles=grid['signs'])
                class Trainer:
                    def __init__(self):self.root=root;self.bot=Client()
                    def state(self):return dict(map={'name':'Route4_PokemonCenter_1F'},position={'x':7,'y':4})
                nav=Navigator(Trainer());farm=nav.choose_farm('Route4');self.assertEqual(farm['hub'],'Cerulean')
                outward=nav.current_plan('CeruleanCity_PokemonCenter_1F',(7,4));self.assertTrue(any(e['source'] in ('MtMoon_B2F','DiglettsCave_B1F') for e in outward['links']))
                # Onward feasibility prevents selecting Cerulean on the way to Route1.
                key,_=nav.nearest_clinic(('Route4_PokemonCenter_1F',(7,4)));hub=zone_spec(root)['hubs'][key];self.assertTrue(nav.plan(hub['map'],hub['nurse'],'Route4_PokemonCenter_1F',(7,4)))

if __name__=='__main__':unittest.main()
