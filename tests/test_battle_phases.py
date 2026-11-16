"""Resume all ordinary battle screens; capture isolation and cancellation rules."""
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock,patch
from copy import deepcopy
import sys,tempfile,json,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from test_battle_sidebar import state,controller
from pokemon_red.battle_flow import phase
from pokemon_red.manual_battle import eligibility
from pokemon_red.battle_fighter import BattleFighter
from pokemon_red.encounter_capture import eligibility as capture_eligibility,PokeballOnly,set_enabled

class PhaseTests(unittest.TestCase):
    def test_all_entry_screens_are_eligible_even_with_transitioning_live_battlers(self):
        cases=[('message',dict(callback='BattleMainCB2')),('yes_no',dict(callback='BattleMainCB2',battle_script_opcode=0x67,yes_no_state=1)),('party',dict(callback='CB2_UpdatePartyMenu',tasks=[{'name':'Task_HandleChooseMonInput'}])),('party_context',dict(callback='CB2_UpdatePartyMenu',tasks=[{'name':'Task_HandleSelectionMenuInput'}])),('party_blocked',dict(callback='CB2_UpdatePartyMenu',party_action=2)),('summary',dict(callback='CB2_RunPokemonSummaryScreen',summary_mode=0)),('bag',dict(callback='CB2_BagMenuRun')),('item_target',dict(callback='CB2_UpdatePartyMenu',party_action=3)),('move_order',dict(callback='BattleMainCB2',controllers=['HandleMoveSwitching'])),('target',dict(callback='BattleMainCB2',controllers=['HandleInputChooseTarget'])),('wait',dict(callback='CB2_InitPartyMenu'))]
        for expected,c in cases:
            with self.subTest(expected=expected):
                s=state();s['controls']=c;s['telemetry_valid']=False;s['battle']['telemetry_valid']=False;s['battle']['allies']=[]
                self.assertEqual(phase(s),expected);self.assertIsNone(eligibility(s))
    def test_win_messages_can_be_completed_but_learning_and_loss_need_the_player(self):
        s=state();s['battle']['outcome']=1;self.assertIsNone(eligibility(s))
        for change in ['learn','summary_learn','summary_forget','loss']:
            s=state()
            if change=='learn':s['decision']={'party_slot':1}
            if change in ('summary_learn','summary_forget'):s['controls']=dict(callback='CB2_RunPokemonSummaryScreen',summary_mode=2 if change=='summary_learn' else 3)
            if change=='loss':s['battle']['outcome']=2
            self.assertIsNotNone(eligibility(s))
    def fighter(self):
        f=BattleFighter.__new__(BattleFighter);f.root=ROOT;f.tap=Mock();f.wait=Mock();f.party_select=Mock();f.bot=NS(handoff=Mock(side_effect=RuntimeError('handoff')));return f
    def test_optional_switch_is_declined_for_both_cursor_positions(self):
        f=self.fighter()
        for cursor in [0,1]:
            s=state();s['controls'].update(battle_script_opcode=0x67,yes_no_state=1,yes_no_cursor=cursor)
            f.step(s);self.assertEqual(f.tap.call_args.args,('B',))
    def test_wild_faint_prompt_chooses_yes_without_accidentally_fleeing(self):
        f=self.fighter();s=state();s['controls'].update(battle_script_opcode=0x67,yes_no_state=1,player_fainted=True,yes_no_cursor=1)
        f.step(s);self.assertEqual(f.tap.call_args.args,('UP',));s['controls']['yes_no_cursor']=0;f.step(s);self.assertEqual(f.tap.call_args.args,('A',))
    def test_forced_party_selection_does_not_require_an_active_enemy(self):
        f=self.fighter();s=state();s['controls'].update(callback='CB2_UpdatePartyMenu',tasks=[dict(name='Task_HandleChooseMonInput')],player_fainted=True);s['battle']['enemies']=[];s['battle']['allies']=[];s['battle']['telemetry_valid']=False
        f.step(s);f.party_select.assert_called_once_with(s['party'][0]['uid'])
    def test_optional_party_context_summary_and_item_screens_back_out(self):
        for cb,tasks,action in [('CB2_UpdatePartyMenu',['Task_HandleChooseMonInput'],0),('CB2_UpdatePartyMenu',['Task_HandleSelectionMenuInput'],0),('CB2_RunPokemonSummaryScreen',[],0),('CB2_BagMenuRun',[],0),('CB2_UpdatePartyMenu',[],3)]:
            f=self.fighter();s=state();s['controls'].update(callback=cb,tasks=[dict(name=t) for t in tasks],party_action=action);f.step(s);self.assertEqual(f.tap.call_args.args,('B',))
    def test_level_up_stat_pages_accept_confirmation_without_selecting_moves(self):
        f=self.fighter();s=state();s['controls'].update(battle_script_opcode=0x6c,controllers=['PlayerBufferRunCommand'])
        f.step(s);self.assertEqual(f.tap.call_args.args,('B',))
    def test_forget_move_summary_is_protected_by_the_per_frame_guard(self):
        from pokemon_red.manual_battle import frame_guard
        c=controller();c.automation.running=True;c.automation.script=ROOT/'Bots/auto_battle.py';c.game.read8=lambda a:2 if a==0x439 else 0
        with patch('pokemon_red.manual_battle.symbols',return_value={'gMain':0,'gBattleOutcome':1}),patch('pokemon_red.manual_battle.read_decision',return_value=None),patch('pokemon_red.manual_battle.read_learning_control',return_value={'evo':None,'summary':{'mode':3}}):
            self.assertTrue(frame_guard(c))
        self.assertEqual(c.automation.stop.call_args.kwargs['status'],'attention');c.pause.assert_called_once_with(save=False)
    def test_incomplete_combat_identity_never_sends_an_attack(self):
        f=self.fighter();s=state();s['controls']['controllers']=['HandleInputChooseMove'];s['battle']['telemetry_valid']=False
        f.step(s);f.wait.assert_called_once();f.tap.assert_not_called();f.party_select.assert_not_called()

