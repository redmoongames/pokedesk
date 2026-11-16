"""Priority utility, nature constraints, real-time budgets and safe auto-selection."""
import sys,json,hashlib,tempfile,time,os,unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock,patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.models import STAT_KEYS
from pokemon_red.catch_preferences import normalize_preferences,accepted_natures,score
from pokemon_red.capture_target import CaptureTarget
from pokemon_red.search_budget import SearchBudget,SearchDeadline
from pokemon_red.acquisition_play import AcquisitionAttention,JobPaused
from pokemon_red.search_candidates import CandidateStore

def preferences(**kw):return dict.fromkeys(STAT_KEYS,'neutral')|kw
def mon(n=20,**kw):return dict(uid='opponent',species_id=19,personality=2,nature=2,level=5,checksum_valid=True,is_egg=False,shiny=False,ivs=dict.fromkeys(STAT_KEYS,n))|kw

class PriorityModel(unittest.TestCase):
 def test_weights_are_two_one_and_half_and_weak_stats_still_contribute(self):
  r=preferences(speed='positive',hp='neutral',attack='negative');a=dict.fromkeys(STAT_KEYS,25);b=dict(a)
  a['hp']=26;b['speed']=26
  self.assertGreater(score(b,r,(0,)*6)['score'],score(a,r,(0,)*6)['score'])
  a['attack']+=1;self.assertEqual(score(a,r,(0,)*6)['score']-score(dict(a,attack=25),r,(0,)*6)['score'],.5)
 def test_quality_does_not_cap_at_the_requested_minimum(self):
  r=preferences();self.assertGreater(score(mon(30)['ivs'],r,(10,)*6,exact=True)['score'],score(mon(20)['ivs'],r,(10,)*6,exact=True)['score'])
  self.assertEqual(score(mon(30)['ivs'],r,(10,)*6,exact=True)['target_score'],186)
 def test_hard_minimum_eligibility_outranks_partial_high_total(self):
  low=mon(10)['ivs'];high=mon(31)['ivs'];high['hp']=9
  self.assertGreater(score(low,preferences(),(10,)*6,exact=True)['rank'],score(high,preferences(),(10,)*6,exact=True)['rank'])
 def test_nature_boosts_attack_drops_speed_and_never_changes_hp(self):
  self.assertEqual(accepted_natures(preferences(hp='positive',attack='positive',speed='negative')),(2,))
  self.assertEqual(accepted_natures(preferences(hp='positive')),tuple(range(25)))
  self.assertEqual(accepted_natures(preferences(attack='positive')),(1,2,3,4))
 def test_all_protected_or_all_dumped_stats_use_neutral_natures(self):
  self.assertEqual(accepted_natures(dict.fromkeys(STAT_KEYS,'positive')),(0,6,12,18,24))
  self.assertEqual(accepted_natures(dict.fromkeys(STAT_KEYS,'negative')),(0,6,12,18,24))
 def test_malformed_preferences_and_iv_values_are_rejected(self):
  for value in ({},['neutral']*5,dict(preferences(),speed='other')):
   with self.assertRaises(ValueError):normalize_preferences(value)
  self.assertIsNone(score(dict(mon()['ivs'],hp=True),preferences(),(0,)*6))
 def test_defaults_remain_legacy_for_old_jobs_and_new_jobs_use_full_iv_quality(self):
  old=CaptureTarget.parse(dict(species_id=19,gender='any'),ROOT);self.assertEqual(old.assess(mon(),ROOT)['score'],60);self.assertTrue(old.should_capture(mon(),ROOT))
  new=CaptureTarget.parse(dict(species_id=19,gender='any',stat_preferences=preferences(),search_seconds=60),ROOT)
  self.assertEqual(new.assess(mon(),ROOT)['score'],120);self.assertFalse(new.should_capture(mon(),ROOT));self.assertTrue(new.should_capture(mon(31),ROOT))
  self.assertEqual(CaptureTarget.parse(new.as_dict(),ROOT),new)
 def test_minima_are_optional_and_odds_follow_the_toggle(self):
  from pokemon_red.search_odds import wild_odds
  cfg=dict(species_id=19,gender='any',stat_preferences=preferences(),min_ivs=dict.fromkeys(STAT_KEYS,31))
  loose=CaptureTarget.parse(dict(cfg,exact_ivs=False),ROOT);strict=CaptureTarget.parse(dict(cfg,exact_ivs=True),ROOT)
  self.assertTrue(loose.matches(mon(),ROOT));self.assertFalse(strict.matches(mon(),ROOT));self.assertEqual(wild_odds(loose,ROOT)['iv'],1)
 def test_time_and_exact_flags_validate_before_a_worker_is_started(self):
  for val in (0,-1,True,1.5,float('inf'),86401):
   with self.assertRaises(ValueError):CaptureTarget.parse(dict(species_id=19,search_seconds=val),ROOT)
  with self.assertRaises(ValueError):CaptureTarget.parse(dict(species_id=19,exact_ivs=1),ROOT)

