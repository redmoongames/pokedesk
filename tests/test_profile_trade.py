"""Paired publication recovers crashes without exposing one-sided exchanges."""
from pathlib import Path
from unittest.mock import patch,Mock
import fcntl,json,sys,time,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from test_runtime_performance import PrivateSessionTestCase
from pokemon_red.profiles import Profiles
from pokemon_red.persistence import SaveSnapshot,publish_checkpoint
from pokemon_red.acquisition import write_json
from pokemon_red import profile_trade as trade

class ProfileTradeTests(PrivateSessionTestCase):
 def setUp(self):
  super().setUp();self.store=Profiles(self.root);self.rows=[self.store.create(),self.store.create()];self.ids=[r['id'] for r in self.rows];self.resolved=trade.rows_for(self.root,self.ids)
  for i,row in enumerate(self.resolved):
   for n in ('FireRed.state','FireRed.sav'):(row['folder']/'Data'/n).write_bytes(('before'+str(i)+n).encode())
  self.before=[trade.hashes(r['folder']) for r in self.resolved];self.key='a'*32;self.folder=trade.folder_for(self.root,self.key);self.folder.mkdir(parents=True)
  for i in range(2):trade.stage_snapshot(SaveSnapshot(('after'+str(i)).encode(),('sram'+str(i)).encode(),100+i,time.time(),b'{}'),self.folder/f'after-{i}')
  self.journal=dict(profiles=self.ids,games=['firered','firered'],before=self.before,commit_intent=True,status='committing');write_json(self.folder/'journal.json',self.journal)
 def test_failure_after_first_side_blocks_both_until_recovery(self):
  calls=[]
  def fail_second(*args,**kw):
   calls.append(1)
   if len(calls)==2:raise OSError('disk full')
   return publish_checkpoint(*args,**kw)
  with trade.locks(self.resolved),patch('pokemon_red.profile_trade.publish_checkpoint',side_effect=fail_second):
   with self.assertRaisesRegex(OSError,'disk full'):trade.commit(self.root,self.key,self.resolved,self.journal)
  self.assertNotEqual(trade.hashes(self.resolved[0]['folder']),self.before[0]);self.assertEqual(trade.hashes(self.resolved[1]['folder']),self.before[1])
  self.assertTrue(all(self.store.busy(r) for r in self.rows));trade.recover(self.root,self.key)
  self.assertFalse(trade.pending(self.root));self.assertTrue(all(not self.store.busy(r) for r in self.rows))
  for i,row in enumerate(self.resolved):self.assertEqual((row['folder']/'Data/FireRed.state').read_bytes(),('after'+str(i)).encode())
  self.assertIsNone(trade.recover(self.root,self.key))
 def test_torn_sram_publication_is_recoverable(self):
  (self.resolved[0]['folder']/'Data/FireRed.sav').write_bytes(b'sram0');trade.recover(self.root,self.key)
  self.assertEqual((self.resolved[0]['folder']/'Data/FireRed.state').read_bytes(),b'after0')
 def test_unrelated_new_progress_is_never_overwritten(self):
  source=self.resolved[0]['folder'];(source/'Data/FireRed.state').write_bytes(b'new unrelated progress')
  with self.assertRaisesRegex(RuntimeError,'изменилось вне обмена'):trade.recover(self.root,self.key)
  self.assertEqual((source/'Data/FireRed.state').read_bytes(),b'new unrelated progress');self.assertEqual(trade.hashes(self.resolved[1]['folder']),self.before[1])
 def test_corrupt_prepared_result_is_rejected_before_any_publication(self):
  (self.folder/'after-1/FireRed.state').write_bytes(b'broken')
  with self.assertRaisesRegex(RuntimeError,'Повреждена'):trade.recover(self.root,self.key)
  self.assertEqual([trade.hashes(r['folder']) for r in self.resolved],self.before)
 def test_open_profile_is_rejected_before_constructing_any_core(self):
  with (self.resolved[0]['folder']/'Data/.session.lock').open('a') as lock:
   fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
   with patch('pokemon_red.engine.Game',side_effect=AssertionError('Live profile must not be read')):
    with self.assertRaisesRegex(RuntimeError,'открыто'):trade.inspect(self.root,self.ids)
 def test_running_exchange_dialog_cannot_be_opened_twice(self):
  from pokemon_red.startup import StartupHome
  from types import SimpleNamespace
  dialog=SimpleNamespace(closed=False,window=Mock());home=SimpleNamespace(trade_dialog=dialog,trade_busy=True)
  with patch('pokemon_red.profile_trade_ui.ProfileTradeDialog') as create:StartupHome.exchange(home)
  create.assert_not_called();dialog.window.lift.assert_called_once()
 def test_same_profile_cannot_trade_with_itself(self):
  with self.assertRaises(ValueError):trade.rows_for(self.root,[self.ids[0],self.ids[0]])

if __name__=='__main__':unittest.main()
