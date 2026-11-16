"""Battle selection, display placement and one-battle ownership boundaries."""
from pathlib import Path
from types import SimpleNamespace as NS
from copy import deepcopy
from concurrent.futures import Future
from unittest.mock import Mock,patch
import sys,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.window_layout import Rect,layout
from pokemon_red.manual_battle import eligibility,set_enabled,status,frame_guard,battle_key
from pokemon_red.mechanics import wild_mon

def mon(number,slot):return dict(wild_mon(number,24,ROOT),uid=str(slot),slot=slot,checksum_valid=True,nickname='MON '+str(slot))
def state():
    a=mon(74,1);b=mon(58,1);b['uid']='foe1';other=mon(37,2);other['uid']='foe2'
    return dict(in_battle=True,telemetry_valid=True,party=[a],controls=dict(callback='BattleMainCB2'),battle=dict(flags=8,outcome=0,trainer_id=12,telemetry_valid=True,enemy_party=[b,other],allies=[dict(a,party_slot=1)],enemies=[dict(b,party_slot=1,identity_valid=True)]))
def controller():
    c=NS(folder=ROOT,keys=set(),automation=NS(running=False,script=None,session=object(),status='idle'),pending_start=None,closed=False,closing=False,session_transition=False,operation=NS(active=False),safety_notice=None,last_state=state(),history=NS(db=NS(error=None)),game=NS(root=ROOT,state_generation=1,advance=Mock()),settings={'speed':1},paused=True)
    c.automation.start=Mock();c.automation.stop=Mock();c.session_state=lambda:c.last_state;c.create_slot=Mock();c.take_control=Mock();c.pause=Mock();c.set_speed=Mock();c.update_panel=Mock();return c

class LayoutTests(unittest.TestCase):
    def test_game_center_is_preserved_and_tools_fit(self):
        for width,height in ((1280,800),(1440,900),(1728,1117),(1920,1080)):
            p=layout(Rect(0,0,width,height),3)
            self.assertLessEqual(p.scale,3);self.assertGreaterEqual(p.trainer.width,480)
            self.assertEqual(p.game.x+p.game.width/2,width/2)
            for rect in (p.game,p.trainer,p.battle):
                self.assertGreaterEqual(rect.x,0);self.assertLessEqual(rect.x+rect.width,width)
            if p.trainer.x>=p.game.x+p.game.width:self.assertGreater(p.trainer.x,p.game.x+p.game.width)
    def test_negative_monitor_origin_is_preserved(self):
        p=layout(Rect(-1920,-200,1920,1080),3)
        self.assertEqual(p.game.x+p.game.width/2,-960);self.assertEqual(p.game.y+32+p.game.height/2,340)

class OwnershipTests(unittest.TestCase):
    def test_other_automation_blocks_start_and_stop_does_not_cancel_it(self):
        c=controller();c.automation.running=True;c.automation.script=ROOT/'Bots/train_xp.py'
        self.assertFalse(status(c)['available'])
        with self.assertRaisesRegex(RuntimeError,'автоматизация'):set_enabled(c,True)
        set_enabled(c,False);c.take_control.assert_not_called();c.create_slot.assert_not_called()
    def test_queued_delivery_also_reserves_ownership_between_cycles(self):
        c=controller();c.delivery=NS(enabled=True)
        with self.assertRaisesRegex(RuntimeError,'обмен'):set_enabled(c,True)
        c.create_slot.assert_not_called()
    def test_pending_restore_is_cancelled_if_battle_changes_before_checkpoint_finishes(self):
        c=controller();set_enabled(c,True);self.assertTrue(status(c)['pending']);cb=c.create_slot.call_args.kwargs['on_saved'];c.last_state['battle']['trainer_id']=99;cb(None)
        c.automation.start.assert_not_called();self.assertIsNone(c.pending_start)
    def test_start_waits_for_checkpoint_and_takeover_revokes_late_start(self):
        c=controller();set_enabled(c,True);cb=c.create_slot.call_args.kwargs['on_saved'];c.automation.start.assert_not_called();c.pending_start=None;cb(None);c.automation.start.assert_not_called()
        set_enabled(c,True);cb=c.create_slot.call_args.kwargs['on_saved'];cb(None);c.automation.start.assert_called_once_with(ROOT/'Bots/auto_battle.py');c.set_speed.assert_called_once_with(1)
    def test_end_of_battle_releases_inputs_and_pauses(self):
        c=controller();c.automation.running=True;c.automation.script=ROOT/'Bots/auto_battle.py';c.keys={'A'};c.game.read8=lambda _:0
        with patch('pokemon_red.manual_battle.symbols',return_value={'gMain':100}):self.assertTrue(frame_guard(c))
        c.automation.stop.assert_called_once();c.pause.assert_called_once_with(save=False);self.assertFalse(c.keys)
    def test_bot_handoff_pauses_once_instead_of_leaving_simulation_running(self):
        c=controller();c.automation.script=ROOT/'Bots/auto_battle.py';c.automation.status='attention';c._battle_auto_session=object()
        self.assertTrue(frame_guard(c));c.pause.assert_called_once_with(save=False)
        self.assertFalse(frame_guard(c));c.pause.assert_called_once()
    def test_special_and_double_battles_are_unavailable(self):
        for flag in [1,2,0x40,0x80,0x100,0x200,0x800]:
            s=state();s['battle']['flags']|=flag;self.assertIsNotNone(eligibility(s))

class SidebarTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from pokemon_red.battle_panel import BattlePanel
        self.root=tk.Tk();self.root.withdraw();self.monitor=NS(folder=ROOT,window=self.root,emergency_stop=Mock(),focus_out=Mock(),generation=1,status={'battle_auto':dict(active=False,pending=False,available=True,reason='Only this battle')},runtime=NS(submit=Mock()),watch=Mock())
        self.view=BattlePanel(self.monitor);self.view.window.geometry('350x820');self.s=state();self.view.update(self.s);self.root.update()
    def tearDown(self):self.root.destroy()
    def test_selected_reserve_stays_separate_from_active_and_does_not_open_inspector(self):
        self.assertEqual(self.view.selected_uid,'foe1');self.view.inspect(1);self.root.update()
        self.assertEqual(self.view.selected_uid,'foe2');self.assertEqual(self.view.active_uid,'foe1');self.assertIn('slot 2',self.view.heading.cget('text'))
        self.view.update(deepcopy(self.s));self.assertEqual(self.view.selected_uid,'foe2')
        self.s['battle']['enemies']=[dict(self.s['battle']['enemy_party'][1],party_slot=2,identity_valid=True)];self.view.update(self.s);self.assertEqual(self.view.selected_uid,'foe2');self.assertEqual(self.view.active_uid,'foe2')
    def test_end_clears_all_visible_data(self):
        self.view.update(dict(in_battle=False));self.root.update()
        self.assertFalse(self.view.body.winfo_ismapped());self.assertFalse(self.view.footer.winfo_ismapped());self.assertFalse(self.view.opponents);self.assertIsNone(self.view.selected_uid)
    def test_team_and_action_fit_820_pixels_with_all_six_opponents(self):
        for i in range(3,7):m=mon(3,i);m['uid']='foe'+str(i);self.s['battle']['enemy_party'].append(m)
        self.view.update(self.s);self.root.update();bottom=self.view.cards[-1].winfo_rooty()+self.view.cards[-1].winfo_height();self.assertLessEqual(bottom,self.view.auto.winfo_rooty())
    def test_live_types_override_species_and_wrong_identity_does_not(self):
        from pokemon_red.battle_panel import opponents
        self.s['battle']['enemies'][0]['types']=[11];row=opponents(self.s,ROOT)[0];self.assertEqual(row['types'],[11])
        self.s['battle']['enemies'][0]['uid']='wrong';row=opponents(self.s,ROOT)[0];self.assertFalse(row['active']);self.assertNotEqual(row['types'],[11])
    def test_autobattle_click_is_async_and_error_does_not_take_over_other_bot(self):
        future=Future();self.monitor.runtime.submit.return_value=future;self.view.toggle_auto();self.monitor.runtime.submit.assert_called_once_with('battle_auto',True)
        future.set_exception(RuntimeError('Управляет другая автоматизация'));failure=self.monitor.watch.call_args.args[2];failure(future.exception());self.assertIn('other',self.view.auto_reason.cget('text'))

if __name__=='__main__':unittest.main()