class BudgetTests(unittest.TestCase):
 def test_preparation_is_not_counted_and_deadline_is_real_not_emulated_time(self):
  now=[10.];b=SearchBudget(60,clock=lambda:now[0]);now[0]=1000;self.assertEqual(b.remaining(),60);self.assertFalse(b.expired())
  b.start();now[0]=1030;self.assertEqual(b.remaining(),30);now[0]=1060;self.assertTrue(b.expired())
 def test_pause_freezes_remaining_and_resume_keeps_it(self):
  now=[0.];b=SearchBudget(60,clock=lambda:now[0]);b.start();now[0]=10;b.freeze();now[0]=999;self.assertEqual(b.remaining(),50)
  c=SearchBudget(60,remaining=b.remaining(),clock=lambda:now[0]);c.start();self.assertEqual(c.deadline,1049)
  self.assertEqual(SearchBudget(60,remaining=0).remaining(),60)
 def test_legacy_unbounded_search_has_no_deadline(self):
  b=SearchBudget(None);b.start();b.freeze();self.assertIsNone(b.remaining());self.assertFalse(b.expired())
 def test_lane_stops_before_a_frame_or_candidate_after_shared_deadline(self):
  from pokemon_red.wild_search_worker import Lane
  from pokemon_red.acquisition import write_json
  with tempfile.TemporaryDirectory() as tmp:
   pool=Path(tmp);folder=pool/'0';folder.mkdir();write_json(folder/'request.json',dict(config={'search_seconds':10},lane=0,owner_pid=os.getppid()));write_json(pool/'deadline.json',dict(at=time.monotonic()-1))
   lane=Lane(folder)
   with self.assertRaises(SearchDeadline):lane.before_frame()
   with self.assertRaises(SearchDeadline):lane.candidate(Mock(),mon())
   self.assertEqual(lane.attempts,0)
   (pool/'stop').touch();lane.next_stop_check=0
   with self.assertRaises(JobPaused) as e:lane.before_frame()
   self.assertIs(type(e.exception),JobPaused)

class PoolBudgetTests(unittest.TestCase):
 def exercise(self,*,cancel=False,exact=False,perfect=False):
  from pokemon_red.wild_search import search
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/'vendor').symlink_to(ROOT/'vendor');(root/'Data').mkdir()
   cfg=dict(species_id=19,gender='any',stat_preferences=preferences(),search_seconds=10,search_workers=2,exact_ivs=exact,min_ivs=dict.fromkeys(STAT_KEYS,31 if exact else 0))
   target=CaptureTarget.parse(cfg,root);enemy=mon(31 if perfect else 20);children=[]
   g=NS(root=root,capture_save=Mock(return_value=NS(state=b'baseline',publish=Mock())),restore_checkpoint=Mock());w=NS(safe_point=Mock(),update=Mock(),event=Mock());p=NS(g=g,w=w,state=Mock())
   def clone(project,folder,snapshot,**_):(folder/'Data').mkdir(parents=True)
   def spawn(args,**_):
    folder=Path(args[-1]);n=int(folder.name);item=mon((31 if perfect else 20+n),uid='enemy-'+str(n));data=('candidate-'+str(n)).encode();rated=target.assess(item,root);rated['sha256']=hashlib.sha256(data).hexdigest();CandidateStore(folder,'wild').record([],rated,data,top_k=True)
    from pokemon_red.acquisition import write_json
    write_json(folder/'progress.json',dict(status='running' if perfect else 'budget_done',heartbeat=1,attempts=10,candidates=[rated]))
    children.append((item,data));return NS(poll=lambda:None if perfect else 0)
   def stop(rows):
    for _,_,log in rows:log.close()
    if cancel:w.safe_point.side_effect=JobPaused
   expected=mon(31 if perfect else 21,uid='enemy-0' if perfect else 'enemy-1')
   with patch('pokemon_red.telemetry.read_walk_state',return_value={'on_bike':False}),patch('pokemon_red.wild_search.prepare_hunt',return_value=dict(initial=['owned'],hunter='owned',selected={'method':'water_mons'})),patch('pokemon_red.wild_search.clone_session',side_effect=clone),patch('pokemon_red.wild_search.subprocess.Popen',side_effect=spawn),patch('pokemon_red.wild_search.stop_children',side_effect=stop),patch('pokemon_red.wild_search.read_roster_uids',return_value={'owned'}),patch('pokemon_red.wild_search.verified_enemy',return_value=expected),patch('pokemon_red.wild_search.run_autocatch',return_value=expected) as capture:
    if cancel:
     with self.assertRaises(JobPaused):search(p,cfg)
     g.restore_checkpoint.assert_not_called();capture.assert_not_called()
    elif exact and not perfect:
     with self.assertRaises(AcquisitionAttention):search(p,cfg)
     g.restore_checkpoint.assert_not_called();capture.assert_not_called()
    else:
     self.assertEqual(search(p,cfg)['uid'],expected['uid']);self.assertIsNone(capture.call_args.args[1]['search_seconds']);g.restore_checkpoint.assert_called_once_with(b'candidate-0' if perfect else b'candidate-1')
 def test_deadline_selects_highest_quality_in_pool(self):self.exercise()
 def test_no_eligible_candidate_never_relaxes_exact_minima(self):self.exercise(exact=True)
 def test_f9_during_deadline_teardown_prevents_any_import(self):self.exercise(cancel=True)
 def test_perfect_candidate_can_finish_before_limit(self):self.exercise(perfect=True)
