"""Encounter recovery must be explicit, durable, scoped and independent of views."""
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock,patch
import hashlib,json,sys,tempfile,time,unittest,shutil
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.wild_search_history import saved_searches,candidate_request
from pokemon_red.search_candidates import CandidateStore
from pokemon_red.capture_target import CaptureTarget
from pokemon_red.i18n import set_locale
from pokemon_red.models import STAT_KEYS

ID='1'*32

def fixture(root,identifier=ID):
 folder=root/'Sessions/operations'/identifier;(folder/'main/Data').mkdir(parents=True)
 cfg=dict(schema_version=2,species_id=19,gender='any',min_ivs=dict.fromkeys(STAT_KEYS,20),search_workers=1)
 (folder/'operation.json').write_text(json.dumps(dict(kind='local',config=cfg,created_at=1)))
 (folder/'status.json').write_text(json.dumps(dict(status='paused',search=dict(attempts=5380))))
 store=CandidateStore(folder/'main','wild');history=[]
 for i in range(3):
  mon=dict(uid='pokemon-'+str(i),species_id=19,personality=i,nature=i,ivs=dict.fromkeys(STAT_KEYS,19-i),shiny=False,checksum_valid=True,level=3)
  rated=CaptureTarget.parse(cfg,root).assess(mon,root);data=('checkpoint-'+str(i)).encode();rated['sha256']=hashlib.sha256(data).hexdigest();history=store.record(history,rated,data,top_k=True)
 return folder,history

class SavedEncounterDataTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);(self.root/'vendor').symlink_to(ROOT/'vendor');self.folder,self.rows=fixture(self.root)
 def tearDown(self):self.tmp.cleanup()
 def test_stopped_search_survives_new_search_and_new_reader(self):
  before=CandidateStore(self.folder/'main','wild').checkpoint(self.rows[1]['sha256']);fixture(self.root,'2'*32)
  for _ in range(2):
   rows=saved_searches(self.root);self.assertEqual(len(rows),2);self.assertEqual(len(next(r for r in rows if r['id']==ID)['candidates']),3)
  self.assertEqual(CandidateStore(self.folder/'main','wild').checkpoint(self.rows[1]['sha256']),before)
 def test_restoring_selected_encounter_keeps_its_exact_identity(self):
  row,candidate=candidate_request(self.root,dict(operation_id=ID,sha256=self.rows[1]['sha256']));self.assertEqual(candidate['pokemon']['uid'],'pokemon-1');self.assertTrue(candidate['missing']);self.assertEqual(row['config']['species_id'],19)
 def test_bad_ids_missing_files_and_corrupt_checkpoints_are_rejected(self):
  for identifier in ('../outside','x'*32):
   with self.assertRaises(ValueError):candidate_request(self.root,dict(operation_id=identifier,sha256=self.rows[0]['sha256']))
  path=CandidateStore(self.folder/'main','wild').folder/(self.rows[1]['sha256']+'.state');path.write_bytes(b'corrupt')
  with self.assertRaises(ValueError):candidate_request(self.root,dict(operation_id=ID,sha256=self.rows[1]['sha256']))
 def test_interrupted_app_does_not_make_saved_encounters_unrecoverable(self):
  (self.folder/'status.json').write_text(json.dumps(dict(status='running')))
  self.assertEqual(candidate_request(self.root,dict(operation_id=ID,sha256=self.rows[0]['sha256']))[1]['pokemon']['uid'],'pokemon-0')

