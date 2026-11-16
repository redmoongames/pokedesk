"""Native profile isolation, legacy data preservation and pack-build contracts."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from test_runtime_performance import PrivateSessionTestCase
from test_engine_runtime import ProbeRuntime
from pokemon_red.paths import session_paths,bind_installation,resource,LAYOUT_FILE
from pokemon_red.catalog import catalog
from pokemon_red.database import connect
from pokemon_red.editions import edition
from pokemon_red.reference_pack import build_reference,compile_reference,load_reference,_read


class ReferencePackBuildTests(unittest.TestCase):
    def test_rom_import_writes_only_the_writable_library(self):
        from pokemon_red.editions import install_rom,available
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);bind_installation(root,ROOT,kind='profile',library=root)
            written=[]
            from pokemon_red.persistence import atomic_bytes
            def record(path,*args,**kwargs):
                written.append(Path(path));return atomic_bytes(path,*args,**kwargs)
            with patch('pokemon_red.editions.atomic_bytes',side_effect=record):
                install_rom(root,ROOT/'ROMs/Ruby-Rev2.gba','ruby')
            self.assertEqual(written,[root/'ROMs/Ruby-Rev2.gba'])
            self.assertTrue(available(root,'ruby'))
            self.assertFalse((root/'Data').exists())

    def test_all_editions_match_the_enrichment_recipe(self):
        for game in ('firered','leafgreen','ruby','sapphire'):
            with self.subTest(game=game),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);bind_installation(root,ROOT)
                (root/'Data').mkdir();(root/'Data/game.json').write_text(json.dumps(dict(game=game)))
                self.assertEqual(load_reference(root),compile_reference(ROOT,game))

    def test_failed_pack_publication_keeps_previous_pack_and_journal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'vendor/catalog').mkdir(parents=True)
            # Copy only build inputs; nothing is written through shared links.
            shutil.copytree(ROOT/'vendor/catalog',root/'vendor/catalog',dirs_exist_ok=True)
            shutil.copytree(ROOT/'vendor/reference',root/'vendor/reference')
            pack=root/'vendor/catalog/packs/firered.json';before=pack.read_bytes()
            db=connect(root);db.execute('CREATE TABLE sentinel(value TEXT)');db.execute("INSERT INTO sentinel VALUES('save-history')");db.commit();db.close()
            journal=(root/'Data/history.sqlite3').read_bytes()
            with patch('pokemon_red.persistence.atomic_bytes',side_effect=OSError('disk full')):
                with self.assertRaises(OSError):build_reference(root,'firered')
            self.assertEqual(pack.read_bytes(),before)
            self.assertEqual((root/'Data/history.sqlite3').read_bytes(),journal)

    def test_new_journal_has_no_reference_tables_and_old_tables_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);db=connect(root)
            tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertFalse(tables&{'species','moves','abilities','route_encounters','reference_meta'})
            db.execute('CREATE TABLE reference_meta(key TEXT PRIMARY KEY,value TEXT)')
            db.execute("INSERT INTO reference_meta VALUES('legacy','retain')");db.commit();db.close()
            db=connect(root);self.assertEqual(db.execute("SELECT value FROM reference_meta WHERE key='legacy'").fetchone()[0],'retain');db.close()


class SeparateProfileNativeTests(PrivateSessionTestCase):
    def separate(self):
        installation=self.root/'installation';installation.mkdir()
        for name in ('src','native','vendor','assets','runtime','Bots'):
            (installation/name).symlink_to(ROOT/name,target_is_directory=True)
            alias=self.root/name
            if alias.is_symlink():alias.unlink()
        bind_installation(self.root,installation,kind='profile',library=self.root)
        return installation

    def test_owner_autosave_manual_input_and_analytics_without_resource_aliases(self):
        installation=self.separate();before=set(installation.iterdir());installation.chmod(0o555)
        runtime=ProbeRuntime(self.root,paused=True)
        try:
            runtime.ready.result(15)
            def setup(c):
                c.game.load_state(ROOT/'tests/fixtures/fire_red/clinic.state');c.refresh_state()
                c.settings.values.update(autosave_enabled=True,autosave_seconds=5)
                c.last_save=time.monotonic()-10;c.set_speed(16)
                return c.last_saved_frame
            saved=runtime.submit('probe',setup).result(5)
            deadline=time.monotonic()+5
            while runtime.latest.status['last_saved_frame']<=saved and time.monotonic()<deadline:time.sleep(.005)
            self.assertGreater(runtime.latest.status['last_saved_frame'],saved)
            self.assertIsInstance(runtime.submit('history_read','comparisons',()).result(10),list)
            script=self.root/'hold.py';script.write_text("def run(bot):\n    bot.press('RIGHT',frames=36000)\n")
            runtime.submit('start_bot',script).result(10)
            deadline=time.monotonic()+5
            while not runtime.latest.status['automation']['running'] and time.monotonic()<deadline:time.sleep(.005)
            self.assertTrue(runtime.latest.status['automation']['running'])
            at=time.monotonic();epoch=runtime.take_control(pause=False)
            while runtime.latest.epoch<epoch and time.monotonic()-at<2:time.sleep(.001)
            self.assertGreaterEqual(runtime.latest.epoch,epoch)
            self.assertFalse(runtime.latest.status['automation']['running'])
            runtime.submit('manual','B',True).result(5);runtime.submit('manual','B',False).result(5)
            runtime.submit('save',True).result(10)
        finally:
            runtime.take_control(close=True);runtime.finished.result(15);runtime.thread.join(2);installation.chmod(0o755)
        self.assertEqual(before,set(installation.iterdir()))
        self.assertFalse((installation/'Data').exists())
        self.assertTrue(session_paths(self.root).profile.journal.is_file())
        self.assertTrue((self.root/'Data/FireRed.state').is_file())

    def test_new_profile_and_job_run_after_portable_tree_move(self):
        from pokemon_red.profiles import Profiles
        from pokemon_red.operations import clone_session
        from pokemon_red.engine import Game
        from pokemon_red.telemetry import read_state
        installation=self.separate()
        # The moved native workload carries the actual resources it reads, not
        # links back to the pre-move temporary installation.
        for name in ('native','vendor'):
            (installation/name).unlink();shutil.copytree(ROOT/name,installation/name)
        (self.root/'Data/FireRed.gba').unlink()
        shutil.copyfile(ROOT/'Data/FireRed.gba',self.root/'Data/FireRed.gba')
        store=Profiles(self.root);row=store.create('Portable QA');profile=store.folder(row)
        with Game(self.root) as game:
            game.load_state(ROOT/'tests/fixtures/fire_red/clinic.state')
            snapshot=game.capture_save()
        snapshot.publish(profile/'Data')
        job=clone_session(profile,profile/'Sessions/operations/test/main',snapshot)
        self.assertFalse((profile/'src').exists());self.assertFalse((job/'vendor').exists())
        relocation=tempfile.TemporaryDirectory(prefix='Pokemon moved tree ');self.addCleanup(relocation.cleanup)
        moved=Path(relocation.name).resolve()/'Moved portable project';self.root.rename(moved)
        self.root=moved
        profile=Profiles(moved).folder(row);job=profile/'Sessions/operations/test/main'
        with Game(job) as game:
            self.assertTrue(read_state(game)['ready'])
            self.assertEqual(edition(game.root).id,'firered')
            self.assertEqual(game.frame,snapshot.frame)
        self.assertEqual(session_paths(job).installation.root,moved/'installation')
        self.assertFalse((moved/'installation/Data').exists())
