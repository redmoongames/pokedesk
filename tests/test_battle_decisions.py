"""Rejected moves, paid/free switches and backing out of an active-party choice."""
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock,patch
from copy import deepcopy
import sys,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.battle_conditions import move_blockers
from pokemon_red.battle_strategy import choose_fighter,attack_plan
from pokemon_red.battle_fighter import BattleFighter
from pokemon_red.training import RouteTrainer,best_move
from pokemon_red.catalog import move
from pokemon_red.mechanics import wild_mon,ranked_attacks
from test_battle_sidebar import state

class MoveLegalityTests(unittest.TestCase):
    def setUp(self):
        self.mon=dict(wild_mon(25,30,ROOT),uid='own',slot=1);self.mon['moves']=[dict(move(n,ROOT),current_pp=10) for n in (85,33,45)]
        self.enemy=wild_mon(16,25,ROOT)
    def test_disable_excludes_the_strongest_attack_everywhere(self):
        self.assertEqual(best_move(self.mon,self.enemy,ROOT),0);self.mon['disabled_move']=85
        self.assertEqual(move_blockers(self.mon,self.mon['moves'][0]),['disable']);self.assertEqual(best_move(self.mon,self.enemy,ROOT),1)
        self.assertNotIn(0,[i for i,_ in ranked_attacks(self.mon,self.enemy,ROOT)])
    def test_torment_encore_taunt_choice_and_imprison(self):
        for change,index,reason in [(dict(status2=1<<31,last_move=85),0,'torment'),(dict(encore_turns=2,encored_move=33),0,'encore'),(dict(taunt_turns=2),2,'taunt'),(dict(held_item=186,choice_move=33),0,'choice_band'),(dict(imprisoned_moves=[85]),0,'imprison')]:
            with self.subTest(reason=reason):self.assertIn(reason,move_blockers(dict(self.mon,**change),self.mon['moves'][index]))
        self.assertFalse(move_blockers(dict(self.mon,encore_turns=0,encored_move=33),self.mon['moves'][0]))
        self.assertFalse(move_blockers(dict(self.mon,held_item=186,choice_move=0xffff),self.mon['moves'][0]))
    def test_zero_pp_and_explicit_snapshot_restrictions_are_never_selected(self):
        self.mon['moves'][0].update(usable=False,unusable_reasons=['disable']);self.mon['moves'][1]['current_pp']=0
        self.assertIsNone(best_move(self.mon,self.enemy,ROOT));self.assertIsNone(attack_plan(self.mon,self.enemy,ROOT))

class SwitchCostTests(unittest.TestCase):
    def setUp(self):
        self.s=state();current=self.s['party'][0];current['uid']='own';current['moves']=[dict(move(33,ROOT),current_pp=10)];self.s['battle']['allies']=[dict(current,party_slot=1)]
        reserve=deepcopy(current);reserve.update(uid='reserve',slot=2,hp=reserve['max_hp']);self.s['party'].append(reserve)
        self.turns={'own':3,'reserve':1}
    def rows(self,mon,enemy,root):
        if mon['uid'] not in self.turns:return []
        turns=self.turns[mon['uid']];damage=enemy['hp']/turns
        return [(0,dict(turns=turns,min=damage,max=damage,mean=damage,accuracy=1,ohko=int(turns==1),move_id=33))]
    def decide(self,**kw):
        with patch('pokemon_red.battle_strategy.ranked_attacks',side_effect=self.rows),patch('pokemon_red.battle_strategy.incoming_risk',return_value=0):return choose_fighter(self.s,ROOT,**kw)
    def test_switch_costs_a_turn_and_exact_ties_keep_current(self):
        best=self.decide();self.assertEqual(best['mon']['uid'],'reserve');self.assertEqual(best['cost'],2)
        self.turns['own']=2;self.assertEqual(self.decide()['mon']['uid'],'own')
        self.turns['own']=1;self.assertEqual(self.decide()['mon']['uid'],'own')
    def test_free_or_forced_switch_has_no_attack_cost(self):
        self.turns['own']=2
        self.assertEqual(self.decide(free_switch=True)['cost'],1);self.assertEqual(self.decide(free_switch=True)['mon']['uid'],'reserve')
        self.s['party'][0]['hp']=0;self.assertEqual(self.decide(forced=True)['cost'],1)
    def test_trapping_keeps_a_usable_current_fighter(self):
        self.s['battle']['allies'][0]['status2']=0x2000
        self.assertEqual(self.decide()['mon']['uid'],'own')
    def test_low_pp_can_finish_with_a_second_move(self):
        mon=self.s['party'][0];mon['moves']=[dict(move(33,ROOT),current_pp=1),dict(move(98,ROOT),current_pp=1)]
        rows=[(0,dict(turns=2,min=6,max=6,mean=6,accuracy=1,move_id=33)),(1,dict(turns=3,min=4,max=4,mean=4,accuracy=1,move_id=98))]
        with patch('pokemon_red.battle_strategy.ranked_attacks',return_value=rows):
            self.assertEqual(attack_plan(mon,dict(hp=10),ROOT)['turns'],2)
            mon['moves'][1]['current_pp']=0;self.assertIsNone(attack_plan(mon,dict(hp=10),ROOT))