class SavedEncounterViewTests(unittest.TestCase):
 def setUp(self):
  SavedEncounterDataTests.setUp(self);from pokemon_red import localized_tk as tk
  self.tk=tk;self.window=tk.Tk();self.window.geometry('350x800');set_locale('en')
  self.operation=NS(active=False,job=None,result=None,begin=Mock(),command=Mock());self.m=NS(folder=self.root,status={'saving':False},notice='',operation=self.operation,automation=NS(running=False));self.panel=NS(monitor=self.m);self.view=None
 def tearDown(self):
  if self.view:
   self.view.close();self.view.pool.shutdown(wait=True,cancel_futures=True)
  self.window.destroy();SavedEncounterDataTests.tearDown(self);set_locale('en')
  # TestCase instances outlive tearDown. Release their destroyed Tk object
  # graphs here so a subsequent native-owner allocation cannot collect them.
  self.view=self.window=self.panel=self.m=self.operation=None
  import gc
  gc.collect()
 def open(self):
  from pokemon_red.wild_history_ui import SavedEncountersView
  self.view=SavedEncountersView(self.panel,self.window,operation_id=ID);end=time.monotonic()+3
  while not self.view.record and time.monotonic()<end:self.window.update();time.sleep(.005)
  self.assertIsNotNone(self.view.record)
 def test_back_and_reopening_keep_three_candidates(self):
  self.open();self.assertEqual(len(self.view.candidates.rows),3);self.view.close();self.open();self.assertEqual(len(self.view.candidates.rows),3)
 def test_selection_requires_explicit_rollback_review_and_preserves_chosen_hash(self):
  self.open();sha=self.rows[1]['sha256'];self.view.candidates.choose(sha);self.view.ask();self.operation.begin.assert_not_called();self.assertEqual(self.view.confirmation,dict(operation_id=ID,sha256=sha));self.assertIn('F8',self.view.confirm_text._source_text)
  self.view.confirm();self.operation.begin.assert_called_once_with('local',dict(schema_version=2,_saved_candidate=dict(operation_id=ID,sha256=sha)))
 def test_changing_selection_dismisses_previous_confirmation(self):
  self.open();self.view.ask();self.assertIsNotNone(self.view.confirmation);self.view.candidates.choose(self.rows[1]['sha256']);self.assertIsNone(self.view.confirmation);self.view.confirm();self.operation.begin.assert_not_called()
 def test_active_search_cannot_capture_an_encounter_before_stopping(self):
  self.operation.active=True;self.operation.kind='local';self.open();self.view.ask();self.view.confirm();self.operation.begin.assert_not_called();self.view.stop_search();self.operation.command.assert_called_once_with('pause')
 def test_an_evicted_explicit_choice_never_silently_selects_another_pokemon(self):
  self.open();view=self.view.candidates;sha=self.rows[1]['sha256'];view.choose(sha);self.assertEqual(view.selected,sha);view.update([self.rows[0],self.rows[2]],True);self.assertIsNone(view.selected)

 def test_save_barrier_blocks_both_review_and_confirm(self):
  self.open();self.m.status['saving']=True;self.view.ask();self.assertIsNone(self.view.confirmation)
  self.m.status['saving']=False;self.view.ask();self.m.status['saving']=True;self.view.confirm();self.operation.begin.assert_not_called()
 def test_review_keeps_actions_visible_at_minimum_window_size(self):
  self.window.geometry('300x600');set_locale('ru');self.open();self.view.ask();self.window.update()
  self.assertFalse(self.view.browser.winfo_ismapped());self.assertTrue(self.view.confirm_box.winfo_ismapped())
  self.assertLessEqual(int(self.view.confirm_text.cget('wraplength')),self.view.confirm_box.winfo_width()-28)
  self.assertTrue(self.view.confirm_button.winfo_ismapped());self.assertLess(self.view.confirm_button.winfo_rooty()+self.view.confirm_button.winfo_height(),self.window.winfo_rooty()+600)
  self.view.dismiss();self.window.update();self.assertTrue(self.view.browser.winfo_ismapped());self.assertFalse(self.view.confirm_box.winfo_ismapped());self.assertEqual(len(self.view.candidates.rows),3)

 def test_busy_status_does_not_report_a_previous_catch_as_finished(self):
  self.open();self.operation.result=dict(config={'_saved_candidate':{}},status='ready',applied=True);self.operation.result['config']['_saved_candidate']={'operation_id':ID};self.operation.active=True;self.operation.kind='local';self.m.notice='Catching the chosen encounter';self.view.render();self.assertIn('Catching',self.view.status._source_text)
 def test_failed_capture_displays_the_reason_without_claiming_timeline_was_kept(self):
  self.open();self.operation.result=dict(config={'_saved_candidate':{'operation_id':ID}},status='attention',stage='Disk full',applied=False);self.view.render();self.assertIn('Disk full',self.view.status._source_text);self.assertNotIn('timeline was kept',self.view.status._source_text)

class SavedEncounterBackupTests(unittest.TestCase):
 setUp=SavedEncounterDataTests.setUp
 tearDown=SavedEncounterDataTests.tearDown
 def test_failed_durable_backup_never_starts_worker_or_restores_old_timeline(self):
  from concurrent.futures import Future
  from pokemon_red.operations import MainOperation
  (self.root/'Data').mkdir();game=Mock(frame=123);game.capture_save.return_value=NS(frame=123)
  backup=Mock();backup.publish.side_effect=OSError('Disk full')
  m=NS(folder=self.root,session_transition=False,closing=False,pending_start=False,critical_save_pending=lambda:False,settings={'language':'en'},automation=Mock(),pause=Mock(),keys=set(),game=game,slots=NS(capture=Mock(return_value=backup)),update_panel=Mock(),close_after_operation=False)
  def submit(work,**_):
   future=Future()
   try:future.set_result(work())
   except Exception as error:future.set_exception(error)
   return future
  m.submit_write=submit;op=MainOperation(m);op.launch=Mock()
  op.begin('local',dict(schema_version=2,_saved_candidate=dict(operation_id=ID,sha256=self.rows[1]['sha256'])))
  with self.assertRaises(OSError):op.prepare_future.result(2)
  op.poll();op.launch.assert_not_called();game.load_state.assert_not_called();self.assertFalse(op.active);self.assertFalse(op.result['applied']);self.assertIn('Disk full',op.result['stage'])

if __name__=='__main__':unittest.main()
