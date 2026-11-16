from pathlib import Path
import copy,sys,unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from test_grind import mon
from pokemon_red.coverage import make_coverage_plan,support_cover,certified,matchup_rows,covered
from pokemon_red.catalog import catalog,move
from pokemon_red.mechanics import estimate,wild_mon

class CoveragePolicyTests(unittest.TestCase):
    def setUp(self):
        self.team=[mon(129,3,'t',[150]),mon(19,12,'r',[33],ability_id=50),mon(150,40,'a',[94]),mon(21,40,'b',[64]),mon(1,40,'c',[22]),mon(7,40,'d',[55])]
        self.inv=dict(ready=True,party=self.team,boxes=[]);self.cfg=dict(route='Auto',trainee='t',target=25,strategy='adaptive');self.geo=dict(farm=dict(hub='Viridian',pair=[[12,6],[13,6]],cost=[0,40]),travel_seconds=20,preparation_seconds=10,preparation_steps=40)
    def choose(self,coverage,distances=None):
        routes=tuple(coverage)
        def rows(m,route,root,**_):
            p=coverage[route] if m['uid']=='t' else 1
            if isinstance(p,tuple):p=p[int(_.get('max_hits',1)==2)]
            weights=[p*100,(1-p)*100]
            return [dict(species_id=n,species='foe',level=3,hp=20,weight=w,attacker=m['nickname'],attacker_uid=m['uid'],mean=30 if m['uid']!='t' else 0,ohko=1 if i==0 or m['uid']!='t' else 0,ohko_on_hit=1 if i==0 or m['uid']!='t' else 0,turns=1,move='TACKLE',move_id=33,accuracy=1) for i,(n,w) in enumerate(zip((16,19),weights))]
        def geometry(_,route,root):return dict(self.geo,preparation_seconds=(distances or {}).get(route,10))
        forecast=dict(xp_game_minute=100,remaining_game_seconds=600,evidence=dict(exact_cycles=0),target_xp=100,game_seconds=60)
        with patch('pokemon_red.coverage.routes_for',return_value=routes),patch('pokemon_red.coverage.matchup_rows',side_effect=rows),patch('pokemon_red.coverage.difficulty',side_effect=lambda route,_:(routes.index(route),)),patch('pokemon_red.optimizer.route_geometry',side_effect=geometry),patch('pokemon_red.optimizer.forecast_cycle',return_value=copy.deepcopy(forecast)):
            return make_coverage_plan(self.inv,self.cfg,ROOT,navigator=object(),evidence=dict(cycles=[],battles=[]))
    def test_main_threshold_selects_hardest_qualifying_student_route(self):
        p=self.choose(dict(Route1=1,Route2=.9,Route3=.2));self.assertEqual(p['route'],'Route2');self.assertEqual(p['training_mode'],'direct');self.assertAlmostEqual(p['coverage']['target'],.9)
    def test_non_monotonic_type_matchups_do_not_stop_at_first_failed_zone(self):
        p=self.choose(dict(Route1=1,Route2=.1,Route3=1));self.assertEqual(p['route'],'Route3')
    def test_eighty_percent_is_accepted_and_partial_route_below_it_is_not(self):
        p=self.choose(dict(Route1=.8,Route2=.5,Route3=.49),dict(Route1=100,Route2=10,Route3=0));self.assertEqual(p['route'],'Route1');self.assertEqual(p['training_mode'],'direct')
    def test_splash_learner_uses_hardest_route_covered_by_owned_supports(self):
        p=self.choose(dict(Route1=0,Route2=0,Route3=0));self.assertEqual(p['route'],'Route3');self.assertEqual(p['training_mode'],'assisted');self.assertEqual(p['coverage']['supports'],1);self.assertIn('t',p['team_uids']);self.assertIn('r',p['team_uids']);self.assertLessEqual(len(p['fighters'])-1,4)
    def test_checkbox_changes_learner_routes_and_single_hit_fallback(self):
        values=dict(Route1=(1,1),Route2=(.7,.9),Route3=(.2,.9))
        self.assertEqual(self.choose(values)['route'],'Route3')
        self.cfg['allow_two_hits']=False
        self.assertEqual(self.choose(values)['route'],'Route1')
        self.assertEqual(self.choose(dict(Route1=.7,Route2=.5,Route3=.2))['training_mode'],'assisted')
    def test_mentor_is_strongest_and_route_maximizes_xp_not_level(self):
        reference=copy.deepcopy(catalog(ROOT))
        for route,xp in [('Route1',1000),('Route2',10),('Route3',100)]:reference['routes'][route]['difficulty']['expected_wild_xp']=xp
        with patch('pokemon_red.coverage.catalog',return_value=reference):p=self.choose(dict(Route1=0,Route2=0,Route3=0))
        self.assertEqual(p['route'],'Route1');self.assertEqual(p['primary_mentor'],'a');self.assertEqual(p['training_mode'],'assisted')
    def test_primary_mentor_can_be_the_previous_escape_provider(self):
        self.team[1]['level']=99
        p=self.choose(dict(Route1=0,Route2=0,Route3=0));self.assertEqual(p['primary_mentor'],'r');self.assertNotEqual(p['runner'],'r');self.assertIn('r',p['fighters'])
    def test_all_rare_spawns_must_be_covered_in_support_mode(self):
        matrix={'a':[dict(ohko_on_hit=1),dict(ohko_on_hit=0)],'b':[dict(ohko_on_hit=0),dict(ohko_on_hit=1)]}
        candidates=self.team[2:4];self.assertEqual(set(support_cover(matrix,candidates,capacity=2)),{'a','b'});self.assertIsNone(support_cover(matrix,candidates,capacity=1))
    def test_set_cover_can_find_solution_greedy_largest_mask_misses(self):
        masks={'a':0b001111,'b':0b010011,'c':0b101100}
        matrix={u:[dict(ohko_on_hit=int(mask>>i&1)) for i in range(6)] for u,mask in masks.items()}
        self.assertEqual(set(support_cover(matrix,self.team[2:5],capacity=2)),{'b','c'})
    def test_accuracy_does_not_reduce_damage_on_hit_certificate(self):
        attacker=mon(25,50,'p',[87]);foe=wild_mon(16,2,ROOT);r=estimate(attacker,foe,move(87,ROOT),ROOT)
        self.assertEqual(r['ohko_on_hit'],1);self.assertLess(r['ohko'],1);self.assertTrue(certified(r))
    def test_immunity_is_not_counted_as_weakness_and_second_move_can_cover_it(self):
        m=mon(25,100,'p',[84,98]);rows=matchup_rows(m,'MtMoon_1F',ROOT,trainee=True)
        ground=[r for r in rows if r['species_id']==74];self.assertTrue(ground);self.assertTrue(all(r['move_id']==98 and r['min']>=r['hp'] for r in ground))
    def test_sqlite_profiles_include_exact_weights_hp_and_dual_type_weakness(self):
        for route in catalog(ROOT)['routes'].values():
            self.assertAlmostEqual(sum(r['probability'] for r in route['population']),100)
            self.assertIn('rank',route['difficulty'])
            for r in route['population']:
                self.assertGreater(r['hp_min'],0);self.assertGreaterEqual(r['hp_max'],r['hp_min']);self.assertEqual(set(r['levels']),set(r['hp_by_level']));self.assertIn('weaknesses',r)

if __name__=='__main__':unittest.main()
