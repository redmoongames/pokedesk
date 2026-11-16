"""Paused alternatives are bounded and independent of the manual timeline."""
import sys,time,json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.catch_lifecycle import observe,expired,close_receipt,persist_context
from pokemon_red.operations import MainOperation
from pokemon_red.wild_search_history import saved_searches,candidate_request,resume_snapshot
import test_saved_encounters as fixtures
fixture=fixtures.fixture;ID=fixtures.ID

class MovementLifetime(unittest.TestCase):
 def state(self,x=0,y=0,name='Route1',**kw):return dict(position=dict(x=x,y=y),map=dict(name=name),**kw)
 def context(self):return dict(id=ID,state='paused',paused_at=1000,manual_steps=0)
 def test_stationary_dialogs_and_frames_do_not_expire_search(self):
  c=self.context();p=None
  for _ in range(200):p,done=observe(c,self.state(),p,generation=1,now=1100)
  self.assertEqual(c['manual_steps'],0);self.assertFalse(done)
 def test_distance_closes_at_one_hundred(self):
  c=self.context();p,_=observe(c,self.state(),None,generation=1,now=1100)
  p,done=observe(c,self.state(99),p,generation=1,now=1100);self.assertFalse(done)
  p,done=observe(c,self.state(100),p,generation=1,now=1100);self.assertTrue(done)
 def test_generation_and_map_changes_are_not_large_teleports(self):
  c=self.context();p,_=observe(c,self.state(),None,generation=1,now=1100)
  p,_=observe(c,self.state(300,300),p,generation=2,now=1100);self.assertEqual(c['manual_steps'],0)
  p,_=observe(c,self.state(1,1,'City'),p,generation=2,now=1100);self.assertEqual(c['manual_steps'],1)
 def test_battle_coordinates_do_not_count(self):
  c=self.context();p,_=observe(c,self.state(),None,generation=1,now=1100)
  p,done=observe(c,self.state(999,in_battle=True),p,generation=1,now=1100)
  self.assertIsNone(p);self.assertFalse(done);self.assertEqual(c['manual_steps'],0)
 def test_expiry_uses_real_time(self):
  c=self.context();self.assertFalse(expired(c,1000+86399));self.assertTrue(expired(c,1000+86400))

