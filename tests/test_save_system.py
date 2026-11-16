"""Profile isolation, temporal retention, integrity and startup without a live core."""
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch,Mock
import hashlib,json,os,shutil,sys,tempfile,time,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.persistence import SaveSnapshot,publish_checkpoint
from pokemon_red.save_timeline import SaveTimeline,AGES
from pokemon_red.profiles import Profiles,LEGACY

def snapshot(n,stamp=None,*,producer='run-a',active=None):
    return SaveSnapshot(('state-'+str(n)).encode(),b'cartridge',n,10000+n*5 if stamp is None else stamp,
                        json.dumps(dict(ready=True,player='ALEX',money=n,pokedex=dict(caught=n,seen=n,total=386))).encode(),b'',producer,n*5 if active is None else active)

class TimelineTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.data=Path(self.temp.name)/'Data';self.timeline=SaveTimeline(self.data)
        self.sync=patch('pokemon_red.persistence.sync_file',side_effect=lambda f,**_:f.flush());self.directory=patch('pokemon_red.persistence.sync_directory');self.sync.start();self.directory.start()
    def tearDown(self):self.sync.stop();self.directory.stop();self.temp.cleanup()
    def save(self,s):return publish_checkpoint(s,self.data,'rom')
    def test_seven_windows_are_actual_previous_commits(self):
        for n in range(373):self.save(snapshot(n))
        current=self.timeline.current();self.assertEqual(current['frame'],372)
        anchors=self.timeline.anchors();self.assertEqual([a for a,_ in anchors],list(AGES))
        for age,row in anchors:
            self.assertIsNotNone(row);self.assertEqual(row['frame'],372-age//5);self.assertEqual(row['age_seconds'],age)
            self.assertEqual(SaveTimeline.restore_bytes(row['directory'],'rom'),snapshot(row['frame']).state)
        rows=self.timeline.records();self.assertLessEqual(len(rows),362);self.assertGreaterEqual(rows[-1]['history_time'],current['history_time']-1805)
    def test_missing_windows_are_not_substituted_with_newer_saves(self):
        self.save(snapshot(0));self.save(snapshot(1));self.save(snapshot(2))
        anchors=dict(self.timeline.anchors());self.assertEqual(anchors[5]['frame'],1)
        for age in AGES[1:]:self.assertIsNone(anchors[age])
    def test_small_timer_jitter_does_not_double_five_second_rollback(self):
        self.save(snapshot(0));self.save(snapshot(1,active=5.02));self.save(snapshot(2,active=10.0))
        self.assertEqual(dict(self.timeline.anchors())[5]['frame'],1)
    def test_closed_application_and_paused_unchanged_state_do_not_age_history(self):
        self.save(snapshot(0));self.save(snapshot(1));self.save(replace(snapshot(1),captured_at=1_000_000,active_seconds=500))
        self.assertEqual(self.timeline.current()['history_time'],5)
        self.save(snapshot(2,stamp=2_000_000,producer='run-b',active=5));self.assertEqual(self.timeline.current()['history_time'],10)
        self.assertEqual(dict(self.timeline.anchors())[5]['frame'],1)
    def test_metadata_is_not_used_when_it_belongs_to_different_state(self):
        self.save(snapshot(0));(self.data/'FireRed.state').write_bytes(b'changed')
        self.assertIsNone(self.timeline.current())
    def test_failed_staging_keeps_current_commit_and_all_old_history(self):
        self.save(snapshot(0));self.save(snapshot(1));old=self.timeline.current()
        with patch.object(SaveSnapshot,'publish',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):self.save(snapshot(2))
        self.assertEqual((self.data/'FireRed.state').read_bytes(),snapshot(1).state);self.assertEqual(self.timeline.current()['sha256'],old['sha256'])
        self.assertTrue(self.timeline.records())
    def test_corrupt_compressed_backup_and_wrong_rom_are_rejected(self):
        self.save(snapshot(0));self.save(snapshot(1));row=self.timeline.records()[0]
        with self.assertRaises(ValueError):SaveTimeline.restore_bytes(row['directory'],'wrong-rom')
        (row['directory']/'state.z').write_bytes(b'damaged')
        with self.assertRaises(ValueError):SaveTimeline.restore_bytes(row['directory'],'rom')

class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=(Path(self.temp.name)/'Project').resolve();(self.root/'Data').mkdir(parents=True)
        (self.root/'Data/FireRed.gba').write_bytes(b'rom')
        for d in ('src','native','vendor','assets','runtime','Bots'):(self.root/d).mkdir()
        self.store=Profiles(self.root)
    def tearDown(self):self.temp.cleanup()
    def test_existing_progress_is_registered_in_place_and_new_slot_is_empty(self):
        state=self.root/'Data/FireRed.state';state.write_bytes(b'existing');first=self.store.list()[0]
        self.assertEqual(first['id'],LEGACY);self.assertEqual(self.store.folder(first),self.root)
        second=self.store.create();folder=self.store.folder(second)
        self.assertFalse((folder/'Data/FireRed.state').exists());self.assertEqual(state.read_bytes(),b'existing')
        (folder/'Data/training.json').write_text('{"own": true}');self.assertFalse((self.root/'Data/training.json').exists())
        self.assertFalse((folder/'templates/FireRed/Progressed-hunting-v1').exists())
    def test_profiles_and_relative_installation_layout_survive_project_move(self):
        row=self.store.create();moved=self.root.with_name('Moved project');self.root.rename(moved)
        other=Profiles(moved);profile=other.folder(row)
        self.assertTrue((profile/'Data/FireRed.gba').is_file())
        from pokemon_red.paths import session_paths,LAYOUT_FILE
        self.assertEqual(session_paths(profile).installation.root,moved.resolve())
        self.assertFalse(Path(json.loads((profile/LAYOUT_FILE).read_text())['installation']).is_absolute())
    def test_profile_switch_cannot_cross_project_or_reinterpret_display_name_as_path(self):
        with self.assertRaises(ValueError):self.store.folder(dict(id='../outside',root='..'))
        row=self.store.create('../../name is text');self.assertTrue(self.store.folder(row).is_relative_to(self.root))
    def test_registry_updates_are_serialized_and_corruption_does_not_erase_slots(self):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as pool:rows=list(pool.map(lambda n:self.store.create(str(n)),range(2)))
        self.assertEqual(len(self.store.list()),3)
        raw=b'{broken';self.store.path.write_bytes(raw)
        with self.assertRaises(ValueError):self.store.list()
        self.assertEqual(self.store.path.read_bytes(),raw)
    def test_profile_summaries_are_separate_and_do_not_start_emulator_when_cached(self):
        first=self.store.list()[0];second=self.store.create()
        for row,n in [(first,1),(second,2)]:publish_checkpoint(snapshot(n),self.store.folder(row)/'Data','rom')
        with patch('pokemon_red.engine.Game',side_effect=AssertionError('should use detached summary')):
            self.assertEqual(self.store.summary(first)['metadata']['summary']['money'],1)
            self.assertEqual(self.store.summary(second)['metadata']['summary']['money'],2)

class ActiveClockTests(unittest.TestCase):
    def test_memory_checkpoints_skip_preview_and_summary_work(self):
        from pokemon_red.engine import Game
        with Game(ROOT,resume=False) as game:
            game.advance(1)
            with patch('pokemon_red.save_metadata.capture',side_effect=AssertionError('memory-only checkpoint')):
                state=game.capture_save(metadata=False)
            self.assertTrue(state.state);self.assertEqual(len(state.sram),131072);self.assertEqual(state.summary,b'');self.assertEqual(state.preview,b'')
    def test_real_play_time_excludes_long_pauses_and_zero_frame_input_release(self):
        from pokemon_red.engine import Game
        game=Game.__new__(Game);game._check=Mock();game.lib=Mock();game.handle=1;game.active_seconds=0;game._active_at=None;game.revision=0
        with patch('pokemon_red.engine.time.monotonic',side_effect=[10,10.001,10.1,10.101,100,100.001,100.2,200,200.001]):
            game.advance(1);game.advance(1);game.advance(1);game.advance(0);game.advance(1)
        self.assertAlmostEqual(game.active_seconds,.103,places=3)
        game.handle=None
    def test_releasing_buttons_does_not_discard_ongoing_play_time(self):
        from pokemon_red.engine import Game
        game=Game.__new__(Game);game._check=Mock();game.lib=Mock();game.handle=1;game.active_seconds=0;game._active_at=None;game.revision=0
        with patch('pokemon_red.engine.time.monotonic',side_effect=[10,10.001,10.05,10.1,10.101]):game.advance(1);game.advance(0);game.advance(1)
        self.assertAlmostEqual(game.active_seconds,.101,places=3);game.handle=None

class SaveInterfaceTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from types import SimpleNamespace
        from pokemon_red.ui import BG,theme
        self.temp=tempfile.TemporaryDirectory();self.folder=Path(self.temp.name);(self.folder/'Data').mkdir()
        self.root=tk.Tk();self.root.geometry('580x800');theme(self.root);self.parent=tk.Frame(self.root,bg=BG);self.parent.pack(fill='both',expand=True)
        self.monitor=SimpleNamespace(folder=self.folder,pause=Mock(),load_backup=Mock(),load_slot=Mock(),save=Mock(),return_to_menu=Mock())
        self.panel=SimpleNamespace(monitor=self.monitor,window=self.root,show=Mock())
    def tearDown(self):self.root.destroy();self.temp.cleanup()
    def drive(self,predicate):
        deadline=time.monotonic()+4
        while not predicate() and time.monotonic()<deadline:self.root.update();time.sleep(.005)
        self.assertTrue(predicate())
    def test_temporary_points_are_disabled_and_restore_uses_selected_record(self):
        from pokemon_red.save_history_ui import SaveHistoryView
        publish_checkpoint(snapshot(0),self.folder/'Data','rom');publish_checkpoint(snapshot(1),self.folder/'Data','rom')
        view=SaveHistoryView(self.panel,self.parent);self.drive(lambda:len(view.tree.get_children())==8)
        view.tree.selection_set('age-15');view.selected();self.assertFalse(view.load.enabled)
        view.tree.selection_set('age-5');view.selected();self.assertTrue(view.load.enabled);view.restore()
        self.monitor.pause.assert_called_once_with(save=False);self.monitor.load_backup.assert_called_once_with(view.records['age-5']['directory']);self.panel.show.assert_called_once_with('overview')
    def test_startup_renders_original_size_preview_without_starting_session(self):
        from pokemon_red.startup import StartupHome
        from pokemon_red.save_metadata import png
        for d in ('src','native','vendor','assets','runtime','Bots'):(self.folder/d).mkdir()
        (self.folder/'Data/FireRed.gba').write_bytes(b'rom');image=png(bytes((120,160,200))*240*160)
        publish_checkpoint(replace(snapshot(0),preview=image),self.folder/'Data','rom');chosen=Mock()
        with patch('pokemon_red.engine.Game',side_effect=AssertionError('startup must use cached metadata')):
            home=StartupHome(self.root,self.folder,chosen);self.drive(lambda:len(getattr(home,'cards',[]))==1)
            self.assertEqual([(photo.width(),photo.height()) for photo in home.images],[(240,160)]);chosen.assert_not_called()
            home.cards[0]['button'].invoke();self.assertEqual(chosen.call_args.args[0]['id'],LEGACY);home.close()
    def test_return_to_menu_reuses_one_interpreter_and_removes_session_callbacks(self):
        import tkinter as tk
        import gc,weakref
        from types import SimpleNamespace
        from pokemon_red.startup import Application
        for d in ('src','native','vendor','assets','runtime','Bots'):(self.folder/d).mkdir()
        (self.folder/'Data/FireRed.gba').write_bytes(b'rom');publish_checkpoint(snapshot(0),self.folder/'Data','rom')
        class FakeMonitor:
            def __init__(self,window,folder,**_):
                self.window=window;self.game=SimpleNamespace(current_scroll_delta=lambda:None);self.callback_error=Mock();self.save=Mock()
                menu=tk.Menu(window);window.configure(menu=menu);window.bind_all('<KeyPress>',lambda _:self.save(),add='+');window.after(60000,lambda:None)
            def close(self):self.window.after_idle(self.window.destroy)
        with patch('pokemon_red.gui.Monitor',FakeMonitor):
            app=Application(self.root,self.folder,paused=True);self.drive(lambda:len(getattr(app.home,'cards',[]))==1)
            before=self.root.tk.call('bind','all','<KeyPress>')
            for _ in range(2):
                app.choose(app.store.list()[0]);previous=weakref.ref(app.monitor);self.assertIsInstance(app.session_window,tk.Toplevel);app.back();self.drive(lambda:app.monitor is None)
                self.assertEqual(self.root.tk.call('bind','all','<KeyPress>'),before);self.assertTrue(self.root.winfo_exists())
                gc.collect();self.assertIsNone(previous())
            app.home.close()

if __name__=='__main__':unittest.main()