class CancellationTests(unittest.TestCase):
    def fighter(self):
        f=BattleFighter.__new__(BattleFighter);f.root=ROOT;f.tap=Mock();f.wait=Mock();f.party_select=Mock();f.bot=NS(event=Mock(),handoff=Mock(side_effect=RuntimeError('handoff')));return f
    def test_optional_prompt_and_party_cancel_when_best_is_already_active(self):
        for screen in ('yes_no','party'):
            f=self.fighter();s=state();s['battle']['next_enemy_slot']=2;f.choose=Mock(return_value=s['party'][0])
            if screen=='yes_no':s['controls'].update(battle_script_opcode=0x67,yes_no_state=1,yes_no_cursor=0)
            else:s['controls'].update(callback='CB2_UpdatePartyMenu',tasks=[dict(name='Task_HandleChooseMonInput')])
            f.step(s);self.assertEqual(f.tap.call_args.args,('B',));f.party_select.assert_not_called()
    def test_optional_prompt_accepts_only_a_different_better_fighter(self):
        f=self.fighter();s=state();s['battle']['next_enemy_slot']=2;f.choose=Mock(return_value=dict(uid='reserve'));s['controls'].update(battle_script_opcode=0x67,yes_no_state=1,yes_no_cursor=0)
        f.step(s);self.assertEqual(f.tap.call_args.args,('A',));f.party_select.assert_called_once_with('reserve')
    def test_party_select_active_uid_backs_out_without_confirming_it(self):
        s=state();s['frame']=0;s['controls'].update(callback='CB2_UpdatePartyMenu',tasks=[dict(name='Task_HandleChooseMonInput')]);t=RouteTrainer.__new__(RouteTrainer);t.state=lambda:s;t.bot=NS(event=Mock());keys=[]
        def tap(key,wait=0):keys.append(key);s['frame']+=6;s['controls']['callback']='BattleMainCB2'
        t.tap=tap;t.party_select(s['party'][0]['uid']);self.assertEqual(keys,['B'])
    def test_temporary_party_cursor_index_does_not_cancel_a_real_switch(self):
        s=state();s['frame']=0;current=s['party'][0];reserve=deepcopy(current);reserve.update(uid='reserve',slot=2);s['party'].append(reserve)
        s['battle']['allies']=[];s['battle']['unverified_battlers']=[dict(uid=current['uid'],position=0,party_slot=2)]
        s['controls'].update(callback='CB2_UpdatePartyMenu',tasks=[dict(name='Task_HandleChooseMonInput')],player_party_slot=2,party_cursor=1,party_action=0)
        t=RouteTrainer.__new__(RouteTrainer);t.state=lambda:s;t.bot=NS(event=Mock());keys=[]
        def tap(key,wait=0):keys.append(key);s['frame']+=6;s['controls']['callback']='BattleMainCB2'
        t.tap=tap;t.party_select('reserve');self.assertEqual(keys,['A'])
    def test_repeated_rejected_attack_stops_but_pp_progress_resets_guard(self):
        f=self.fighter();s=state();own=s['party'][0];foe=s['battle']['enemies'][0]
        for _ in range(3):f.attack_guard(s,own,foe,0)
        own['moves'][0]['current_pp']-=1;f.attack_guard(s,own,foe,0);f.bot.handoff.assert_not_called()
        for _ in range(2):f.attack_guard(s,own,foe,0)
        with self.assertRaisesRegex(RuntimeError,'handoff'):f.attack_guard(s,own,foe,0)
        self.assertEqual(f.bot.handoff.call_args.args[0],'autobattle_rejected_move')
    def test_transient_enemy_decryption_waits_without_input_and_then_resumes(self):
        f=self.fighter();start=state();start['frame']=0;partial=deepcopy(start);partial['frame']=2;partial['battle']['enemy_party']=partial['battle']['enemy_party'][:1]
        recovered=deepcopy(start);recovered['frame']=4;finished=dict(in_battle=False,frame=6)
        f.state=Mock(side_effect=[start,partial,recovered,finished]);f.step=Mock(return_value=True)
        f.run();f.wait.assert_called_once_with(2);f.step.assert_called_once_with(recovered);f.tap.assert_not_called();f.bot.handoff.assert_not_called()
    def test_completed_turns_are_progress_even_without_damage_or_pp_loss(self):
        f=self.fighter();s=state();own=s['party'][0];foe=s['battle']['enemies'][0];own['status_code']=0x20
        for turn in range(10):s['battle']['turn']=turn;f.attack_guard(s,own,foe,0)
        f.bot.handoff.assert_not_called()
    def test_a_real_new_enemy_identity_still_stops_single_battle_ownership(self):
        f=self.fighter();start=state();start['frame']=0;changed=deepcopy(start);changed['frame']=2;changed['battle']['enemy_party'][1]['uid']='new-encounter'
        f.state=Mock(side_effect=[start,changed]);f.step=Mock()
        with self.assertRaisesRegex(RuntimeError,'handoff'):f.run()
        f.step.assert_not_called();f.tap.assert_not_called()

if __name__=='__main__':unittest.main()
