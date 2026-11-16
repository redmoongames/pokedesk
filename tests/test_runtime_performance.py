"""Event-driven commands and detached saves, using private data only."""
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from pokemon_red.automation import Automation, Request, Session
from pokemon_red.engine import BUTTONS, Game
from pokemon_red.file_writer import FileWriter
from pokemon_red.persistence import SaveSnapshot, publish_checkpoint


class FileWriterTests(unittest.TestCase):
    def test_pending_autosaves_coalesce_after_manual_jobs_without_reordering(self):
        gate = threading.Event()
        entered = threading.Event()
        calls = []
        writer = FileWriter()
        try:
            def block():
                entered.set()
                gate.wait(3)
                calls.append('first')
            first = writer.submit(block)
            self.assertTrue(entered.wait(1))
            old = writer.submit(lambda:calls.append('old'), coalesce='autosave')
            manual = writer.submit(lambda:calls.append('manual'))
            latest = writer.submit(lambda:calls.append('latest'), coalesce='autosave')
            self.assertTrue(old.cancelled())
            gate.set()
            latest.result(2)
            self.assertTrue(manual.done())
            self.assertEqual(calls, ['first', 'manual', 'latest'])
        finally:
            gate.set()
            writer.close()

    def test_failure_is_reported_and_later_explicit_save_can_succeed(self):
        wake = threading.Event()
        writer = FileWriter(wake.set)
        try:
            def broken():
                raise OSError('disk full')
            bad = writer.submit(broken)
            with self.assertRaisesRegex(OSError, 'disk full'):
                bad.result(2)
            self.assertTrue(wake.wait(1))
            good = writer.submit(lambda:42)
            self.assertEqual(good.result(2), 42)
        finally:
            writer.close()

    def test_queue_is_bounded_and_close_drains_accepted_jobs(self):
        gate = threading.Event()
        entered = threading.Event()
        writer = FileWriter(capacity=1)
        try:
            writer.submit(lambda:(entered.set(), gate.wait(3)))
            self.assertTrue(entered.wait(1))
            accepted = writer.submit(lambda:'written')
            with self.assertRaisesRegex(RuntimeError, 'заполнена'):
                writer.submit(lambda:None)
            gate.set()
            writer.close()
            self.assertEqual(accepted.result(), 'written')
            with self.assertRaises(RuntimeError):
                writer.submit(lambda:None)
        finally:
            gate.set()
            writer.close()


class CommandTests(unittest.TestCase):
    def controller(self, **kwargs):
        return Automation(ROOT, snapshot=Mock(side_effect=AssertionError('full decode not needed')),
                          checkpoint=lambda _:None, set_speed=lambda _:None, release=lambda:None,
                          **kwargs)

    def test_frame_commands_do_not_decode_full_state(self):
        import socket
        controller = self.controller(frame_reader=lambda:123)
        controller.session = Session(socket.socket())
        request = Request(controller.session, 'press', dict(button='A', frames=1))
        controller._dispatch(request)
        self.assertEqual(controller.action['start_frame'], 123)
        self.assertEqual(controller.next_mask(0), BUTTONS['A'])
        controller.snapshot.assert_not_called()
        controller.close()

    def test_cycle_event_ack_waits_for_sql_and_takeover_revokes_late_ack(self):
        import socket
        future=Future();controller=self.controller(event_sink=lambda *_:future)
        controller.session=Session(socket.socket())
        request=Request(controller.session,'event',dict(code='cycle_complete',message='complete'))
        controller._dispatch(request);controller.poll();self.assertFalse(request.done.is_set())
        controller.stop();self.assertTrue(request.response['cancelled'])
        future.set_result(None);controller.poll();self.assertTrue(request.response['cancelled']);controller.close()

    def test_checkpoint_reply_waits_for_durable_completion_and_is_revoked(self):
        import socket
        future = Future()
        controller = self.controller()
        controller.checkpoint = lambda _:future
        session = Session(socket.socket())
        controller.session = session
        request = Request(session, 'checkpoint', dict(name='before'))
        controller._dispatch(request)
        controller.poll()
        self.assertFalse(request.done.is_set())
        controller.stop()
        self.assertTrue(request.response['cancelled'])
        future.set_result('slot-id')
        controller.poll()
        self.assertTrue(request.response['cancelled'])
        controller.close()


class PrivateSessionTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='Pokemon runtime ')
        self.root = Path(self.temporary.name)
        (self.root / 'Data').mkdir()
        for name in ('native', 'vendor', 'runtime', 'Bots', 'src', 'assets'):
            (self.root / name).symlink_to(ROOT / name, target_is_directory=True)
        (self.root / 'Data/FireRed.gba').symlink_to(ROOT / 'Data/FireRed.gba')
        (self.root / 'Data/settings.json').write_text(json.dumps(dict(
            panel_on_start=False, sound_enabled=False, autosave_enabled=False, speed=8, scale=1)))
        with Game(self.root, resume=False) as game:
            game.advance(120)
            game.save()

    def tearDown(self):
        self.temporary.cleanup()


class NativeSaveTests(PrivateSessionTestCase):
    def test_block_read_matches_scalar_reads_for_gba_regions_and_boundaries(self):
        with Game(self.root) as game:
            for address, count in ((0x08000000, 257), (0x02000000, 601), (0x03000000, 127),
                                   (0x0203FFF0, 32), (0x03007FF0, 32)):
                with self.subTest(address=address):
                    self.assertEqual(game.read_bytes(address, count), bytes(game.read8(address+i) for i in range(count)))
            self.assertEqual(game.read_bytes(0, 0), b'')
            for address, count in ((0, -1), (0, True), (0, 1048577), (-1, 1), (0xFFFFFFFF, 2)):
                with self.assertRaises(ValueError):
                    game.read_bytes(address, count)

    def test_detached_snapshot_restores_capture_frame_after_core_closed(self):
        from pokemon_red.telemetry import read_state
        with Game(self.root) as game:
            before = read_state(game)
            snapshot = game.capture_save()
            game.advance(90, BUTTONS['A'])
            self.assertEqual(snapshot.frame, before['frame'])
        writer = FileWriter()
        try:
            writer.submit(lambda:publish_checkpoint(snapshot, self.root/'Data', 'test')).result(2)
        finally:
            writer.close()
        with Game(self.root) as restored:
            self.assertEqual(read_state(restored), before)

    def test_failed_native_capture_preserves_primary_checkpoint(self):
        path = self.root / 'Data/FireRed.state'
        before = path.read_bytes()
        with Game(self.root) as game:
            original = game.lib.pokemon_capture_state
            game.lib.pokemon_capture_state = lambda *_:0
            try:
                with self.assertRaises(OSError):
                    game.save()
            finally:
                game.lib.pokemon_capture_state = original
        self.assertEqual(path.read_bytes(), before)

    def test_worker_cannot_read_or_advance_owned_core(self):
        with Game(self.root) as game:
            failures = []
            def unsafe():
                for operation in (lambda:game.read_bytes(0x02000000, 4), game.capture_save,
                                  lambda:game.advance(1), game.close):
                    try:
                        operation()
                    except RuntimeError as error:
                        failures.append(str(error))
            worker = threading.Thread(target=unsafe)
            worker.start()
            worker.join()
            self.assertEqual(len(failures), 4)
            self.assertEqual(game.frame, 120)

    def run_gui_child(self, extra):
        code = '''from pathlib import Path
import sys, time, tkinter as tk
sys.path.insert(0, str(Path(sys.argv[1])/'src'))
from pokemon_red.gui import Monitor
from pokemon_red.engine_runtime import EngineRuntime
class Probe(EngineRuntime):
 def _dispatch(self,c,method,args):
  if method=='probe':return args[0](c)
  return super()._dispatch(c,method,args)
root=tk.Tk();root.withdraw()
m=Monitor(root,Path(sys.argv[2]),paused=True,runtime_factory=Probe)
while not m.ready:root.update();time.sleep(.001)
'''+extra+'''
root.after(15000,m.close)
root.mainloop()
'''
        return subprocess.Popen([str(ROOT/'runtime/python/cpython-3.12.16-macos-aarch64-none/bin/python3'),
            '-I', '-B', '-c', code, str(ROOT), str(self.root)], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    def wait_child_file(self, process, path, condition=lambda p:p.exists(), timeout=10):
        deadline = time.monotonic()+timeout
        while not condition(path) and time.monotonic()<deadline:
            if process.poll() is not None:
                self.fail(process.stderr.read().decode())
            time.sleep(.02)
        self.assertTrue(condition(path), str(path))

    def test_gui_background_autosave_survives_sigkill_without_close_handler(self):
        settings = json.loads((self.root/'Data/settings.json').read_text())
        settings.update(autosave_enabled=True, autosave_seconds=5)
        (self.root/'Data/settings.json').write_text(json.dumps(settings))
        path = self.root/'Data/FireRed.state'
        before = path.stat().st_mtime_ns
        process = self.run_gui_child('m.set_speed(8)')
        try:
            self.wait_child_file(process, path, lambda p:p.stat().st_mtime_ns != before)
            process.kill()
            process.wait(timeout=3)
            with Game(self.root) as restored:
                self.assertGreater(restored.frame, 120)
                self.assertIsNone(restored.recovered_from)
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=3)

    def test_sigkill_during_writer_staging_keeps_last_complete_primary_pair(self):
        state, sram = self.root/'Data/FireRed.state', self.root/'Data/FireRed.sav'
        before = state.read_bytes(), sram.read_bytes()
        process = self.run_gui_child('''import pokemon_red.persistence as persistence
original=persistence.sync_file
def blocked(file,**options):
    original(file,**options)
    path=Path(file.name)
    if path.parent.resolve()==(m.folder/'Data').resolve() and path.name.startswith('FireRed.state.'):
        (m.folder/'Data/staging.marker').write_text('staged, not committed')
        time.sleep(30)
persistence.sync_file=blocked
m.runtime.submit('probe',lambda c:c.game.advance(50)).result(3)
m.save(manual=True)
''')
        try:
            self.wait_child_file(process, self.root/'Data/staging.marker')
            process.kill()
            process.wait(timeout=3)
            self.assertEqual((state.read_bytes(), sram.read_bytes()), before)
            with Game(self.root) as restored:
                self.assertEqual(restored.frame, 120)
                self.assertIsNone(restored.recovered_from)
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=3)