class CaptureTests(unittest.TestCase):
    def wild(self):s=state();s['battle']['flags']=0;s['controls']['controllers']=['HandleInputChooseAction'];return s
    def test_start_requires_the_wild_battle_scene(self):
        self.assertIsNone(capture_eligibility(self.wild()))
        for mode in ['trainer','party','bag','outside','dead','animation']:
            s=self.wild()
            if mode=='trainer':s['battle']['flags']=8
            if mode in ('party','bag'):s['controls']['callback']='CB2_UpdatePartyMenu' if mode=='party' else 'CB2_BagMenuRun'
            if mode=='outside':s['in_battle']=False
            if mode=='dead':s['battle']['enemies'][0]['hp']=0
            if mode=='animation':s['controls']['controllers']=['PlayerHandleBallThrowAnim']
            self.assertIsNotNone(capture_eligibility(s),mode)
    def test_throw_only_never_weakens_or_uses_a_different_ball(self):
        p=PokeballOnly();self.assertEqual(p.decide({}, {},{1:1,2:99,4:1},1)['ball_id'],4)
        self.assertEqual(p.decide({}, {},{1:1,2:99},1)['action'],'attention')
    def test_stop_targets_only_encounter_operation_and_carries_click_time(self):
        c=controller();c.operation=NS(active=True,kind='local',command=Mock());set_enabled(c,False,12);c.operation.command.assert_not_called()
        c.operation.kind='encounter';set_enabled(c,False,12);c.operation.command.assert_called_once_with('cancel',requested_at=12)
    def test_late_cancel_after_capture_does_not_discard_success(self):
        from pokemon_red.operation_worker import Worker,Cancelled
        with tempfile.TemporaryDirectory() as t:
            w=Worker.__new__(Worker);w.job=Path(t);w.spec={'kind':'encounter'};w.cancel=True;w.pause=False;w.caught_at=10;w.heartbeat=Mock()
            (w.job/'command.json').write_text(json.dumps(dict(requested_at=11)));w.safe_point()
            (w.job/'command.json').write_text(json.dumps(dict(requested_at=9)))
            with self.assertRaises(Cancelled):w.safe_point()

if __name__=='__main__':unittest.main()
