"""Party drafts, ordered PC replacement and revocable asynchronous launch."""
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
from itertools import permutations
import sys, unittest, copy, threading, time, shutil
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.party_management import validate_roster,validate_field,order_party,roster_plan
from pokemon_red.workspace import task_summary


def mon(uid,**kw):return dict(uid=uid,level=10,hp=20,checksum_valid=True,is_egg=False,**kw)


class PartyRulesTests(unittest.TestCase):
    def setUp(self):self.inv=dict(ready=True,party=[mon('a'),mon('b')],boxes=[mon('c')],daycare=[mon('day')])
    def test_stable_uid_is_used_and_daycare_is_not_a_pc_slot(self):
        self.assertEqual([m['uid'] for m in validate_roster(self.inv,['c','a'])],['c','a'])
        for desired in ([],['a']*2,['day'],['missing'],list('1234567')):
            with self.subTest(desired=desired),self.assertRaises(ValueError):validate_roster(self.inv,desired)
    def test_mail_is_retained_and_pc_capacity_is_checked_before_inputs(self):
        self.inv['party'][0]['held_item']=121
        validate_roster(self.inv,['a','c'])
        with self.assertRaises(ValueError):validate_roster(self.inv,['b','c'])
        self.inv['party'][0]['held_item']=0;self.inv['boxes']=[mon(str(i)) for i in range(419)]
        with self.assertRaises(ValueError):validate_roster(self.inv,['1','2'])
    def test_menu_battle_and_mid_step_cannot_start_a_replacement(self):
        valid=dict(ready=True,in_battle=False,controls=dict(callback='CB2_Overworld',field_locked=False,moving=False))
        validate_field(valid)
        for field,value in [('in_battle',True),('ready',False)]:
            with self.assertRaises(ValueError):validate_field(dict(valid,**{field:value}))
        for field,value in [('callback','CB2_UpdatePartyMenu'),('field_locked',True),('moving',True)]:
            with self.assertRaises(ValueError):validate_field(dict(valid,controls=dict(valid['controls'],**{field:value})))
    def test_every_six_slot_permutation_is_restored_with_first_slot_swaps(self):
        for target in permutations('abcdef'):
            party=[mon(uid) for uid in 'abcdef']
            def lead(uid):
                index=next(i for i,m in enumerate(party) if m['uid']==uid)
                party[0],party[index]=party[index],party[0]
            order_party(NS(state=lambda:dict(party=party),lead=lead),target)
            self.assertEqual([m['uid'] for m in party],list(target))


class WorkspaceResolutionTests(unittest.TestCase):
    def monitor(self,**status):
        return NS(status=status,automation=NS(info=lambda:dict(running=True,status='running',script='change_party.py',stage='PC')),
                  operation=NS(data={}),pending_start=False,notice='')
    def test_save_failure_precedes_ongoing_task_and_manual_battle(self):
        m=self.monitor(save_failed=True,battle_auto=dict(active=True))
        self.assertEqual(task_summary(m).kind,'save_error')
        m.status['save_failed']=False;self.assertEqual(task_summary(m).kind,'party')
    def test_an_enabled_delivery_queue_does_not_hide_the_actual_controller(self):
        m=self.monitor();m.delivery=NS(data=dict(enabled=True))
        self.assertEqual(task_summary(m).kind,'party')
    def test_partial_party_stop_explains_resume_and_rollback(self):
        m=self.monitor();m.automation.info=lambda:dict(running=False,status='stopped',script='change_party.py')
        result=task_summary(m);self.assertEqual(result.kind,'stopped');self.assertIn('F8',result.stage)
    def test_background_work_does_not_become_main_controller(self):
        m=self.monitor();m.automation.info=lambda:dict(running=False,status='idle')
        m.delivery=NS(data={'rows':[dict(status='preparing')]})
        self.assertEqual(task_summary(m).kind,'idle')


