"""Exact FireRed cave spawns, trapping risk and optional support planning."""
from pathlib import Path
import sys,unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from test_grind import mon
from pokemon_red.catalog import catalog,species
from pokemon_red.coverage import matchup_rows,trapped_matchups,make_coverage_plan
from pokemon_red.zones import zone_spec

class DiglettCaveTests(unittest.TestCase):
    def test_encounters_and_portals_are_separate_and_exact(self):
        c=catalog(ROOT);r=c['routes']['DiglettsCave_B1F'];p={m['species_id']:m for m in r['population']}
        self.assertEqual({s:m['probability'] for s,m in p.items()},{50:95,51:5})
        self.assertEqual(p[51]['levels'],{'29':4,'31':1});self.assertEqual(p[50]['levels'],{'15':10,'16':10,'17':15,'18':20,'19':20,'20':10,'21':5,'22':5})
        self.assertNotIn('DiglettsCave_SouthEntrance',c['routes']);self.assertNotIn('DiglettsCave_NorthEntrance',c['routes'])
        self.assertEqual(set(species(50,ROOT)['abilities']),{8,71})
        links=zone_spec(ROOT)['links']
        for a,b in [('Route11','DiglettsCave_SouthEntrance'),('DiglettsCave_SouthEntrance','DiglettsCave_B1F'),('DiglettsCave_B1F','DiglettsCave_NorthEntrance'),('DiglettsCave_NorthEntrance','Route2')]:
            self.assertTrue(any(e['source']==a and e['destination']==b for e in links),(a,b))
            self.assertTrue(any(e['source']==b and e['destination']==a for e in links),(b,a))

    def test_trapping_warns_but_does_not_ban_assisted_training(self):
        t=mon(129,3,'t',[150]);a=mon(150,70,'a',[94]);team=[t,a]
        rows=matchup_rows(t,'DiglettsCave_B1F',ROOT,trainee=True)
        self.assertTrue(trapped_matchups(t,rows,ROOT))
        flying=mon(21,3,'fly',[64]);self.assertEqual(trapped_matchups(flying,rows,ROOT),[])
        geo=dict(farm=dict(hub='Vermilion',pair=[[73,56],[73,69]],cost=[28,148]),travel_seconds=20,preparation_seconds=10,preparation_steps=40)
        forecast=dict(xp_game_minute=100,remaining_game_seconds=600,evidence=dict(exact_cycles=0),target_xp=100,game_seconds=60)
        with patch('pokemon_red.coverage.routes_for',return_value=('DiglettsCave_B1F',)),patch('pokemon_red.optimizer.route_geometry',return_value=geo),patch('pokemon_red.optimizer.forecast_cycle',return_value=forecast):
            p=make_coverage_plan(dict(ready=True,party=team,boxes=[]),dict(route='Auto',trainee='t',target=15,strategy='adaptive'),ROOT,navigator=object(),evidence=dict(cycles=[],battles=[]))
        self.assertEqual(p['route'],'DiglettsCave_B1F');self.assertEqual(p['training_mode'],'assisted');self.assertTrue(p['battle_risks']);self.assertIn('a',p['team_uids'])


class TrapResourceTests(unittest.TestCase):
    def test_depleted_attacks_heal_before_next_trap_but_splash_learner_can_train(self):
        from pokemon_red.grind import GrindTrainer
        t=object.__new__(GrindTrainer);t.root=ROOT;t.preparing=False;t.runner=None;t.threshold=.4;t.route='DiglettsCave_B1F';t.strategy='adaptive'
        target=mon(3,40,'t',[75]);target['moves'][0]['current_pp']=0
        helper=mon(150,70,'a',[94]);t.trainee='t';t.healthy_fighters=lambda s:[helper]
        s=dict(in_battle=False,party=[target,helper])
        self.assertTrue(t.need_heal(s));self.assertIn('PP',t.heal_cause)
        target['moves'][0]['current_pp']=1;self.assertFalse(t.need_heal(s))
        s['party'][0]=mon(129,3,'t',[150]);self.assertFalse(t.need_heal(s))
        s['party'][0]=mon(21,40,'t',[64]);s['party'][0]['moves'][0]['current_pp']=0
        self.assertFalse(t.need_heal(s))

class DirectedTravelTests(unittest.TestCase):
    def test_long_route_requires_real_cut_capability_and_cave_chain(self):
        import tempfile
        from types import SimpleNamespace
        from pokemon_red.engine import Game
        from pokemon_red.telemetry import read_map
        from pokemon_red.navigation import Navigator
        from pokemon_red.training import TrainingProblem
        with tempfile.TemporaryDirectory() as d:
            r=Path(d);(r/'Data').mkdir();(r/'Data/FireRed.gba').symlink_to(ROOT/'Data/FireRed.gba')
            for name in ('vendor','native'):(r/name).symlink_to(ROOT/name)
            with Game(r,resume=False) as g:
                # Synthetic cleared-story fixture; Cut trees remain obstacles.
                cache={}
                def grid(name):
                    if name not in cache:
                        raw=read_map(g,name);cuts=[o for o in raw['objects'] if o.get('graphics_id')==95]
                        cache[name]=dict(raw,objects=cuts,obstacles=raw.get('signs',[])+[[o['x'],o['y']] for o in cuts],trainers=[],script_triggers=[])
                    return cache[name]
                t=SimpleNamespace(root=r,bot=SimpleNamespace(map=grid),state=lambda:{})
                nav=Navigator(t)
                with self.assertRaises(TrainingProblem) as e:nav.plan('Route5',(31,32),'Route1',(12,0))
                self.assertEqual(e.exception.code,'cut_required')
                nav=Navigator(t);nav.cut_enabled=True
                path=nav.plan('Route5',(31,32),'Route1',(12,0))
                self.assertIn('DiglettsCave_B1F',[e['destination'] for e in path['links']]);self.assertTrue(path['field_actions'])
                self.assertTrue(nav.plan('VermilionCity_PokemonCenter_1F',(7,4),'ViridianCity_PokemonCenter_1F',(7,4))['links'])

if __name__=='__main__':unittest.main()
