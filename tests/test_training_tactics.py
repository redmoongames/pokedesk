"""Safety decisions must account for the switch turn and preserve local parties."""
from pathlib import Path
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch
import sys,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from test_grind import mon
from pokemon_red.training_tactics import duel,choose,escape_support,plan
from pokemon_red.optimizer import make_training_plan,PlanningUnavailable
from pokemon_red.run_context import RunConfig

GEO=dict(farm=dict(hub='Viridian',map='Route1',entry=[12,6],pair=[[12,6],[13,6]],cost=[0,40]),travel_seconds=20,preparation_seconds=10,preparation_steps=40)
EVIDENCE=dict(cycles=[],battles=[])
class TacticalTests(unittest.TestCase):
    def test_critical_margin_causes_switch_but_finishing_before_enemy_is_safe(self):
        learner=mon(1,6,'t',[33]);support=mon(25,30,'m',[84]);enemy=mon(19,3,'e',[33]);learner.update(hp=4,slot=1);support['slot']=2
        state=dict(party=[learner,support],battle=dict(enemies=[enemy],allies=[]))
        choice=choose(state,learner,'t',ROOT);self.assertEqual(choice['mon']['uid'],'m');self.assertGreater(choice['critical'],0)
        support['hp']=1;state['party']=[support];choice=choose(state,support,'m',ROOT);self.assertEqual(choice['mon']['uid'],'m');self.assertTrue(choice['finishes_first'])
    def test_no_survivor_requests_retreat_instead_of_an_unsafe_attack(self):
        learner=mon(1,5,'t',[33]);learner['hp']=1;enemy=mon(19,4,'e',[33]);state=dict(party=[learner],battle=dict(enemies=[enemy]))
        self.assertIsNone(choose(state,learner,'t',ROOT))
    def test_switch_adds_a_dangerous_enemy_turn(self):
        learner=mon(25,10,'t',[84]);enemy=mon(16,2,'e',[33]);staying=duel(learner,enemy,ROOT);switching=duel(learner,enemy,ROOT,switch=True)
        self.assertTrue(staying['finishes_first']);self.assertEqual(staying['budget'],0);self.assertGreater(switching['budget'],0);self.assertEqual(switching['turns'],staying['turns']+1)
    def test_live_stages_and_hp_override_party_values(self):
        learner=mon(1,10,'t',[33],slot=1);enemy=mon(19,3,'e',[33]);ally=dict(learner,hp=1,stages=dict(attack=-6));state=dict(party=[learner],battle=dict(enemies=[enemy],allies=[ally]))
        self.assertIsNone(choose(state,learner,'t',ROOT))
    def test_unsupported_damaging_move_is_not_assumed_harmless(self):
        learner=mon(1,20,'t',[33]);enemy=mon(100,25,'e',[120]);row=duel(learner,enemy,ROOT)
        self.assertGreaterEqual(row['critical'],learner['max_hp']);self.assertFalse(row['survives'])
    def test_disabled_move_cannot_be_selected(self):
        learner=mon(25,20,'t',[84,98]);learner['moves'][0]['disabled']=True;enemy=mon(16,3,'e',[33])
        # Battle telemetry identifies the move through disabled_move.
        learner['disabled_move']=84
        from pokemon_red.battle_conditions import move_blockers
        self.assertTrue(move_blockers(learner,learner['moves'][0]));self.assertEqual(duel(learner,enemy,ROOT)['index'],1)
    def test_auto_falls_back_to_careful_for_early_solo_starter(self):
        target=mon(1,5,'t',[33,45]);inv=dict(ready=True,party=[target],boxes=[]);cfg=dict(training_approach='auto',route='Route1',trainee='t',target=10)
        with patch('pokemon_red.optimizer.route_geometry',return_value=deepcopy(GEO)):
            result=make_training_plan(inv,cfg,ROOT,navigator=object(),evidence=EVIDENCE)
        self.assertEqual(result['tactic'],'careful');self.assertGreater(result['survivable_coverage'],0);self.assertGreater(result['forecast']['xp_game_minute'],0)
    def test_careful_route_remains_available_when_center_can_restore_depleted_pp(self):
        target=mon(1,5,'t',[33]);target['moves'][0]['current_pp']=0;inv=dict(ready=True,party=[target],boxes=[])
        with patch('pokemon_red.optimizer.route_geometry',return_value=deepcopy(GEO)):
            result=make_training_plan(inv,dict(training_approach='careful',route='Route1',trainee='t',target=8),ROOT,navigator=object(),evidence=EVIDENCE)
        self.assertEqual(result['tactic'],'careful')
    def test_fast_and_forced_mentor_are_separate_approaches(self):
        target=mon(1,30,'t',[33]);mentor=mon(25,50,'m',[84]);inv=dict(ready=True,party=[target,mentor],boxes=[]);cfg=dict(route='Route1',trainee='t',target=35)
        with patch('pokemon_red.optimizer.route_geometry',return_value=deepcopy(GEO)):
            auto=make_training_plan(inv,dict(cfg,training_approach='auto'),ROOT,navigator=object(),evidence=EVIDENCE)
            assisted=make_training_plan(inv,dict(cfg,training_approach='mentor'),ROOT,navigator=object(),evidence=EVIDENCE)
        self.assertEqual(auto['tactic'],'fast');self.assertEqual(assisted['tactic'],'mentor');self.assertEqual(assisted['primary_mentor'],'m')
    def test_local_preserves_exact_party_including_weak_members_and_eggs(self):
        target=mon(1,10,'t',[33]);reserve=mon(19,5,'r',[33]);egg=mon(25,5,'egg',[84],is_egg=True);inv=dict(ready=True,party=[target,reserve,egg],boxes=[mon(25,50,'boxed',[84])],_planning=dict(state=dict(map=dict(name='Route1'))));cfg=dict(route='Route22',trainee='t',target=12,training_approach='local')
        # No native world is needed; route geometry is supplied by the test.
        with patch('pokemon_red.optimizer.route_geometry',return_value=deepcopy(GEO)):
            result=make_training_plan(inv,cfg,ROOT,navigator=object(),evidence=EVIDENCE)
        self.assertEqual(result['route'],'Route1');self.assertEqual(result['team_uids'],['t','r','egg']);self.assertNotIn('boxed',result['fighters']);self.assertTrue(result['keep_party']);self.assertEqual(result['forecast']['preparation_seconds'],0)
    def test_local_rejects_boxed_target_instead_of_modifying_party(self):
        inv=dict(party=[mon(1,5,'t',[33])],boxes=[mon(25,50,'boxed',[84])],_planning=dict(state=dict(map=dict(name='Route1'))))
        with self.assertRaises(ValueError):make_training_plan(inv,dict(training_approach='local',trainee='boxed'),ROOT,navigator=object())
    def test_escape_keeps_current_fast_runner_and_avoids_fatal_switches(self):
        target=mon(1,5,'t',[33],slot=1);target['hp']=2;runner=mon(19,40,'r',[33],slot=2);enemy=mon(19,6,'e',[33]);state=dict(party=[target,runner],battle=dict(enemies=[enemy]))
        self.assertEqual(escape_support(state,target,ROOT)['uid'],'r');self.assertEqual(escape_support(state,runner,ROOT)['uid'],'r')
    def test_config_validates_approach_and_roundtrips(self):
        cfg=RunConfig.parse(dict(training_approach='auto',equip_lucky_egg=False));self.assertEqual(RunConfig.parse(cfg.as_dict()),cfg)
        with self.assertRaises(ValueError):RunConfig.parse(dict(training_approach='bogus'))
