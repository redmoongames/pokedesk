from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
import sys,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from test_grind import mon
from pokemon_red.move_plan import compile_plan,default_moves,require_approval,needs_approval,allows_evolution
from pokemon_red.move_plan_ui import review_lines
from pokemon_red.run_context import RunConfig
from pokemon_red.session_controller import SessionController as Monitor
from pokemon_red.learning import LearningRuntime
from pokemon_red.move_plan import PlanMismatch

class MoveReviewTests(unittest.TestCase):
    def test_default_kept_moves_cannot_silently_approve_skips_or_evolution(self):
        m=mon(1,14,'t',[33,45,73,22]);p=compile_plan(m,16,default_moves(m,16,ROOT),ROOT)
        self.assertEqual([s['action'] for s in p['decisions']],['skip','skip','evolve'])
        with self.assertRaisesRegex(ValueError,'решения'):require_approval(p,None)
        require_approval(p,p['id'])
    def test_changed_goal_moves_species_or_target_invalidates_confirmation(self):
        m=mon(1,14,'t',[33,45,73,22]);p=compile_plan(m,16,[33,73,22,79],ROOT)
        changes=[compile_plan(m,17,[33,73,22,79],ROOT),compile_plan(m,16,[33,45,73,22],ROOT),compile_plan(dict(m,uid='other'),16,[33,73,22,79],ROOT),compile_plan(m,16,[33,73,22,79],ROOT,'stay')]
        for new in changes:
            with self.assertRaises(ValueError):require_approval(new,p['id'])
    def test_evolution_and_its_cancellation_both_require_explicit_review(self):
        m=mon(11,9,'t',[33,81,106])
        for mode in ('natural','stay'):
            p=compile_plan(m,10,default_moves(m,10,ROOT,mode),ROOT,mode);self.assertTrue(needs_approval(p))
            with self.assertRaises(ValueError):require_approval(p,None)
    def test_intermediate_evolution_target_keeps_metapod_and_cancels_butterfree(self):
        m=mon(10,5,'t',[33,81]);p=compile_plan(m,12,[33,81,106],ROOT,'stop_at:11')
        self.assertEqual(p['final_species'],11);self.assertEqual([(s['level'],s['action']) for s in p['decisions']],[(7,'evolve'),(10,'cancel'),(11,'cancel'),(12,'cancel')]);self.assertTrue(allows_evolution('stop_at:11',10));self.assertFalse(allows_evolution('stop_at:11',11));self.assertIn('Отменить',review_lines(p,ROOT))
        with self.assertRaises(ValueError):compile_plan(m,6,[33,81],ROOT,'stop_at:12')
    def test_free_slot_without_evolution_has_no_destructive_decision(self):
        m=mon(1,6,'t',[33,45]);p=compile_plan(m,7,[33,45,73],ROOT);self.assertFalse(needs_approval(p));require_approval(p,None)
    def test_review_shows_evolution_before_new_form_move_at_the_same_level(self):
        m=mon(11,9,'t',[33,81,106]);p=compile_plan(m,10,[33,81,106,93],ROOT)
        lines=review_lines(p,ROOT).splitlines();self.assertIn('→',lines[0]);self.assertIn('Confusion',lines[1])
    def test_server_rejects_missing_approval_before_installing_runtime(self):
        m=mon(1,14,'t',[33,45,73,22]);m['location']='party';m['slot']=1
        monitor=SimpleNamespace(folder=ROOT,game=object(),inventory_snapshot=lambda:dict(party=[m],boxes=[]),automation=SimpleNamespace(move_runtime=None,record_event=Mock(),suspend_input=Mock()),create_slot=Mock())
        args=dict(uid='t',goal=16,final_moves=[33,45,73,22],evolution_mode='natural')
        with patch('pokemon_red.telemetry.read_decision',return_value=None):
            with self.assertRaises(ValueError):Monitor.install_move_plan(monitor,args)
            self.assertIsNone(monitor.automation.move_runtime)
            p=compile_plan(m,16,args['final_moves'],ROOT);result=Monitor.install_move_plan(monitor,dict(args,approved_plan_id=p['id']));self.assertEqual(result['id'],p['id']);self.assertIsNotNone(monitor.automation.move_runtime)
    def test_config_preserves_approval_and_intermediate_target(self):
        cfg=RunConfig.parse(dict(approved_plan_id='a'*24,evolution_mode='stop_at:11'));self.assertEqual(cfg.approved_plan_id,'a'*24)
        with self.assertRaises(ValueError):RunConfig.parse(dict(approved_plan_id='unreviewed'))
    def test_cancellation_cannot_extend_past_the_explicitly_reviewed_levels(self):
        m=mon(11,9,'t',[33,81,106]);p=compile_plan(m,10,[33,81,106],ROOT,'stay')
        current=dict(m,level=11,slot=1);runtime=LearningRuntime(p,event=Mock(),checkpoint=Mock(),suspend=Mock())
        control=dict(frame=100,callback='CB2_EvolutionSceneUpdate',evo=dict(slot=1,pre=11,post=12,state=8,bits=1),stable=False)
        with patch('pokemon_red.learning.read_learning_control',return_value=control),patch('pokemon_red.learning.read_learning_mon',return_value=current):
            with self.assertRaisesRegex(PlanMismatch,'не подтверждена'):runtime.poll(SimpleNamespace(frame=100,root=ROOT))
        self.assertEqual(runtime.mask,0);self.assertIsNone(runtime.evo)

if __name__=='__main__':unittest.main()
