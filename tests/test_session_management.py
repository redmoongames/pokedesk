"""Reversible profile management and save-barrier return to the launcher."""
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock,patch
import fcntl,json,sys,tempfile,time,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.profiles import Profiles,LEGACY


class ProfileManagementTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.folder=Path(self.tmp.name);(self.folder/'Data').mkdir()
        for name in ('src','native','vendor','assets','runtime','Bots'):(self.folder/name).mkdir()
        (self.folder/'Data/FireRed.gba').write_bytes(b'ROM is shared')
        self.store=Profiles(self.folder);self.legacy=self.store.list()[0]
        for name in ('FireRed.state','FireRed.sav','save-info.json','save-preview.png','settings.json','training.json'):(self.folder/'Data'/name).write_bytes(name.encode())
        for name in ('slots/a/FireRed.state','rewind/earlier.state.z','backups/actions/b/metadata.json'):
            path=self.folder/'Data'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(name.encode())
    def tearDown(self):self.tmp.cleanup()
    def test_legacy_delete_is_reversible_and_never_moves_shared_data(self):
        before={p.relative_to(self.folder):p.read_bytes() for p in (self.folder/'Data').rglob('*') if p.is_file() and p.name not in ('profiles.json','profiles.lock')}
        self.store.archive(LEGACY);self.assertEqual(self.store.list(),[]);self.assertEqual(self.store.list(deleted=True)[0]['id'],LEGACY)
        self.assertEqual(Profiles(self.folder).list(),[])
        for path,blob in before.items():self.assertEqual((self.folder/path).read_bytes(),blob)
        self.store.restore(LEGACY);self.assertEqual(self.store.list()[0]['id'],LEGACY);self.assertEqual(self.store.list(deleted=True),[])
    def test_new_session_delete_restore_keeps_current_and_all_history(self):
        row=self.store.duplicate(LEGACY,'Branch');folder=self.store.folder(row);before=(folder/'Data/FireRed.state').read_bytes()
        self.store.archive(row['id']);self.assertNotIn(row['id'],{r['id'] for r in self.store.list()});self.assertTrue((folder/'Data/slots/a/FireRed.state').exists())
        restored=self.store.restore(row['id']);self.assertEqual(self.store.folder(restored),folder);self.assertEqual((folder/'Data/FireRed.state').read_bytes(),before)
    def test_open_session_cannot_be_deleted_or_copied(self):
        with (self.folder/'Data/.session.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            for action in (lambda:self.store.archive(LEGACY),lambda:self.store.duplicate(LEGACY,'copy')):
                with self.assertRaises(RuntimeError):action()
        self.assertEqual(len(self.store.list()),1)
    def test_unfinished_trade_protects_delete_copy_and_restore(self):
        with patch('pokemon_red.profile_trade.pending',return_value=['pending']):
            with self.assertRaises(RuntimeError):self.store.archive(LEGACY)
            with self.assertRaises(RuntimeError):self.store.duplicate(LEGACY,'copy')
        self.store.archive(LEGACY)
        with patch('pokemon_red.profile_trade.pending',return_value=['pending']):
            with self.assertRaises(RuntimeError):self.store.restore(LEGACY)
    def test_copy_is_independent_and_excludes_global_registry_jobs_and_caches(self):
        for name in ('history.sqlite3','navigation-cache.sqlite3','.session.lock'):(self.folder/'Data'/name).write_bytes(b'not copied')
        candidate=self.folder/'Data/starter-candidates'/('a'*64+'.state');candidate.parent.mkdir();candidate.write_bytes(b'candidate snapshot')
        (self.folder/'Data/starter-candidates.json').write_text('[]');(self.folder/'Data/starter-frontier.state').write_bytes(b'safe frontier')
        row=self.store.duplicate(LEGACY,'Branch');folder=self.store.folder(row)
        self.assertEqual((folder/'Data'/candidate.relative_to(self.folder/'Data')).read_bytes(),b'candidate snapshot');self.assertEqual((folder/'Data/starter-frontier.state').read_bytes(),b'safe frontier')
        self.assertNotEqual(row['id'],LEGACY);self.assertEqual(row['game'],'firered')
        self.assertEqual((folder/'Data/FireRed.state').read_bytes(),b'FireRed.state')
        self.assertEqual((folder/'Data/slots/a/FireRed.state').read_bytes(),b'slots/a/FireRed.state')
        for name in ('history.sqlite3','navigation-cache.sqlite3','.session.lock','profiles.json'):self.assertFalse((folder/'Data'/name).exists())
        (folder/'Data/FireRed.state').write_bytes(b'new progress');self.assertEqual((self.folder/'Data/FireRed.state').read_bytes(),b'FireRed.state')
        self.assertTrue((folder/'Data/FireRed.gba').is_symlink());self.assertFalse((folder/'Data/FireRed.gba').readlink().is_absolute())
        from pokemon_red.paths import resource
        self.assertEqual(resource(folder,'native').resolve(),(self.folder/'native').resolve())
        self.assertFalse((folder/'native').exists())
    def test_copy_failure_does_not_publish_half_created_profile(self):
        original=(self.folder/'Data/profiles.json').read_bytes()
        from pokemon_red.persistence import atomic_bytes
        def write(path,*args,**kw):
            if Path(path).name=='FireRed.state':raise OSError('disk full')
            return atomic_bytes(path,*args,**kw)
        with patch('pokemon_red.profiles.atomic_bytes',side_effect=write):
            with self.assertRaisesRegex(OSError,'disk full'):self.store.duplicate(LEGACY,'Branch')
        self.assertEqual((self.folder/'Data/profiles.json').read_bytes(),original);self.assertEqual(list((self.folder/'Profiles').iterdir()),[])
    def test_failed_manifest_write_preserves_visibility_and_can_be_retried(self):
        with patch.object(self.store,'_write',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):self.store.archive(LEGACY)
        self.assertEqual(len(self.store.list()),1);self.store.archive(LEGACY);self.assertEqual(self.store.list(),[])
    def test_link_inside_save_payload_is_rejected_without_touching_target(self):
        outside=self.folder/'private';outside.write_bytes(b'private')
        (self.folder/'Data/slots/link').symlink_to(outside)
        with self.assertRaises(ValueError):self.store.duplicate(LEGACY,'Branch')
        self.assertEqual(outside.read_bytes(),b'private');self.assertEqual(len(self.store.list()),1)
    def test_stale_deleted_profile_cannot_be_renamed_copied_or_started(self):
        self.store.archive(LEGACY)
        for action in (lambda:self.store.get(LEGACY),lambda:self.store.rename(LEGACY,'No'),lambda:self.store.duplicate(LEGACY,'No')):
            with self.assertRaises(ValueError):action()


class SessionManagementUITests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk,gc
        gc.collect();self.root=tk.Tk();self.root.geometry('780x650');self.root.update();self.home=None
        self.tmp=tempfile.TemporaryDirectory();self.folder=Path(self.tmp.name);(self.folder/'Data').mkdir()
        for name in ('src','native','vendor','assets','runtime','Bots'):(self.folder/name).mkdir()
        (self.folder/'Data/FireRed.gba').write_bytes(b'rom')
        from test_save_system import snapshot
        from pokemon_red.persistence import publish_checkpoint
        publish_checkpoint(snapshot(0),self.folder/'Data','rom')
        self.errors=[];self.root.report_callback_exception=lambda kind,error,tb:self.errors.append(error)
    def drive(self,predicate):
        deadline=time.monotonic()+5
        while not predicate() and time.monotonic()<deadline:self.root.update();time.sleep(.005)
        self.assertTrue(predicate());self.assertEqual(self.errors,[])
    def picker(self):
        from pokemon_red.startup import StartupHome
        self.home=StartupHome(self.root,self.folder,Mock());self.drive(lambda:len(getattr(self.home,'cards',[]))==1)
        return self.home
    def tearDown(self):
        if self.home and not self.home.closed:self.home.close()
        self.root.destroy();self.tmp.cleanup();self.assertEqual(self.errors,[])
    def test_exit_cancel_stops_bot_pauses_and_confirm_closes_only_once(self):
        from pokemon_red.session_ui import confirm_return_to_menu
        monitor=NS(window=self.root,panel=None,closed=False,close_requested=False,take_control=Mock(),pause=Mock())
        close=Mock();dialog=confirm_return_to_menu(monitor,close);self.root.update()
        self.assertIsNone(self.root.grab_current());monitor.take_control.assert_called_once_with(focus=False);monitor.pause.assert_called_once_with(save=False)
        self.assertIs(confirm_return_to_menu(monitor,close),dialog);dialog.cancel_button.invoke();close.assert_not_called()
        dialog=confirm_return_to_menu(monitor,close);dialog.confirm_button.invoke();dialog.accept();close.assert_called_once()
    def test_confirmation_does_not_consume_global_f9(self):
        from pokemon_red.session_ui import Confirmation
        handler=Mock();self.root.bind_all('<F9>',lambda _:handler())
        dialog=Confirmation(self.root,title='Exit?',message='Saved first',confirm='Yes',on_confirm=Mock())
        dialog.window.focus_force();self.root.update();dialog.window.event_generate('<KeyPress-F9>');self.root.update();handler.assert_called_once();dialog.cancel()
    def test_picker_delete_cancel_restore_and_duplicate(self):
        home=self.picker();row=home.rows[0]
        dialog=home.delete(row);dialog.cancel_button.invoke();self.assertEqual(len(home.store.list()),1)
        dialog=home.delete(row);dialog.confirm_button.invoke();self.drive(lambda:home.management_future is None and home.future is None and not home.cards)
        home.mode.set('deleted');home.refresh();self.drive(lambda:home.future is None and len(home.cards)==1)
        home.cards[0]['button'].invoke();self.drive(lambda:home.management_future is None and home.future is None and not home.cards)
        home.mode.set('active');home.refresh();self.drive(lambda:home.future is None and len(home.cards)==1)
        with patch('pokemon_red.startup.simpledialog.askstring',return_value='Branch'):home.duplicate(home.rows[0])
        self.drive(lambda:home.management_future is None and home.future is None and len(home.cards)==2)
        self.assertTrue(any(r['name']=='Branch' for r in home.rows))
    def test_stale_preview_from_other_tab_is_discarded(self):
        import threading
        from pokemon_red.startup import read_profiles
        home=self.picker();gate=threading.Event();entered=threading.Event()
        def slow(store,deleted=False):entered.set();gate.wait(3);return read_profiles(store,deleted)
        with patch('pokemon_red.startup.read_profiles',side_effect=slow):
            home.refresh();self.assertTrue(entered.wait(1));home.mode.set('deleted');home.refresh();gate.set()
            self.drive(lambda:home.future is None and not home.cards)
        self.assertEqual(home.store.list(deleted=True),[])
    def test_profile_actions_stays_reachable_and_no_grab_blocks_f9(self):
        from pokemon_red.session_ui import profile_actions
        home=self.picker();profile_actions(home,home.rows[0],home.cards[0]['button']);self.root.update()
        popup=home.action_menu;self.assertTrue(popup.winfo_viewable());self.assertIsNone(self.root.grab_current())
        handler=Mock();self.root.bind_all('<F9>',lambda _:handler());popup.focus_force();self.root.update();popup.event_generate('<KeyPress-F9>');self.root.update();handler.assert_called_once()
        popup.destroy()


from test_runtime_performance import PrivateSessionTestCase


class SessionReturnIntegrationTests(PrivateSessionTestCase):
    def setUp(self):
        import tkinter as tk,gc
        gc.collect();super().setUp();self.window=tk.Tk();self.window.update();self.errors=[];self.app=None
        from pokemon_red.gui import Monitor
        from pokemon_red.startup import Application
        from test_engine_runtime import ProbeRuntime
        self.patch=patch('pokemon_red.gui.Monitor',side_effect=lambda window,folder,*,paused:Monitor(window,folder,paused=paused,runtime_factory=ProbeRuntime));self.patch.start()
        self.error_popup=patch('pokemon_red.gui.messagebox.showerror');self.error_popup.start()
        self.retry_popup=patch('pokemon_red.gui.messagebox.askretrycancel',return_value=False);self.retry_popup.start()
        self.app=Application(self.window,self.root,paused=True);self.window.report_callback_exception=lambda kind,error,tb:self.errors.append(error)
        self.drive(lambda:bool(getattr(self.app.home,'cards',[])))
        self.row=self.app.home.rows[0];self.app.choose(self.row);self.drive(lambda:self.app.monitor.ready)
        # Retain our callback error collector across the launcher/monitor handoff.
        self.window.report_callback_exception=lambda kind,error,tb:self.errors.append(error)
    def drive(self,predicate):
        deadline=time.monotonic()+8
        while not predicate() and time.monotonic()<deadline:self.window.update();time.sleep(.002)
        self.assertTrue(predicate(),self.errors);self.assertEqual(self.errors,[])
    def tearDown(self):
        if self.app.monitor:
            self.app.back();self.drive(lambda:self.app.monitor is None)
        if self.app.home and not self.app.home.closed:self.app.home.close()
        self.window.destroy();self.patch.stop();self.error_popup.stop();self.retry_popup.stop();self.app=None;self.window=None
        import gc
        gc.collect();super().tearDown()
    def test_menu_waits_for_durable_save_and_session_can_be_reopened(self):
        import threading
        from pokemon_red.engine import Game
        m=self.app.monitor;gate=threading.Event();entered=threading.Event()
        def prepare(c):
            c.game.advance(37);c.writer.submit(lambda:(entered.set(),gate.wait(5)))
            return c.game.frame
        frame=m.runtime.submit('probe',prepare).result(4);self.assertTrue(entered.wait(1))
        try:
            dialog=self.app.request_back();dialog.cancel_button.invoke();self.assertIs(self.app.monitor,m);self.assertFalse(m.close_requested)
            dialog=self.app.request_back();dialog.confirm_button.invoke();beats=[];self.window.after(0,lambda:beats.append(True));self.drive(lambda:bool(beats))
            self.assertIs(self.app.monitor,m);self.assertFalse(m.closed)
            gate.set();self.drive(lambda:self.app.monitor is None)
            with Game(self.root) as restored:self.assertEqual(restored.frame,frame)
            copy=self.app.store.duplicate(self.row['id'],'Native branch')
            with Game(self.app.store.folder(copy)) as restored:self.assertEqual(restored.frame,frame)
            self.drive(lambda:bool(getattr(self.app.home,'cards',[])));self.app.choose(self.row);self.drive(lambda:self.app.monitor.ready)
            # SessionController renders exactly one initial frame on open.
            self.assertEqual(self.app.monitor.runtime.submit('probe',lambda c:c.game.frame).result(4),frame+1)
        finally:gate.set()
    def test_save_failure_keeps_session_open_then_retry_returns_to_menu(self):
        m=self.app.monitor
        with patch('pokemon_red.session_controller.publish_checkpoint',side_effect=OSError('disk full')):
            dialog=self.app.request_back();dialog.confirm_button.invoke();self.drive(lambda:m.save_failed and not m.close_requested)
            self.assertIs(self.app.monitor,m);self.assertFalse(m.closed);self.assertTrue(m.paused)
        dialog=self.app.request_back();dialog.confirm_button.invoke();self.drive(lambda:self.app.monitor is None)


if __name__=='__main__':unittest.main()
