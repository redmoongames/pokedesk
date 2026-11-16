"""Browse before creating a session, then validate/backup/restore under a lock."""
from pathlib import Path
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock,patch
import fcntl,hashlib,json,sys,tempfile,time,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.engine import Game
from pokemon_red.slots import Slots
from pokemon_red.profile_restore import restore_profile
from pokemon_red.persistence import publish_checkpoint
from pokemon_red.save_timeline import SaveTimeline

class ClosedRestoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.folder=Path(self.temp.name);(self.folder/'Data').mkdir()
        for name in ('native','vendor'):(self.folder/name).symlink_to(ROOT/name,target_is_directory=True)
        (self.folder/'Data/FireRed.gba').symlink_to(ROOT/'Data/FireRed.gba');self.slots=Slots(self.folder)
        with Game(self.folder,resume=False) as game:
            game.advance(120);game.save();self.slot=self.slots.save(game,'Earlier');game.advance(30);game.save()
        self.before=(self.folder/'Data/FireRed.state').read_bytes()
    def tearDown(self):self.temp.cleanup()
    def test_restore_checks_candidate_preserves_exact_current_and_publishes_selected(self):
        result=restore_profile(self.folder,self.slots.get(self.slot))
        self.assertEqual((result['backup']/'FireRed.state').read_bytes(),self.before)
        self.assertEqual(result['frame'],121)
        with Game(self.folder) as game:self.assertEqual(game.frame,121)
        self.assertTrue(any(r['directory']==result['backup'] for r in self.slots.backups()))
    def test_invalid_candidate_leaves_current_and_action_history_unchanged(self):
        record=self.slots.get(self.slot);(record['directory']/'FireRed.state').write_bytes(b'broken')
        with self.assertRaises(RuntimeError):restore_profile(self.folder,record)
        self.assertEqual((self.folder/'Data/FireRed.state').read_bytes(),self.before)
        self.assertFalse(list((self.folder/'Data/backups/actions').glob('*')))
    def test_an_open_profile_cannot_be_restored_from_picker(self):
        with (self.folder/'Data/.session.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with self.assertRaisesRegex(RuntimeError,'уже открыто'):restore_profile(self.folder,self.slots.get(self.slot))
        self.assertEqual((self.folder/'Data/FireRed.state').read_bytes(),self.before)
    def test_compressed_history_can_be_loaded_before_live_session(self):
        row=SaveTimeline(self.folder/'Data').records()[0];result=restore_profile(self.folder,row)
        with Game(self.folder) as game:self.assertEqual(game.frame,result['frame'])
    def test_cartridge_only_progress_is_preserved_before_restore(self):
        cartridge=(self.folder/'Data/FireRed.sav').read_bytes();(self.folder/'Data/FireRed.state').unlink()
        result=restore_profile(self.folder,self.slots.get(self.slot))
        self.assertEqual((result['backup']/'FireRed.sav').read_bytes(),cartridge)
        self.assertTrue((result['backup']/'FireRed.state').is_file())

class PickerHistoryTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from test_save_system import snapshot
        self.temp=tempfile.TemporaryDirectory();self.folder=Path(self.temp.name);(self.folder/'Data').mkdir()
        for name in ('src','native','vendor','assets','runtime','Bots'):(self.folder/name).mkdir()
        (self.folder/'Data/FireRed.gba').write_bytes(b'rom')
        publish_checkpoint(snapshot(0),self.folder/'Data','rom');publish_checkpoint(snapshot(1),self.folder/'Data','rom')
        self.root=tk.Tk();self.home=None
    def drive(self,predicate):
        end=time.monotonic()+4
        while not predicate() and time.monotonic()<end:self.root.update();time.sleep(.005)
        self.assertTrue(predicate())
    def tearDown(self):
        if self.home and not self.home.closed:self.home.close()
        self.root.destroy();self.temp.cleanup()
    def test_history_is_read_only_and_loading_dispatches_the_selected_record(self):
        from pokemon_red.startup import StartupHome
        before=hashlib.sha256((self.folder/'Data/FireRed.state').read_bytes()).hexdigest();choose=Mock()
        with patch('pokemon_red.engine.Game',side_effect=AssertionError('browsing must not create a core')):
            self.home=StartupHome(self.root,self.folder,choose);self.drive(lambda:len(getattr(self.home,'cards',[]))==1)
            self.home.cards[0]['history'].invoke();view=self.home.history;self.drive(lambda:len(view.tree.get_children())>=8)
            choose.assert_not_called();self.assertEqual(hashlib.sha256((self.folder/'Data/FireRed.state').read_bytes()).hexdigest(),before)
            view.tree.selection_set('age-5');view.selected();view.load.invoke();self.assertEqual(choose.call_args.args[1]['frame'],0)
            self.home.close_history();self.drive(lambda:len(self.home.body.winfo_children())>0);self.assertIsNone(self.home.history)
    def test_current_point_starts_profile_without_rollback(self):
        from pokemon_red.startup import StartupHome
        choose=Mock();self.home=StartupHome(self.root,self.folder,choose);self.drive(lambda:len(getattr(self.home,'cards',[]))==1)
        self.home.open_history(self.home.rows[0]);view=self.home.history;self.drive(lambda:bool(view.tree.get_children()))
        view.tree.selection_set('current');view.selected();self.assertTrue(view.load.enabled);view.restore();self.assertTrue(choose.call_args.args[1]['is_current'])
    def test_live_session_starts_only_after_restore_finishes_and_stays_paused(self):
        import tkinter as tk,threading
        from pokemon_red.startup import Application
        gate=threading.Event();entered=threading.Event()
        def restore(*_):entered.set();gate.wait(3)
        class Monitor:
            def __init__(self,window,folder,*,paused):
                self.window=window;self.paused=paused;self.game=SimpleNamespace(current_scroll_delta=lambda:None);self.callback_error=Mock()
                window.configure(menu=tk.Menu(window))
            def close(self):self.window.after_idle(self.window.destroy)
        with patch('pokemon_red.startup.restore_profile',side_effect=restore),patch('pokemon_red.gui.Monitor',Monitor):
            app=Application(self.root,self.folder);self.home=app.home;self.drive(lambda:len(getattr(self.home,'cards',[]))==1)
            row=self.home.rows[0];self.home.open_history(row);self.drive(lambda:bool(self.home.history.tree.get_children()))
            app.choose(row,self.home.history.records['age-5']);self.drive(entered.is_set)
            self.assertIsNone(app.monitor);self.assertTrue(self.home.history.loading);self.assertFalse(self.home.history.load.enabled)
            gate.set();self.drive(lambda:app.monitor is not None);self.assertTrue(app.monitor.paused)
            app.back();self.drive(lambda:app.monitor is None);self.home=app.home
    def test_failed_restore_keeps_history_open_without_starting_game(self):
        from pokemon_red.startup import Application
        with patch('pokemon_red.startup.restore_profile',side_effect=ValueError('invalid')),patch('pokemon_red.gui.Monitor') as monitor:
            app=Application(self.root,self.folder);self.home=app.home;self.drive(lambda:len(getattr(self.home,'cards',[]))==1)
            row=self.home.rows[0];self.home.open_history(row);self.drive(lambda:bool(self.home.history.tree.get_children()))
            app.choose(row,self.home.history.records['age-5']);self.drive(lambda:app.restore_future is None)
            monitor.assert_not_called();self.assertIsNotNone(self.home.history);self.assertFalse(self.home.history.loading);self.assertIn('invalid',self.home.history.status.cget('text'))

class ManualBackupRetentionTests(unittest.TestCase):
    def test_more_than_ten_manual_backups_preserve_history_clock_and_commit(self):
        from test_save_system import snapshot
        from pokemon_red.persistence import publish_checkpoint
        from pokemon_red.save_timeline import SaveTimeline
        with tempfile.TemporaryDirectory() as folder:
            data=Path(folder)/'Data'
            with patch('pokemon_red.persistence.sync_file',side_effect=lambda f,**_:f.flush()),patch('pokemon_red.persistence.sync_directory'):
                for n in range(13):publish_checkpoint(snapshot(n),data,'rom',backup=True)
            self.assertEqual((data/'FireRed.state').read_bytes(),snapshot(12).state)
            self.assertEqual(len(list((data/'backups/sessions').glob('*.state'))),10)
            self.assertEqual(SaveTimeline(data).current()['history_time'],60)

if __name__=='__main__':unittest.main()
