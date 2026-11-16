"""Real bots, late imports, F9/autosave and rejection before state adoption."""
from pathlib import Path
from types import SimpleNamespace
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from test_runtime_performance import PrivateSessionTestCase
from test_engine_runtime import ProbeRuntime
from pokemon_red.installation_versions import prepare_installation


class PinnedBotTests(PrivateSessionTestCase):
    def setUp(self):
        super().setUp();self.runtime=ProbeRuntime(self.root,paused=True);self.runtime.ready.result(10)

    def tearDown(self):
        self.runtime.take_control(close=True);self.runtime.finished.result(15);self.runtime.thread.join(2)
        super().tearDown()

    def probe(self,function):return self.runtime.submit('probe',function).result(5)

    def wait(self,predicate,timeout=8):
        end=time.monotonic()+timeout
        while not predicate() and time.monotonic()<end:time.sleep(.005)
        self.assertTrue(predicate(),str(self.runtime.latest.status.get('notice')))

    def test_preparation_cannot_delay_autosaves_or_revive_after_f9(self):
        entered=threading.Event();gate=threading.Event();script=self.root/'hold.py';script.write_text('def run(bot): pass\n')
        def slow(*_):entered.set();gate.wait(6);return object()
        with patch('pokemon_red.installation_versions.prepare_bot',side_effect=slow):
            self.runtime.submit('start_bot',script).result(5);self.assertTrue(entered.wait(3))
            def autosave(c):
                c.settings.values.update(autosave_enabled=True,autosave_seconds=5)
                c.last_save=time.monotonic()-10;c.set_speed(16);return c.last_saved_frame
            before=self.probe(autosave)
            try:
                self.wait(lambda:self.runtime.latest.status['last_saved_frame']>before,5)
                epoch=self.runtime.take_control(pause=False)
                self.wait(lambda:self.runtime.latest.epoch>=epoch,2)
                self.runtime.submit('manual','B',True).result(5);self.runtime.submit('manual','B',False).result(5)
            finally:gate.set()
            self.wait(lambda:not self.probe(lambda c:bool(c.preparations)),3)
        self.assertFalse(self.runtime.latest.status['automation']['running'])
        self.assertFalse(self.runtime.latest.status['save_failed'])

    def test_running_custom_bot_imports_original_helper_after_source_update(self):
        script=self.root/'custom.py';helper=self.root/'helper.py';helper.write_text('VALUE=1\n')
        script.write_text("import time\ndef run(bot):\n    root=bot.project_dir\n    (root/'ready').touch()\n    while not (root/'continue').exists(): time.sleep(.01)\n    import helper\n    (root/'observed').write_text(str(helper.VALUE))\n")
        self.runtime.submit('start_bot',script).result(5)
        self.wait(lambda:(self.root/'ready').exists(),12)
        helper.write_text('VALUE=2\n');script.write_text('raise RuntimeError("new code")\n')
        (self.root/'continue').touch();self.wait(lambda:(self.root/'observed').exists(),5)
        self.assertEqual((self.root/'observed').read_text(),'1')
        self.wait(lambda:not self.runtime.latest.status['automation']['running'])

    def test_preparation_queue_rejection_releases_pending_launch_and_manual_input(self):
        script=self.root/'hold.py';script.write_text('def run(bot): pass\n')
        with patch('pokemon_red.installation_versions.submit_preparation',side_effect=RuntimeError('queue full')):
            self.runtime.submit('start_bot',script).result(5)
            self.wait(lambda:self.probe(lambda c:c.pending_start is None),5)
            self.assertFalse(self.runtime.latest.status['automation']['running'])
            self.runtime.submit('manual','B',True).result(5);self.runtime.submit('manual','B',False).result(5)

    def test_foreign_result_is_rejected_before_game_or_save_changes(self):
        def attempt(c):
            job=self.root/'Sessions/operations/foreign';(job/'main/Data').mkdir(parents=True)
            snapshot=c.game.capture_save(metadata=False);snapshot.publish(job/'main/Data')
            expected=dict(release_id='a'*64,run_id='run-one')
            (job/'operation.json').write_text(json.dumps(dict(kind='local',config={})))
            (job/'status.json').write_text(json.dumps(dict(status='ready')))
            (job/'result.json').write_text(json.dumps(dict(_execution=dict(expected,release_id='b'*64),main_hashes={name:hashlib.sha256((job/'main/Data'/name).read_bytes()).hexdigest() for name in ('FireRed.state','FireRed.sav')})))
            operation=c.operation;operation.job=job;operation.kind='local';operation.frame=c.game.frame;operation.game=c.game
            operation.generation=c.game.state_generation
            operation.execution=expected;operation.last_poll=0;operation.process=SimpleNamespace(pid=2**30,poll=lambda:0)
            before=(c.game.frame,c.game.revision,(self.root/'Data/FireRed.state').read_bytes())
            operation.poll()
            return before,(c.game.frame,c.game.revision,(self.root/'Data/FireRed.state').read_bytes()),operation.result
        before,after,result=self.probe(attempt)
        self.assertEqual(before,after);self.assertFalse(result['applied']);self.assertEqual(result['status'],'attention')