class TickBudgetTests(unittest.TestCase):
    def test_guard_interrupts_before_next_button_and_only_executed_frames_are_spent(self):
        from pokemon_red.session_controller import SessionController as Monitor
        monitor = Monitor.__new__(Monitor)
        monitor.transport=SimpleNamespace(consume_interrupt=lambda _:False,after_frame=lambda _:None)
        monitor.closed=monitor.closing=monitor.session_transition=monitor.paused=False
        monitor.last_tick=100
        monitor.last_video=monitor.last_panel=monitor.last_export=100.01
        monitor.settings={'speed':8}
        monitor.budget=0
        monitor.keys=set()
        monitor.game=SimpleNamespace(frame=120)
        masks=[]
        def advance(frames,mask):
            masks.append(mask)
            monitor.game.frame+=frames
        monitor.game.advance=advance
        monitor.automation=SimpleNamespace(running=True,next_mask=lambda _:BUTTONS['A'],after_frame=Mock())
        monitor.critical_save_pending=lambda:False
        monitor.check_shiny_encounter=lambda:False
        monitor.check_training_decision=Mock(side_effect=[False,True])
        monitor.sync_audio=Mock()
        monitor.game.read_audio=lambda:b''
        monitor.playback=SimpleNamespace(handle=True,write=Mock())
        monitor.save_if_due=Mock()
        monitor.error=Mock()
        monitor.diagnostics=SimpleNamespace(measure=Mock())
        monitor.window=SimpleNamespace(after=Mock())
        with patch('pokemon_red.session_controller.time.monotonic',return_value=100.01):
            monitor.tick()
        monitor.error.assert_not_called()
        self.assertEqual(masks,[BUTTONS['A']])
        self.assertEqual(monitor.game.frame,121)
        self.assertAlmostEqual(monitor.budget, .01*59.7275*8-1)




if __name__ == '__main__':
    unittest.main()
