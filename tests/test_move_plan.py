"""Reachability, chronological contracts, evolution and fail-closed menu input."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import copy,sys,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from test_grind import mon
from pokemon_red.move_plan import compile_plan,curriculum,default_moves,PlanTracker,PlanMismatch,ids
from pokemon_red.learning import LearningRuntime
from pokemon_red.run_context import RunConfig,planning_key
from pokemon_red.catalog import move
from pokemon_red.engine import BUTTONS

class CompilerTests(unittest.TestCase):
    def test_same_level_moves_and_old_form_before_evolution(self):
        m=mon(1,14,'t',[33,45,73,22]);p=compile_plan(m,16,[33,73,22,79],ROOT)
        self.assertEqual([(s['kind'],s['level']) for s in p['steps']],[('learn',15),('learn',15),('evolve',16)])
        self.assertEqual([s['action'] for s in p['steps']],['skip','replace','evolve']);self.assertEqual(p['steps'][1]['forget'],45);self.assertEqual(p['final_species'],2)
    def test_both_evolutions_and_free_slots_are_chronological(self):
        m=mon(10,5,'t',[33,81]);p=compile_plan(m,10,[33,81,106,93],ROOT)
        self.assertEqual([(s['kind'],s['level'],s.get('move')) for s in p['steps']],[('evolve',7,None),('learn',7,106),('evolve',10,None),('learn',10,93)])
        self.assertEqual(p['steps'][1]['source'],'evolution');self.assertEqual(p['steps'][3]['action'],'auto')
    def test_delayed_evolution_does_not_grant_past_level_moves(self):
        m=mon(11,11,'t',[33,81,106]);data=curriculum(m,12,ROOT);self.assertEqual(data['final_species'],12)
        self.assertNotIn(93,{r['id'] for r in data['available']})
        with self.assertRaisesRegex(ValueError,'нельзя получить'):compile_plan(m,12,[33,81,106,93],ROOT)
    def test_stay_mode_never_assumes_evolved_learnset(self):
        m=mon(11,9,'t',[33,81,106]);p=compile_plan(m,15,[33,81,106],ROOT,'stay');self.assertEqual(p['final_species'],11);self.assertEqual(p['steps'],[])
        with self.assertRaises(ValueError):compile_plan(m,15,[33,81,106,93],ROOT,'stay')
    def test_stone_trade_and_future_moves_are_not_offered_as_level_rewards(self):
        m=mon(25,12,'t',[84,45,39,86]);available={r['id'] for r in curriculum(m,25,ROOT)['available']};self.assertNotIn(85,available)
        with self.assertRaises(ValueError):compile_plan(m,25,[84,86,98,85],ROOT)
        self.assertEqual(curriculum(mon(64,20,'a',[93,134,100]),40,ROOT)['final_species'],64)
    def test_cannot_delete_hm_or_remove_existing_slot(self):
        m=mon(1,14,'t',[15,45,73,22])
        with self.assertRaises(ValueError):compile_plan(m,16,[77,79,73,22],ROOT)
        with self.assertRaises(ValueError):compile_plan(m,16,[15,73,22],ROOT)
    def test_unwanted_free_slot_move_is_mandatory_then_replaceable(self):
        m=mon(1,6,'t',[33,45]);p=compile_plan(m,15,[33,22,77,79],ROOT,'stay')
        self.assertEqual(p['steps'][0]['action'],'auto');self.assertEqual(p['steps'][0]['move'],73);self.assertEqual(set(p['steps'][-1]['after']),{33,22,77,79})
        with self.assertRaises(ValueError):compile_plan(m,7,[33,45],ROOT)
    def test_four_status_moves_are_allowed_but_attack_kept_until_replacement(self):
        m=mon(1,14,'t',[33,45,73,22]);p=compile_plan(m,15,[45,73,77,79],ROOT)
        self.assertTrue(any(move(n,ROOT)['power'] for n in p['steps'][0]['before']));self.assertTrue(any(move(n,ROOT)['power'] for n in p['steps'][0]['after']));self.assertFalse(any(move(n,ROOT)['power'] for n in p['steps'][-1]['after']))
    def test_resume_pending_prompt_includes_second_same_level_move(self):
        m=mon(1,15,'t',[33,45,73,22]);p=compile_plan(m,15,[33,73,22,79],ROOT,pending=dict(uid='t',move_id=77,source='battle'));self.assertEqual([s['move'] for s in p['steps']],[77,79])
    def test_config_and_cache_include_final_moves_and_evolution_mode(self):
        m=mon(1,14,'t',[33,45,73,22]);inv=dict(ready=True,party=[m],boxes=[]);base=dict(trainee='t',target=16,final_moves=[33,73,22,79]);key=planning_key(inv,base)
        self.assertNotEqual(key,planning_key(inv,dict(base,evolution_mode='stay')));self.assertNotEqual(key,planning_key(inv,dict(base,final_moves=[33,45,73,22])))
        with self.assertRaises(ValueError):RunConfig.parse(dict(base,final_moves=[True]))

class TrackerTests(unittest.TestCase):
    def test_expected_automatic_changes_can_be_observed_together(self):
        m=mon(10,5,'t',[33,81]);p=compile_plan(m,10,[33,81,106,93],ROOT);t=PlanTracker(p)
        after=mon(11,7,'t',[33,81,106]);self.assertEqual(len(t.observe(after)),2);self.assertEqual(t.index,2)
        final=mon(12,10,'t',[33,81,106,93]);self.assertEqual(len(t.observe(final,stable=True)),2);self.assertIsNone(t.next_step())
    def test_wrong_uid_moves_species_and_missed_evolution_are_rejected(self):
        m=mon(1,14,'t',[33,45,73,22]);p=compile_plan(m,16,[33,73,22,79],ROOT)
        for change in ('uid','moves','species','level'):
            a=copy.deepcopy(m)
            if change=='uid':a['uid']='other'
            elif change=='moves':a['moves'][0]['id']=15
            elif change=='species':a['species_id']=2
            else:a['level']=17
            with self.subTest(change=change),self.assertRaises(PlanMismatch):PlanTracker(p).observe(a)
    def test_prompt_must_match_source_level_and_new_move(self):
        m=mon(1,15,'t',[33,45,73,22]);p=compile_plan(m,15,[33,73,22,79],ROOT,pending=dict(uid='t',move_id=77))
        for choice in (dict(move_id=79,source='battle'),dict(move_id=77,source='evolution')):
            with self.assertRaises(PlanMismatch):PlanTracker(p).authorize(m,choice)

class ExecutorTests(unittest.TestCase):
    def setup_runtime(self,replace=True):
        m=mon(1,15,'t',[33,45,73,22]);m['slot']=3;pending=dict(uid='t',move_id=77,source='battle');finals=[33,77,73,22] if replace else [33,45,73,22]
        p=compile_plan(m,15,finals,ROOT,pending=pending);events=[];suspensions=[];r=LearningRuntime(p,event=lambda *a:events.append(a),checkpoint=lambda _:None,suspend=lambda:suspensions.append(True),pending=pending)
        c=dict(frame=100,callback='BattleMainCB2',evo=None,summary=None,battle=dict(op=0x5a,state=1,slot=3),cursor=0,move_id=77,stable=False)
        return m,r,c,events,suspensions
    def poll(self,r,m,c,choice=None):
        game=SimpleNamespace(frame=c['frame'],root=ROOT)
        with patch('pokemon_red.learning.read_learning_control',return_value=c),patch('pokemon_red.learning.read_learning_mon',return_value=m):r.poll(game,choice)
    def test_release_gap_prevents_reusing_previous_a_press(self):
        m,r,c,events,s=self.setup_runtime();choice=dict(party_slot=3,move_id=77,source='battle');self.poll(r,m,c,choice);self.assertTrue(r.owns_input);self.assertEqual(r.mask,0);self.assertTrue(s)
        c['frame']=108;self.poll(r,m,c,choice);self.assertEqual(r.mask,BUTTONS['A'])
        c['frame']=109;self.poll(r,m,c,choice);self.assertEqual(r.mask,0)
    def test_wrong_summary_never_confirms_a_destructive_choice(self):
        for change in ('uid','mode','moves','party','slot','return_callback'):
            m,r,c,_,_=self.setup_runtime();self.poll(r,m,c,dict(party_slot=3,move_id=77,source='battle'));summary=dict(uid='t',mode=2,moves=[33,45,73,22,77],party=True,slot=3,return_callback='ReshowBattleScreenAfterMenu',stage=2,cursor=0)
            summary[change]=dict(uid='other',mode=0,moves=[15,45,73,22,77],party=False,slot=1,return_callback='unknown')[change]
            c.update(frame=120,callback='CB2_RunPokemonSummaryScreen',battle=None,summary=summary)
            with self.subTest(change=change),self.assertRaises(PlanMismatch):self.poll(r,m,c)
            self.assertEqual(r.mask,0)
    def test_replacement_commits_only_after_native_party_changes(self):
        m,r,c,events,_=self.setup_runtime();self.poll(r,m,c,dict(party_slot=3,move_id=77,source='battle'));self.assertEqual(r.tracker.index,0)
        m['moves'][1]=dict(move(77,ROOT));c.update(frame=130,battle=dict(op=16,state=3,slot=3));self.poll(r,m,c);self.assertEqual(r.tracker.index,1);self.assertIsNone(r.active);self.assertTrue(any(e[0]=='move_plan_applied' for e in events))
    def test_unknown_screen_and_timeout_stop_before_more_input(self):
        for change in (dict(frame=120,callback='UnknownDialog'),dict(frame=2600)):
            m,r,c,_,_=self.setup_runtime();self.poll(r,m,c,dict(party_slot=3,move_id=77,source='battle'));c.update(change)
            with self.assertRaises(PlanMismatch):self.poll(r,m,c)
            self.assertEqual(r.mask,0)
    def test_transient_native_write_releases_all_input_then_recovers(self):
        m,r,c,events,suspensions=self.setup_runtime();m['checksum_valid']=False
        self.poll(r,m,c);self.assertTrue(r.owns_input);self.assertEqual(r.mask,0);self.assertTrue(suspensions)
        m['checksum_valid']=True;c['frame']=101;self.poll(r,m,c);self.assertFalse(r.owns_input);self.assertEqual(r.mask,0)
        m['checksum_valid']=False;c['frame']=108;self.poll(r,m,c);c['frame']=229
        with self.assertRaisesRegex(PlanMismatch,'не восстановились'):self.poll(r,m,c)
        self.assertEqual(r.mask,0)
    def test_evolution_choice_validates_summary_and_replacement(self):
        m=mon(11,9,'t',[33,81,106,45]);m['slot']=3;p=compile_plan(m,10,[33,81,106,93],ROOT)
        r=LearningRuntime(p,event=lambda *a:None,checkpoint=lambda _:None,suspend=lambda:None)
        m['level']=10;e=dict(slot=3,pre=11,post=12,state=0,bits=1,learn_state=0)
        c=dict(frame=100,callback='CB2_EvolutionSceneUpdate',evo=e,summary=None,battle=None,cursor=0,move_id=93,stable=False)
        self.poll(r,m,c);self.assertTrue(r.owns_input)
        m['species_id']=12;e.update(state=22,learn_state=4,yes=5,no=10);c['frame']=120
        self.poll(r,m,c,dict(party_slot=3,move_id=93,source='evolution'));self.assertEqual(r.tracker.index,1)
        c.update(frame=128,callback='CB2_RunPokemonSummaryScreen',summary=dict(stage=2,mode=2,party=True,uid='t',slot=3,moves=[33,81,106,45,93],return_callback='CB2_EvolutionSceneLoadGraphics',cursor=3))
        self.poll(r,m,c);self.assertEqual(r.mask,BUTTONS['A'])
        m['moves'][3]=dict(move(93,ROOT));c.update(frame=160,callback='CB2_EvolutionSceneUpdate',summary=None);e['learn_state']=7
        self.poll(r,m,c);self.assertEqual(r.tracker.index,2);self.assertIsNone(r.active)
    def test_keep_species_cancels_only_cancellable_animation(self):
        for bits in (0,1):
            m=mon(11,9,'t',[33,81,106]);m['slot']=3;p=compile_plan(m,10,[33,81,106],ROOT,'stay')
            r=LearningRuntime(p,event=lambda *a:None,checkpoint=lambda _:None,suspend=lambda:None);m['level']=10
            c=dict(frame=100,callback='CB2_EvolutionSceneUpdate',evo=dict(slot=3,pre=11,post=12,state=8,bits=bits),summary=None,battle=None,cursor=0,move_id=0,stable=False)
            if bits:self.poll(r,m,c);self.assertEqual(r.mask,BUTTONS['B'])
            else:
                with self.assertRaises(PlanMismatch):self.poll(r,m,c)
                self.assertEqual(r.mask,0)
    def test_cancellation_removes_all_learning_input(self):
        m,r,c,_,_=self.setup_runtime();self.poll(r,m,c,dict(party_slot=3,move_id=77,source='battle'));r.mask=BUTTONS['A'];r.cancel();self.assertEqual(r.mask,0);self.assertFalse(r.owns_input);self.assertIsNone(r.active)

if __name__=='__main__':unittest.main()