class PartyLaunchTests(unittest.TestCase):
    def test_reserved_delivery_rejects_party_change_before_any_file_or_input(self):
        from pokemon_red.session_controller import SessionController
        state=dict(ready=True,in_battle=False,controls=dict(callback='CB2_Overworld',field_locked=False,moving=False))
        c=NS(session_state=lambda:state,inventory_snapshot=lambda:dict(ready=True,party=[mon('a')],boxes=[]),
             automation=NS(running=False),pending_start=None,operation=NS(active=False),delivery=NS(enabled=True),closing=False,session_transition=False)
        with self.assertRaises(ValueError):SessionController.start_party_change(c,dict(desired=['a']))
    def test_new_launch_is_epoch_sensitive(self):
        from pokemon_red.engine_runtime import SENSITIVE
        self.assertIn('start_party_change',SENSITIVE)


class PartyEditorTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from pokemon_red.ui import theme
        from pokemon_red.party_editor import PartyEditor
        from test_grind import mon as real_mon
        self.root=tk.Tk();self.root.geometry('540x900');theme(self.root);self.errors=[]
        self.root.report_callback_exception=lambda _,e,t:self.errors.append(str(e))
        party=[dict(real_mon(25,10,'a',[84]),slot=1),dict(real_mon(1,12,'b',[33]),slot=2)]
        box=dict(real_mon(19,3,'c',[33]),location='box',box=0,box_slot=0)
        inv=dict(ready=True,party=party,boxes=[box])
        self.m=NS(folder=ROOT,generation=1,last_state=dict(ready=True,party=party,map=dict(name='ViridianCity'),position=dict(x=12,y=18),controls=dict(callback='CB2_Overworld',moving=False,field_locked=False)),
                  status={},pending_takeover=False,ai_controlled=lambda:False,inventory_snapshot=lambda:inv,start_party_change=Mock(),watch=Mock(),travel_snapshot=Mock())
        self.p=NS(monitor=self.m);self.body=tk.Frame(self.root);self.body.pack(fill='both',expand=True)
        self.editor=PartyEditor(self.p,self.body);self.root.update()
    def tearDown(self):
        self.editor.close();self.root.destroy();self.assertFalse(self.errors)
    def test_draft_remove_add_and_reorder_do_not_mutate_live_party(self):
        e=self.editor;e.selected.selection_set('a');e.remove_selected();e.available.selection_set('c');e.add_selected()
        self.assertEqual(e.desired,['b','c']);self.assertEqual([m['uid'] for m in self.m.last_state['party']],['a','b'])
        e.selected.selection_set('c');e.move(-1);self.assertEqual(e.desired,['c','b'])
        self.m.start_party_change.assert_not_called();self.assertEqual(e.apply.cget('state'),'disabled')
    def test_back_keeps_draft_and_stale_generation_drops_it(self):
        from pokemon_red.party_editor import PartyEditor
        e=self.editor;e.desired=['c','a'];e.query.set('Rat');e.close();self.body.destroy()
        self.body=__import__('tkinter').Frame(self.root);self.body.pack(fill='both',expand=True)
        self.editor=PartyEditor(self.p,self.body);self.assertEqual(self.editor.desired,['c','a']);self.assertEqual(self.editor.query.get(),'Rat')
    def test_tables_do_not_gain_blank_space_from_the_scrollbar(self):
        self.root.update();table=self.editor.available
        self.assertLess(table.master.winfo_height()-table.winfo_height(),10)
        self.assertLess(self.editor.add.winfo_y()-(table.master.winfo_y()+table.master.winfo_height()),20)
    def test_move_or_load_invalidates_review_before_apply(self):
        e=self.editor;e.plan=dict(desired=e.desired,label='Viridian',steps=20,added=[],removed=[])
        e.review_key=e.key();e.update_controls();self.assertEqual(e.apply.cget('state'),'normal')
        self.m.generation+=1;e.start();self.m.start_party_change.assert_not_called();self.assertEqual(e.apply.cget('state'),'disabled')
    def test_delivery_reservation_blocks_apply_between_transfer_cycles(self):
        e=self.editor;e.plan=dict(desired=e.desired,label='Viridian',steps=20,added=[],removed=[]);e.review_key=e.key()
        self.m.delivery=NS(data=dict(enabled=True));e.start();self.m.start_party_change.assert_not_called()
    def test_busy_main_game_blocks_apply_even_with_a_valid_old_review(self):
        e=self.editor;e.plan=dict(desired=e.desired,label='Viridian',steps=20,added=[],removed=[]);e.review_key=e.key()
        self.m.ai_controlled=lambda:True;e.start();self.m.start_party_change.assert_not_called()


if __name__=='__main__':unittest.main()