class Retirement(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);(self.root/'vendor').symlink_to(ROOT/'vendor');self.folder,self.rows=fixture(self.root)
 def tearDown(self):self.tmp.cleanup()
 def test_closed_candidates_rejected_without_changing_live_save(self):
  (self.root/'Data').mkdir();live=self.root/'Data/FireRed.state';live.write_bytes(b'manual-progress')
  close_receipt(self.root,ID,'dismissed');self.assertEqual(saved_searches(self.root),[])
  with self.assertRaises(ValueError):candidate_request(self.root,dict(operation_id=ID,sha256=self.rows[0]['sha256']))
  self.assertEqual(live.read_bytes(),b'manual-progress');self.assertTrue((self.folder/'main/Data/wild-candidates.json').exists())
 def test_caught_search_not_offered_even_without_receipt(self):
  (self.folder/'status.json').write_text(json.dumps(dict(status='ready')));(self.folder/'result.json').write_text(json.dumps(dict(pokemon={'uid':'caught'})))
  self.assertEqual(saved_searches(self.root),[])
 def test_backend_enforces_manual_step_limit(self):
  persist_context(self.root,dict(id=ID,state='paused',manual_steps=100,paused_at=time.time()))
  with self.assertRaises(ValueError):candidate_request(self.root,dict(operation_id=ID,sha256=self.rows[0]['sha256']))
 def test_resume_uses_safe_frontier_not_attention_state(self):
  folder=self.folder/'main/search-frontier';folder.mkdir();(folder/'FireRed.state').write_bytes(b'safe-grass');(folder/'FireRed.sav').write_bytes(b'sram')
  (self.folder/'main/Data/FireRed.state').write_bytes(b'attention-battle')
  row,snapshot=resume_snapshot(self.root,ID);self.assertEqual(snapshot.state,b'safe-grass');self.assertEqual(len(row['candidates']),3)
 def test_legacy_lane_zero_frontier_can_resume(self):
  folder=self.folder/'main/search-workers/pool/0/Data';folder.mkdir(parents=True);(folder/'FireRed.state').write_bytes(b'legacy-grass');(folder/'FireRed.sav').write_bytes(b'sram')
  self.assertEqual(resume_snapshot(self.root,ID)[1].state,b'legacy-grass')
 def test_missing_frontier_never_falls_back_to_manual_save(self):
  with self.assertRaises(ValueError):resume_snapshot(self.root,ID)
 def owner(self):
  m=NS(folder=self.root,game=NS(state_generation=1),automation=NS(running=False),update_panel=Mock(),notice='')
  m.submit_write=Mock(side_effect=lambda fn,**_:fn());return m,MainOperation(m)
 def test_expired_context_frees_result_candidates(self):
  m,op=self.owner();op.catch_context=dict(id=ID,state='paused',manual_steps=99,paused_at=time.time());op.context_position=(1,'Route1',0,0);op.result=dict(operation_id=ID,search={'candidates':self.rows})
  op.observe_catch_context(dict(position=dict(x=1,y=0),map=dict(name='Route1')))
  self.assertFalse(op.catch_context);self.assertEqual(op.result['search'],{});self.assertEqual(saved_searches(self.root),[])
 def test_active_finish_cancels_before_retirement(self):
  m,op=self.owner();op.job=self.folder;op.kind='local';op.prepare_future=NS();op.command('finish_search')
  self.assertTrue(op.finish_search_requested);self.assertTrue(op.cancel_preparation);self.assertFalse((self.folder/'lifecycle.json').exists())
 def test_failed_capture_keeps_source_open(self):
  m,op=self.owner();op.job=self.folder;op.kind='local';op.spec_config=dict(schema_version=2,_saved_candidate=dict(operation_id=ID));op.result=dict(status='attention',applied=False);op.catch_context=dict(id=ID,state='paused')
  op.retain_catch_context();self.assertEqual(op.catch_context['id'],ID);self.assertEqual(len(saved_searches(self.root)),1)
 def test_late_ui_request_cannot_restore_retired_search_before_writer_finishes(self):
  from concurrent.futures import Future
  m,op=self.owner();m.submit_write=Mock(return_value=Future());m.session_transition=False;m.closing=False;m.pending_start=None;m.critical_save_pending=lambda:False
  op._close_search(ID,'dismissed');self.assertFalse((self.folder/'lifecycle.json').exists())
  with self.assertRaises(ValueError):op.begin('local',dict(schema_version=2,_saved_candidate=dict(operation_id=ID,sha256=self.rows[0]['sha256'])))


class ShinySampling(unittest.TestCase):
 def test_unwanted_shiny_is_skipped_and_next_matching_encounter_is_caught(self):
  from unittest.mock import patch
  from pokemon_red.grass_search import sample_grass
  from pokemon_red.models import STAT_KEYS
  shiny=dict(uid='shiny',checksum_valid=True,species_id=21,shiny=True,is_egg=False,personality=42,level=5,ivs=dict.fromkeys(STAT_KEYS,31))
  ordinary=dict(shiny,uid='ordinary',shiny=False)
  g=Mock(root=ROOT,frame=100);g.capture_save.return_value=NS(state=b'frontier');g.read_bytes.return_value=b'old'
  w=Mock();w.request={'lane':0};p=NS(g=g,w=w,advance=Mock())
  walk=dict(map='Route1',position=[3,4],open=True,moving=False)
  segment=NS(path=[(4,4)],next=lambda _:(0,None))
  with patch('pokemon_red.grass_search.read_walk_state',return_value=walk),patch('pokemon_red.grass_search.symbols',return_value={'gEnemyParty':1}),patch('pokemon_red.grass_search.WalkSegment',return_value=segment),patch('pokemon_red.grass_search.generated_enemy',side_effect=[shiny,ordinary]),patch('pokemon_red.grass_search.settle_encounter') as settle,patch('pokemon_red.autocatch.run_autocatch',return_value=ordinary):
   result=sample_grass(p,dict(species_id=21,gender='any',min_ivs=dict.fromkeys(STAT_KEYS,0)),dict(selected={'map':'Route1'},grass_frontier=dict(pair=[[3,4],[4,4]],movement='walk')))
  self.assertEqual(result['uid'],'ordinary');g.restore_checkpoint.assert_called_once_with(b'frontier');settle.assert_called_once_with(p,'ordinary')

