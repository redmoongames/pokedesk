from pathlib import Path
from copy import deepcopy
from unittest.mock import patch
import sys,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from test_grind import mon
import test_adaptive
from pokemon_red.combat_policy import finish_plan,live_plan,route_resources,profile_key,_profile
from pokemon_red.mechanics import wild_mon
from pokemon_red.run_context import RunConfig,planning_key
from pokemon_red.coverage import matchup_rows,covered

class HitCertificateTests(unittest.TestCase):
 def row(self,mid,damage,**extra):return dict(move_id=mid,min=damage,mean=damage,max=damage,accuracy=1,turns=2,ohko=0,ohko_on_hit=0,**extra)
 def test_two_hit_boundary_pp_and_combined_last_moves(self):
  rows=[self.row(1,50),self.row(2,49)]
  self.assertEqual(finish_plan(rows,{1:2,2:1},100,2)['certified_hits'],2)
  self.assertIsNone(finish_plan(rows,{1:1,2:1},100,2))
  self.assertIsNone(finish_plan(rows,{1:2,2:2},100,1))
  result=finish_plan(rows,{1:1,2:1},99,2);self.assertEqual(result['pp_costs'],{1:1,2:1})
 def test_immunity_approximation_and_hp_dependent_damage_not_certified(self):
  for row in (self.row(1,0),self.row(1,60,approximate=True),self.row(1,50,effect_name='SUPER_FANG')):self.assertIsNone(finish_plan([row],{1:10},100,2))
 def test_one_hit_needs_only_one_pp_and_accuracy_is_not_damage(self):
  row=self.row(1,100);row['accuracy']=.75
  result=finish_plan([row],{1:1},100,1);self.assertEqual(result['certified_hits'],1);self.assertAlmostEqual(result['turns'],1/.75)
 def test_config_default_validation_and_preview_cache_invalidation(self):
  self.assertTrue(RunConfig.parse({}).allow_two_hits);self.assertFalse(RunConfig.parse(dict(allow_two_hits=False)).allow_two_hits)
  with self.assertRaises(ValueError):RunConfig.parse(dict(allow_two_hits=1))
  a=mon(2,20,'t',[22]);inv=dict(ready=True,party=[a],boxes=[])
  self.assertNotEqual(planning_key(inv,dict(trainee='t')),planning_key(inv,dict(trainee='t',allow_two_hits=False)))

class LearnerResourceTests(unittest.TestCase):
 def setup_trainer(self,target,route='Route2'):
  return test_adaptive.AdaptiveTests().trainer(target,[mon(150,50,'h',[94])],route)
 def test_spent_pp_causes_heal_even_with_healthy_mentor_and_persists_after_trapped_fight(self):
  target=mon(2,30,'t',[22,33]);t,s,b=self.setup_trainer(target);s['in_battle']=False
  for a in target['moves']:a['current_pp']=0
  self.assertTrue(t.need_heal(s));self.assertTrue(t.want_heal);self.assertIn('PP',t.heal_cause)
  s['in_battle']=True;self.assertTrue(t.need_heal(s));self.assertTrue(t.want_heal)
 def test_inherently_weak_learner_does_not_loop_healing(self):
  target=mon(129,3,'t',[150]);t,s,_=self.setup_trainer(target);s['in_battle']=False
  self.assertFalse(t.need_heal(s))
 def test_two_hit_learner_stays_in_instead_of_switching(self):
  target=mon(1,8,'t',[33]);t,s,_=self.setup_trainer(target);enemy=wild_mon(19,6,ROOT);s['battle']['enemies']=[enemy]
  # A concrete live HP between one and two guaranteed minimum hits.
  from pokemon_red.mechanics import ranked_attacks
  minimum=ranked_attacks(target,enemy,ROOT)[0][1]['min'];enemy['hp']=minimum*2
  self.assertEqual(t.battle_fighter(s,target)['uid'],'t')
  self.assertEqual(t.attack_choice(target,enemy),0)
  t.config['allow_two_hits']=False;self.assertEqual(t.battle_fighter(s,target)['uid'],'h')
 def test_weak_remaining_move_does_not_count_as_usable_route_resource(self):
  target=mon(2,23,'t',[22,33]);t,s,_=self.setup_trainer(target,'DiglettsCave_B1F');s['in_battle']=False
  full=route_resources(target,t.route,ROOT,t.config)
  target['moves'][0]['current_pp']=0;spent=route_resources(target,t.route,ROOT,t.config)
  self.assertGreaterEqual(full['full'],.8);self.assertLess(spent['current'],.8);self.assertTrue(t.need_heal(s))
 def test_duplicate_equivalent_attack_can_replace_spent_best(self):
  target=mon(2,30,'t',[22,75]);t,s,_=self.setup_trainer(target,'Route2');s['in_battle']=False;target['moves'][0]['current_pp']=0
  self.assertFalse(t.need_heal(s));self.assertGreaterEqual(t.resource_state(target)['current'],.8)
 def test_depletion_during_winnable_battle_finishes_then_returns_to_heal(self):
  target=mon(1,13,'t',[33]);t,s,_=self.setup_trainer(target,'Route2');target['slot']=1;target['moves'][0]['current_pp']=1
  enemy=wild_mon(16,2,ROOT);enemy['hp']=1;s['battle'].update(enemies=[enemy],allies=[dict(party_slot=1)])
  self.assertFalse(t.need_heal(s));self.assertTrue(t.want_heal)
  s['in_battle']=False;s['battle']=None;target['moves'][0]['current_pp']=0
  self.assertTrue(t.need_heal(s))
 def test_eighty_percent_boundary_is_inclusive(self):
  profiles=tuple(dict(weight=w,hp=10,options=[dict(move_id=i,min=10,mean=10,accuracy=1)]) for i,w in ((1,80),(2,20)))
  target=mon(2,30,'t',[22,33]);target['moves'][0]['id']=1;target['moves'][1]['id']=2;target['moves'][1]['current_pp']=0
  with patch('pokemon_red.combat_policy.route_profile',return_value=profiles):
   result=route_resources(target,'Route2',ROOT,{})
  self.assertEqual(result['current'],.8);self.assertFalse(result['depleted'])
 def test_route_profiles_reused_when_only_pp_changes(self):
  target=mon(2,20,'t',[22]);_profile.cache_clear();route_resources(target,'Route2',ROOT,{});before=_profile.cache_info().misses;target['moves'][0]['current_pp']=0
  route_resources(target,'Route2',ROOT,{});self.assertEqual(_profile.cache_info().misses,before)

if __name__=='__main__':unittest.main()
