"""Battles on portal tiles must not consume warp retries or keep walking blindly."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import sys,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.training import RouteTrainer,TrainingProblem
from pokemon_red.bot import ControlLost

class TransitionRecoveryTests(unittest.TestCase):
    def trainer(self):
        s=dict(frame=100,in_battle=False,map=dict(name='source'),position=dict(x=3,y=4),controls=dict(callback='CB2_Overworld',field_locked=False,moving=False))
        t=object.__new__(RouteTrainer);t.state=lambda:s;t.want_heal=False;t.bot=SimpleNamespace(event=Mock())
        t.wait=Mock(side_effect=lambda n:s.update(frame=s['frame']+n));t.go=Mock(side_effect=lambda p:s['position'].update(x=p[0],y=p[1]));t.step=Mock();t.fight=Mock()
        return t,s
    def test_battle_before_transition_rearms_approach_and_preserves_travel_intent(self):
        for healing in (False,True):
            t,s=self.trainer();t.want_heal=healing;s['in_battle']=True
            def fought(**_):s.update(in_battle=False,frame=200);s['position'].update(x=4,y=4)
            t.fight.side_effect=fought;t.step.side_effect=lambda _:s['map'].update(name='destination')
            t.transition('RIGHT','destination',source='source',point=(3,4))
            t.fight.assert_called_once_with(retreat=True,travel=not healing);t.go.assert_called_once_with((3,4));t.step.assert_called_once_with('RIGHT')
    def test_battle_during_step_is_not_a_failed_warp_attempt(self):
        t,s=self.trainer();n=[0]
        def step(_):
            n[0]+=1;s['frame']+=1
            if n[0]==1:s['in_battle']=True
            else:s['map']['name']='destination'
        t.step.side_effect=step;t.fight.side_effect=lambda **_:s.update(in_battle=False)
        t.transition('RIGHT','destination');self.assertEqual(t.step.call_count,2);t.fight.assert_called_once()
    def test_door_activation_tile_can_need_a_second_pulse(self):
        t,s=self.trainer();n=[0]
        def step(_):
            n[0]+=1;s['frame']+=20
            if n[0]==1:s['position']['x']=4
            else:s['map']['name']='destination'
        t.step.side_effect=step;t.transition('RIGHT','destination',source='source',point=(3,4))
        self.assertEqual(t.step.call_count,2);t.go.assert_not_called()

    def test_battle_after_arrival_finishes_without_a_further_direction(self):
        t,s=self.trainer();s.update(in_battle=True);s['map']['name']='destination';t.fight.side_effect=lambda **_:s.update(in_battle=False)
        t.transition('RIGHT','destination',source='source',point=(3,4));t.step.assert_not_called();t.go.assert_not_called()
    def test_unexpected_map_and_trainer_guard_do_not_send_another_step(self):
        t,s=self.trainer();s['map']['name']='elsewhere'
        with self.assertRaises(TrainingProblem):t.transition('RIGHT','destination',source='source',point=(3,4))
        t.step.assert_not_called();t.go.assert_not_called()
        t,s=self.trainer();s['in_battle']=True;t.fight.side_effect=TrainingProblem('unexpected_battle','trainer')
        with self.assertRaisesRegex(TrainingProblem,'trainer'):t.transition('RIGHT','destination')
        t.step.assert_not_called()
    def test_unexpected_battle_map_is_rejected_before_combat_input(self):
        t,s=self.trainer();s.update(in_battle=True);s['map']['name']='elsewhere'
        with self.assertRaises(TrainingProblem):t.transition('RIGHT','destination',source='source',point=(3,4))
        t.fight.assert_not_called();t.step.assert_not_called()

    def test_takeover_during_recovery_propagates_before_any_retry(self):
        t,s=self.trainer();s['in_battle']=True;t.fight.side_effect=ControlLost('F9')
        with self.assertRaises(ControlLost):t.transition('RIGHT','destination')
        t.step.assert_not_called();t.go.assert_not_called()
    def test_repeated_encounters_and_real_misses_are_bounded(self):
        t,s=self.trainer();s['in_battle']=True
        with self.assertRaises(TrainingProblem) as e:t.transition('RIGHT','destination')
        self.assertEqual(e.exception.code,'transition_encounter_limit');self.assertEqual(t.fight.call_count,8);t.step.assert_not_called()
        t,s=self.trainer();t.step.side_effect=lambda _:s.update(frame=s['frame']+20)
        with self.assertRaises(TimeoutError):t.transition('RIGHT','destination')
        self.assertEqual(t.step.call_count,12)
    def test_loading_frames_do_not_spend_the_step_budget(self):
        t,s=self.trainer();s['controls']['moving']=2
        def settle(n):s['frame']+=n;s['controls']['moving']=0
        t.wait.side_effect=settle;t.step.side_effect=lambda _:s['map'].update(name='destination')
        t.transition('RIGHT','destination');t.wait.assert_called_once_with(6);t.step.assert_called_once()

class PartyOpeningTests(unittest.TestCase):
    def trainer(self,ready=False):
        state=dict(frame=100,party=[dict(uid='t',slot=2,nickname='TARGET')],controls=dict(callback='CB2_Overworld',field_locked=True,tasks=[dict(name='Task_StartMenuHandleInput',data=[int(ready)])],start_order=[0,1,2],start_cursor=1))
        t=object.__new__(RouteTrainer);t.state=lambda:state;t.trainee='t';t.bot=SimpleNamespace(event=Mock());t.tap=Mock()
        def wait(n):state['frame']+=n;state['controls']['tasks'][0]['data']=[1]
        t.wait=Mock(side_effect=wait)
        def selected(*a,**kw):state['party'][0]['slot']=1;state['controls'].update(callback='CB2_Overworld',field_locked=False,tasks=[])
        t.party_select=Mock(side_effect=selected)
        return t,state
    def test_waits_for_readiness_and_retries_ignored_a_until_party_ack(self):
        t,s=self.trainer();attempt=[0]
        def tap(key):
            self.assertEqual(key,'A');s['frame']+=12;attempt[0]+=1
            if attempt[0]==2:s['controls'].update(callback='CB2_UpdatePartyMenu',tasks=[dict(name='Task_HandleChooseMonInput')])
        t.tap.side_effect=tap;t.lead('t')
        self.assertEqual(t.tap.call_count,2);t.wait.assert_called_once_with(6);t.party_select.assert_called_once_with('t',reorder=True)
    def test_missing_party_command_and_takeover_do_not_send_unverified_input(self):
        t,s=self.trainer(ready=True);s['controls']['start_order']=[0,2]
        with self.assertRaises(TrainingProblem):t.lead('t')
        t.tap.assert_not_called();t.party_select.assert_not_called()
        t,s=self.trainer(ready=True);t.tap.side_effect=ControlLost('F9')
        with self.assertRaises(ControlLost):t.lead('t')
        t.party_select.assert_not_called()

if __name__=='__main__':unittest.main()
