"""Regression for backup rotation and verified shutdown, using private saves only."""
from pathlib import Path
import sys,tempfile,unittest,json,types,time,threading,traceback
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from pokemon_red.persistence import SaveSnapshot,publish_checkpoint
from pokemon_red.save_timeline import SaveTimeline
from test_save_system import snapshot
from test_runtime_performance import PrivateSessionTestCase
from test_engine_runtime import ProbeRuntime

class CommitTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.data=Path(self.temp.name)/'Data'
  publish_checkpoint(snapshot(0),self.data,'rom')
 def tearDown(self):self.temp.cleanup()
 def test_retention_past_ten_backups_never_replaces_commit_metadata(self):
  for n in range(1,25):publish_checkpoint(snapshot(n),self.data,'rom',backup=True)
  snapshot(24).verify(self.data);info=SaveTimeline(self.data).current();self.assertEqual(info['frame'],24);self.assertEqual(info['history_time'],120)
  self.assertEqual(len(list((self.data/'backups/sessions').glob('*.state'))),10)
 def test_publisher_accepts_snapshots_from_an_earlier_loaded_sdk(self):
  from types import SimpleNamespace
  snap=snapshot(1);legacy=SimpleNamespace(**snap.__dict__,publish=snap.publish)
  publish_checkpoint(legacy,self.data,'rom',backup=True);snap.verify(self.data)
 def test_broken_history_cannot_block_current_progress(self):
  for stage in ('archive','describe','prune'):
   with self.subTest(stage=stage),patch.object(SaveTimeline,stage,side_effect=AttributeError("'PosixPath' object has no attribute 'get'")),self.assertLogs('pokemon_red.save_timeline',level='WARNING'):
    warnings=[];n=1+('archive','describe','prune').index(stage);publish_checkpoint(snapshot(n),self.data,'rom',backup=True,on_warning=warnings.append)
    snapshot(n).verify(self.data);self.assertTrue(warnings)
 def test_failed_backup_cleanup_cannot_undo_verified_commit(self):
  with patch('pokemon_red.save_timeline.rotate_session_backups',side_effect=PermissionError('retention locked')),self.assertLogs('pokemon_red.save_timeline',level='WARNING'):
   publish_checkpoint(snapshot(1),self.data,'rom',backup=True)
  snapshot(1).verify(self.data);self.assertEqual(SaveTimeline(self.data).current()['frame'],1)
 def test_disk_full_never_reports_new_commit_or_rotates_old_metadata(self):
  with patch.object(SaveSnapshot,'publish',side_effect=OSError('disk full')):
   with self.assertRaisesRegex(OSError,'disk full'):publish_checkpoint(snapshot(1),self.data,'rom',backup=True)
  snapshot(0).verify(self.data);self.assertEqual(SaveTimeline(self.data).current()['frame'],0)
 def test_partial_or_missing_cartridge_export_is_repaired_on_unchanged_save(self):
  for broken in (b'partial',None):
   p=self.data/'FireRed.sav'
   if broken is None:p.unlink()
   else:p.write_bytes(broken)
   publish_checkpoint(snapshot(0),self.data,'rom');snapshot(0).verify(self.data)
 def test_successful_return_without_publishing_is_detected(self):
  with patch.object(SaveSnapshot,'publish',return_value=self.data/'FireRed.state'):
   with self.assertRaisesRegex(OSError,'Не подтверждена запись'):publish_checkpoint(snapshot(1),self.data,'rom')