class ResumeUI(unittest.TestCase):
 setUp=fixtures.SavedEncounterViewTests.setUp
 tearDown=fixtures.SavedEncounterViewTests.tearDown
 open=fixtures.SavedEncounterViewTests.open
 def test_resume_requires_review(self):
  self.open();self.view.ask_resume();self.operation.begin.assert_not_called();self.assertIn('F8',self.view.confirm_text._source_text)
  self.view.confirm();self.operation.begin.assert_called_once_with('local',dict(schema_version=2,_resume_search=ID))
 def test_scan_cannot_resurrect_closed_record(self):
  self.open();self.view.ask();self.view.rows=[];self.view.render();self.assertIsNone(self.view.record);self.assertIsNone(self.view.confirmation);self.assertEqual(self.view.candidates.rows,[])
 def test_finish_sends_owner_command(self):
  self.open();self.view.finish_search();self.operation.command.assert_called_once_with('finish_search:'+ID)

class PausedContextUI(unittest.TestCase):
 def test_manual_battle_does_not_disable_saved_candidate_or_resume(self):
  import tkinter as tk,gc
  gc.collect()
  from unittest.mock import patch
  from pokemon_red.catch_view import CatchSetup
  window=tk.Tk();view=None
  op=NS(active=False,kind=None,result=None,command=Mock(),data=dict(catch_context=dict(id=ID,state='paused',config={'species_id':19},search={})))
  m=NS(folder=ROOT,generation=1,last_state=dict(ready=True,in_battle=True),operation=op,automation=NS(running=False),status={},runtime=NS(submit=Mock()),watch=Mock(),battle_panel=NS(open_saved_encounters=Mock()))
  panel=NS(monitor=m,window=window,content=window)
  try:
   with patch('pokemon_red.catch_view.HuntService') as service:
    service.return_value.poll.return_value=None;view=CatchSetup(panel,19,parent=window);view.update_actions()
    self.assertEqual(view.start.cget('state'),'normal');view.run();m.battle_panel.open_saved_encounters.assert_called_once_with(panel,ID,None)
    op.data['catch_context']={};view.update_actions();self.assertEqual(view.candidate_view.rows,[]);self.assertFalse(view.finish_button.winfo_manager())
  finally:
   if view:view.close()
   window.destroy();gc.collect()

class VerifiedCatchRecovery(unittest.TestCase):
 def test_takeover_after_verified_catch_keeps_the_finished_result(self):
  from unittest.mock import patch
  from pokemon_red.operation_worker import Worker
  worker=object.__new__(Worker);worker.game=Mock();mon=dict(uid='caught',species_id=19,personality=7,ivs={'hp':31},level=5,shiny=False,checksum_valid=True)
  worker.verified_catch=dict(mon)
  with patch('pokemon_red.operation_worker.read_inventory',return_value=dict(party=[mon],boxes=[])):
   self.assertEqual(worker.recovered_catch(),mon)
  with patch('pokemon_red.operation_worker.read_inventory',return_value=dict(party=[dict(mon,personality=8)],boxes=[])):
   self.assertIsNone(worker.recovered_catch())
 def test_unverified_late_winner_is_never_imported_as_recovered_catch(self):
  from unittest.mock import patch
  from pokemon_red.operation_worker import Worker
  worker=object.__new__(Worker)
  with patch('pokemon_red.operation_worker.read_inventory') as reader:
   self.assertIsNone(worker.recovered_catch());reader.assert_not_called()