class PinnedHostTests(unittest.TestCase):
    def test_cli_owner_lazy_save_import_and_autosave_survive_installation_update(self):
        from pokemon_red.paths import bind_installation
        with tempfile.TemporaryDirectory(prefix='Pokemon pinned host ') as temporary:
            base=Path(temporary);app=base/'app';library=base/'library'
            for name in ('src','native','vendor','assets','Bots'):
                shutil.copytree(ROOT/name,app/name,ignore=shutil.ignore_patterns('__pycache__'))
            (app/'runtime').symlink_to(ROOT/'runtime',target_is_directory=True);shutil.copy2(ROOT/'main.py',app/'main.py')
            (library/'Data').mkdir(parents=True);(library/'Data/FireRed.gba').symlink_to(ROOT/'Data/FireRed.gba')
            (library/'Data/FireRed.state').write_bytes((ROOT/'tests/fixtures/fire_red/clinic.state').read_bytes())
            (library/'Data/settings.json').write_text(json.dumps(dict(sound_enabled=False,autosave_enabled=True,autosave_seconds=5)))
            bind_installation(library,app,kind='profile',library=library)
            # Pin before start to keep the timing assertion about autosave.
            version=prepare_installation(app,library/'Sessions/installations')
            output=base/'watch-output.jsonl';stream=output.open('w')
            process=subprocess.Popen([str(ROOT/'runtime/python/cpython-3.12.16-macos-aarch64-none/bin/python3'),'-I','-B',str(app/'main.py'),'--watch','--root',str(library)],stdout=stream,stderr=subprocess.PIPE,text=True)
            try:
                deadline=time.monotonic()+12
                while '\n' not in output.read_text() and time.monotonic()<deadline and process.poll() is None:time.sleep(.02)
                line=output.read_text().splitlines()[0];self.assertTrue(json.loads(line)['ready'])
                checkpoint=library/'Data/FireRed.state';before=checkpoint.stat().st_mtime_ns
                # save_metadata is imported lazily on first autosave.
                (app/'src/pokemon_red/save_metadata.py').write_text('raise RuntimeError("mutable installation was imported")\n')
                deadline=time.monotonic()+9
                while checkpoint.stat().st_mtime_ns==before and time.monotonic()<deadline and process.poll() is None:time.sleep(.03)
                self.assertIsNone(process.poll());self.assertNotEqual(checkpoint.stat().st_mtime_ns,before)
                self.assertEqual((version.root/'src/pokemon_red/save_metadata.py').read_bytes(),(ROOT/'src/pokemon_red/save_metadata.py').read_bytes())
            finally:
                if process.poll() is None:process.terminate()
                try:out,error=process.communicate(timeout=5)
                except subprocess.TimeoutExpired:process.kill();out,error=process.communicate()
                stream.close()
            self.assertEqual(process.returncode,0,error)
