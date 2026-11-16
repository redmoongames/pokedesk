from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
import copy,sys,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.grind import GrindTrainer
from pokemon_red.optimizer import PlanningUnavailable
from test_grind import mon

class ReplanTests(unittest.TestCase):
    def trainer(self):
        t=object.__new__(GrindTrainer);t.config=dict(training_policy='coverage',route='Route11');t.requested_route='Auto';t.coverage_signature=(14,1,(33,));t.coverage_key=lambda:(15,1,(33,));t.root=ROOT;t.route='Route11';t.run_id='old-run';t.training_session='session';t.plan=dict(training_mode='assisted',move_plan={'id':'approved-original'});t.preparing=False;t.want_heal=False;t.strategy='adaptive'
        t.bot=SimpleNamespace(event=Mock(),inventory=Mock(return_value={}));t.planning_snapshot=Mock(return_value={});t.navigator=SimpleNamespace(configure_tools=Mock(),choose_farm=Mock(return_value=dict(hub='Vermilion',pair=[[1,2],[2,2]])),travel=Mock());t.prepare_at_clinic=Mock();t.travel_lead=Mock();t.heal_here=Mock();t.record_run=Mock();t.state=lambda:dict(map=dict(name='VermilionCity_PokemonCenter_1F'))
        return t
    def plan(self,**kwargs):
        return dict(dict(training_mode='direct',route='Route6',runner=None,fighters=['t','h'],coverage=dict(target=.9),move_plan={'id':'new-unapproved-preview'}),**kwargs)
    def test_assisted_does_not_change_to_partial_route_or_churn_at_same_level(self):
        t=self.trainer()
        with patch('pokemon_red.optimizer.make_training_plan',return_value=self.plan(training_mode='mixed')) as make:
            self.assertFalse(t.maybe_replan());self.assertFalse(t.maybe_replan());make.assert_called_once()
        t.prepare_at_clinic.assert_not_called();t.record_run.assert_not_called()
    def test_same_route_and_mode_keep_current_team(self):
        t=self.trainer();t.plan['training_mode']='direct'
        with patch('pokemon_red.optimizer.make_training_plan',return_value=self.plan(route='Route11')):self.assertFalse(t.maybe_replan())
        t.prepare_at_clinic.assert_not_called()
    def test_promotion_preserves_approved_moves_and_starts_separate_run_before_next_cycle(self):
        t=self.trainer();purposes=[];t.prepare_at_clinic.side_effect=lambda:purposes.append(t.preparing)
        with patch('pokemon_red.optimizer.make_training_plan',return_value=self.plan()):self.assertTrue(t.maybe_replan())
        self.assertEqual(t.route,'Route6');self.assertEqual(t.config['route'],'Route6');self.assertEqual(t.plan['move_plan']['id'],'approved-original');t.record_run.assert_called_once_with('old-run');self.assertEqual(purposes,[True]);self.assertFalse(t.preparing);self.assertEqual(t.cycle_number,0);t.heal_here.assert_not_called()
    def test_temporary_unavailability_retains_existing_route_and_inputs(self):
        t=self.trainer()
        with patch('pokemon_red.optimizer.make_training_plan',side_effect=PlanningUnavailable([dict(route='Route6',reason='closed')])):self.assertFalse(t.maybe_replan())
        self.assertEqual(t.route,'Route11');t.prepare_at_clinic.assert_not_called();self.assertEqual(t.bot.event.call_args.args[0],'training_replan_deferred')
    def test_manual_route_never_relocates_automatically(self):
        t=self.trainer();t.requested_route='Route11';self.assertFalse(t.maybe_replan());t.planning_snapshot.assert_not_called()

if __name__=='__main__':unittest.main()