class ShutdownTests(PrivateSessionTestCase):
 def setUp(self):
  super().setUp();self.runtime=ProbeRuntime(self.root,paused=True);self.runtime.ready.result(5)
 def probe(self,fn):return self.runtime.submit('probe',fn).result(5)
 def wait(self,predicate,timeout=5):
  end=time.monotonic()+timeout
  while not predicate() and time.monotonic()<end:time.sleep(.005)
  self.assertTrue(predicate())
 def tearDown(self):
  if not self.runtime.finished.done():self.runtime.take_control(pause=True,close=True)
  self.runtime.finished.result(8);self.runtime.thread.join(1);super().tearDown()
 def fail_close(self,side_effect=None,return_value=None):
  captured=self.probe(lambda c:(c.game.advance(12),c.game.frame)[1])
  with patch('pokemon_red.session_controller.publish_checkpoint',side_effect=side_effect,return_value=return_value):
   self.runtime.take_control(pause=True,close=True);self.wait(lambda:self.runtime.latest.status['save_failed'])
   self.assertFalse(self.runtime.finished.done());self.assertFalse(self.runtime.latest.status['closed']);self.assertFalse(self.runtime.latest.status['closing']);self.assertTrue(self.runtime.latest.status['paused'])
   self.assertEqual(self.probe(lambda c:c.game.frame),captured)
  self.runtime.take_control(pause=True,close=True);self.runtime.finished.result(8)
  from pokemon_red.engine import Game
  with Game(self.root) as restored:self.assertEqual(restored.frame,captured)
 def test_failed_close_keeps_exact_live_progress_and_can_retry(self):self.fail_close(side_effect=OSError('disk full'))
 def test_stale_path_return_is_not_permission_to_destroy_live_core(self):self.fail_close(return_value=self.root/'Data/FireRed.state')
 def test_close_commits_latest_frame_after_queued_older_save_and_rotation(self):
  gate=threading.Event();entered=threading.Event()
  def queue(c):
   c.writer.submit(lambda:(entered.set(),gate.wait(3)))
   c.game.advance(5);c.save(manual=True);c.game.advance(10);return c.game.frame
  frame=self.probe(queue);self.assertTrue(entered.wait(1))
  for n in range(12):
   p=self.root/'Data/backups/sessions'/f'old-{n}.state';p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'old')
  self.runtime.take_control(pause=True,close=True);self.assertFalse(self.runtime.finished.done());gate.set();self.runtime.finished.result(8)
  from pokemon_red.engine import Game
  with Game(self.root) as restored:self.assertEqual(restored.frame,frame)
  self.assertEqual(SaveTimeline(self.root/'Data').current()['frame'],frame)

if __name__=='__main__':unittest.main()

class CloseDialogTests(PrivateSessionTestCase):
 def setUp(self):
  super().setUp()
  import tkinter as tk
  from pokemon_red.gui import Monitor
  self.window=tk.Tk();self.window.withdraw();self.errors=[]
  self.monitor=Monitor(self.window,self.root,paused=True,runtime_factory=ProbeRuntime);self.monitor.show_battle_panel=lambda:None
  self.window.report_callback_exception=lambda kind,error,tb:self.errors.append(error)
  self.drive(lambda:self.monitor.ready)
 def drive(self,predicate,timeout=5):
  end=time.monotonic()+timeout
  while not predicate() and time.monotonic()<end:self.window.update();time.sleep(.002)
  self.assertTrue(predicate(),self.errors);self.assertEqual(self.errors,[])
 def tearDown(self):
  if not self.monitor.closed:self.monitor.close();self.drive(lambda:self.monitor.closed,8)
  super().tearDown()
 def test_cancel_after_failed_close_keeps_window_and_core_alive(self):
  m=self.monitor
  with patch('pokemon_red.session_controller.publish_checkpoint',side_effect=OSError('disk full')),patch('pokemon_red.gui.messagebox.askretrycancel',return_value=False) as dialog,patch('pokemon_red.gui.messagebox.askyesno',side_effect=AssertionError('No discard prompt')):
   m.close();self.drive(lambda:dialog.called and not m.close_requested)
   self.assertFalse(m.closed);self.assertTrue(self.window.winfo_exists());self.assertTrue(m.paused)
   self.assertFalse(m.runtime.finished.done());self.assertIn('останется открытой',dialog.call_args.args[1])
 def test_retry_commits_and_reopens_exact_latest_native_frame(self):
  from pokemon_red.persistence import publish_checkpoint as real
  from pokemon_red.engine import Game
  m=self.monitor;attempts=[]
  frame=m.runtime.submit('probe',lambda c:(c.game.advance(17),c.game.frame)[1]).result(5)
  def publish(*args,**kwargs):
   attempts.append(True)
   if len(attempts)==1:raise OSError('temporary disk error')
   return real(*args,**kwargs)
  with patch('pokemon_red.session_controller.publish_checkpoint',side_effect=publish),patch('pokemon_red.gui.messagebox.askretrycancel',return_value=True) as dialog:
   m.close();self.drive(lambda:m.closed,8);dialog.assert_called_once()
  with Game(self.root) as restored:self.assertEqual(restored.frame,frame)
