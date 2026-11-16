"""Phase pacing is a cancellable lease; core input remains frame-counted."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import sys,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.automatic_speed import decide,AutomaticSpeed
from pokemon_red.session_controller import SessionController as Monitor
from pokemon_red.run_context import RunConfig
from pokemon_red.automation import Automation,Session,Request

class SpeedPolicyTests(unittest.TestCase):
    def test_base_and_explicit_fast_waits(self):
        self.assertEqual(decide({}).speed,8)
        self.assertEqual(decide(dict(callback='CB2_Overworld',straight=True)).speed,8)
        self.assertEqual(decide(dict(callback='CB2_Overworld',directional=True)).speed,8)
        self.assertEqual(decide(dict(callback='CB2_Overworld',buttons='A')).speed,8)
        for context in (dict(callback='BattleMainCB2',battle=True,controller='HandleBattleAnimation'),dict(callback='CB2_Overworld',locked=True,interaction='healing'),dict(callback='CB2_Overworld',waiting=True)):
            self.assertEqual(decide(context).speed,12,context)
        self.assertEqual(decide(dict(callback='CB2_Overworld',waiting=True,buttons='UP')).speed,8)
        self.assertEqual(decide(dict(callback='CB2_Overworld',locked=True,waiting=True)).speed,8)

    def test_menu_selection_overrides_animation_and_waits(self):
        for context in (dict(callback='CB2_UpdatePartyMenu',battle=True),dict(callback='CB2_RunPokemonSummaryScreen'),dict(callback='CB2_Overworld',locked=True,interaction='healing',tasks=['Task_YesNoMenu_HandleInput']),dict(callback='BattleMainCB2',battle=True,controller='HandleInputChooseMove'),dict(callback='CB2_Overworld',managed_menu=True,waiting=True),dict(callback='CB2_Overworld',managed_choice=True,directional=True),dict(callback='CB2_Overworld',field_action=True,directional=True),dict(interaction='storage')):
            self.assertEqual(decide(context).speed,4,context)
        self.assertEqual(decide(dict(tasks=['Task_EvolutionScene'],managed_choice=True)).speed,12)

    def test_slows_before_next_frame_and_requires_stability_before_speeding(self):
        apply=Mock();p=AutomaticSpeed(apply);p.configure(True);self.assertEqual(p.speed,8)
        fast=dict(callback='BattleMainCB2',battle=True)
        for f in range(12):self.assertFalse(p.step(f,fast))
        self.assertTrue(p.step(12,fast));self.assertEqual(p.speed,12)
        self.assertTrue(p.step(13,dict(callback='CB2_UpdatePartyMenu')));self.assertEqual(p.speed,4)
        self.assertFalse(p.step(14,fast));self.assertFalse(p.step(15,dict(callback='CB2_UpdatePartyMenu')))
        self.assertFalse(p.step(16,fast));self.assertFalse(p.step(27,fast));self.assertTrue(p.step(28,fast))
        p.configure(False);self.assertIsNone(p.speed);apply.assert_called_with(None,'Ручная скорость')
        self.assertFalse(p.step(100,fast))

    def test_runtime_ownership_matches_managed_arrow_priority(self):
        from pokemon_red.automatic_speed import input_runtime,button_name
        from pokemon_red.engine import BUTTONS
        move=SimpleNamespace(owns_input=True,mask=BUTTONS['UP']);field=SimpleNamespace(mask=BUTTONS['DOWN']);recovery=SimpleNamespace(mask=BUTTONS['A'])
        c=SimpleNamespace(move_runtime=move,field_runtime=field,recovery_runtime=recovery)
        self.assertIs(input_runtime(c),recovery);c.recovery_runtime=None
        self.assertIs(input_runtime(c),field);c.field_runtime=None
        self.assertEqual(button_name(input_runtime(c).mask),'UP')
        move.owns_input=False;self.assertIsNone(input_runtime(c))

    def test_manual_speed_overrides_lease_and_pause_does_not_resume_itself(self):
        m=object.__new__(Monitor);m.settings={'speed':8};m.automatic_speed=16;m.paused=True;m.safety_notice=None
        m.speed_control=AutomaticSpeed(lambda rate,phase:setattr(m,'automatic_speed',rate));m.speed_control.enabled=True;m.speed_control.speed=16
        m.keys=set();m.sync_audio=Mock();m.update_panel=Mock()
        m.update_automatic_speed();self.assertTrue(m.paused)
        m.set_speed(8);self.assertFalse(m.paused);self.assertFalse(m.speed_control.enabled);self.assertEqual(m.simulation_speed,8)
        self.assertEqual(m.settings,{'speed':8})

    def test_pause_button_resume_retains_auto_lease(self):
        m=object.__new__(Monitor);m.settings={'speed':8};m.automatic_speed=3;m.paused=True;m.safety_notice=None
        m.speed_control=AutomaticSpeed(Mock());m.speed_control.enabled=True;m.speed_control.speed=3
        m.keys=set();m.sync_audio=Mock();m.update_panel=Mock();m.canvas=SimpleNamespace(focus_set=Mock())
        m.toggle_pause();self.assertFalse(m.paused);self.assertTrue(m.speed_control.enabled);self.assertEqual(m.simulation_speed,3)

    def test_wait_and_release_phases_never_look_like_pressed_buttons(self):
        from collections import deque
        from pokemon_red.automatic_speed import action_buttons
        from pokemon_red.engine import BUTTONS
        self.assertEqual(action_buttons(dict(buttons='Ожидание',phases=deque([(0,100)]))), '')
        self.assertEqual(action_buttons(dict(buttons='UP',phases=deque([(0,10)]))), '')
        self.assertEqual(action_buttons(dict(buttons='UP',phases=deque([(BUTTONS['UP'],2)]))), 'UP')

    def test_control_loss_restores_speed_on_stop_error_and_attention(self):
        for status in ('stopped','error','attention','finished'):
            callback=Mock();c=Automation(ROOT,snapshot=lambda:{},checkpoint=lambda _:None,set_speed=lambda _:None,release=Mock(),speed_installer=callback)
            c.session=Session(SimpleNamespace(close=lambda:None));c.stop(status=status);callback.assert_called_once_with(False);self.assertFalse(c.running);c.close()

    def test_api_is_typed_and_requires_training_safety(self):
        install=Mock();c=Automation(ROOT,snapshot=lambda:{},checkpoint=lambda _:None,set_speed=lambda _:None,release=Mock(),speed_installer=install)
        c.session=Session(SimpleNamespace(close=lambda:None));s=c.session
        for profile,arg in (('none',True),('training',1)):
            c.safety_profile=profile
            with self.assertRaises(ValueError):c._dispatch(Request(s,'manage_speed',dict(enabled=arg)))
        c.safety_profile='training';r=Request(s,'manage_speed',dict(enabled=True));c._dispatch(r);self.assertTrue(r.response['ok']);install.assert_called_once_with(True)
        c.close()

    def test_configuration_defaults_preserve_existing_automation(self):
        self.assertFalse(RunConfig.parse({}).auto_speed)
        self.assertTrue(RunConfig.parse(dict(auto_speed=True)).rules()['auto_speed'])
        for bad in (1,'true',None):
            with self.assertRaises(ValueError):RunConfig.parse(dict(auto_speed=bad))

class SpeedEvidenceTests(unittest.TestCase):
    def test_only_uninterrupted_auto_cycles_can_calibrate_auto_policy(self):
        from test_optimizer import OptimizerTests
        from pokemon_red.optimizer import compatible_cycles
        from pokemon_red.run_context import build_context
        fixture=OptimizerTests();fixture.setUp();cfg=dict(fixture.cfg,auto_speed=True)
        row=fixture.record();row['body']['context']=build_context(ROOT,cfg,fixture.plan)
        row['body']['speed_intervals']=[dict(speed=s) for s in (8,4,12,4)]
        def read(config=cfg):return compatible_cycles(fixture.plan,config,ROOT,fixture.geo['farm'],dict(cycles=[row]))
        self.assertEqual(len(read()),1);self.assertEqual(read(fixture.cfg),[])
        row['body']['automatic_speed_interrupted']=True;self.assertEqual(read(),[])
        row['body'].pop('automatic_speed_interrupted');row['body']['speed_intervals'].append(dict(speed=16));self.assertEqual(read(),[])

if __name__=='__main__':unittest.main()
