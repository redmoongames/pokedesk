"""Integration checks with the local ROM and disposable, fresh save data."""
from pathlib import Path
import shutil
import hashlib
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from pokemon_red import Game, read_state
from pokemon_red.slots import Slots
from pokemon_red.settings import Settings


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="Pokemon session ")
        self.root = Path(self.temporary.name)
        (self.root / "Data").mkdir()
        (self.root / "native").symlink_to(ROOT / "native", target_is_directory=True)
        (self.root / "vendor").symlink_to(ROOT / "vendor", target_is_directory=True)
        shutil.copy2(ROOT / "Data/FireRed.gba", self.root / "Data/FireRed.gba")
        with Game(self.root, resume=False) as game:
            game.advance(120)
            game.save()

    def tearDown(self):
        self.temporary.cleanup()

    def test_fresh_session_has_no_previous_player(self):
        with Game(self.root) as game:
            state = read_state(game)
            self.assertFalse(state["ready"])
            self.assertIsNone(state["player"])
            self.assertEqual(state["party"], [])
            self.assertEqual(state["frame"], 120)

    def test_emulator_produces_stereo_audio_and_clears_stale_samples(self):
        import array
        with Game(self.root) as game:
            chunks = []
            for _ in range(120):
                game.advance(5)
                chunks.append(game.read_audio())
            samples = array.array("h", b"".join(chunks))
            self.assertGreater(len(samples), 32000)
            self.assertEqual(len(samples) % 2, 0)
            self.assertGreater(max(abs(sample) for sample in samples), 100)
            self.assertGreaterEqual(game.audio_rate, 32768)
            game.advance(2)
            game.clear_audio()
            self.assertEqual(game.read_audio(), b"")

    def test_input_checkpoint_and_reload(self):
        with Game(self.root) as game:
            initial = read_state(game)
            self.assertFalse(initial["in_battle"])
            game.advance(60)
            game.press("START", frames=3)
            game.advance(180)
            game.press("START", frames=3)
            game.advance(90)
            game.press("A", frames=3)
            game.advance(90)
            anchor = self.root / "anchor"
            game.save_to(anchor)
            game.press("START", frames=3)
            game.advance(390)
            moved = read_state(game)
            with Game(self.root) as control:
                control.load_state(anchor / "FireRed.state")
                control.advance(394)
                self.assertNotEqual(hashlib.sha256(game.rgb()).digest(), hashlib.sha256(control.rgb()).digest())
            self.assertEqual(len(game.rgb()), 240 * 160 * 3)
            self.assertGreater(len(set(game.rgb())), 5)
            game.save()
        with Game(self.root) as restored:
            reloaded = read_state(restored)
            self.assertEqual(moved, reloaded)
        self.assertEqual((self.root / "Data/FireRed.sav").stat().st_size, 131072)

    def test_wrong_rom_is_rejected(self):
        path = self.root / "Data/FireRed.gba"
        data = bytearray(path.read_bytes())
        data[0xAC] ^= 1
        path.write_bytes(data)
        with self.assertRaisesRegex(ValueError, "Rev 1"):
            Game(self.root)

    def test_named_slots_overwrite_history_and_fresh_start(self):
        slots = Slots(self.root)
        with Game(self.root) as game:
            game.advance(1)
            initial = read_state(game)
            slot_id = slots.save(game, "Начало игры")
            game.advance(120)
            slots.save(game, "Начало игры", slot_id)
            self.assertEqual(len(slots.list()), 1)
            self.assertEqual(len(slots.backups()), 1)
            backup = slots.backup(game, "Перед новой игрой")
            with slots.prepare_load(slot_id) as restored:
                self.assertEqual(read_state(restored)["frame"], initial["frame"] + 121)
            with Game(self.root, resume=False) as fresh:
                fresh.advance(120)
                self.assertIsNone(read_state(fresh)["player"])
                fresh.save()
            # Starting fresh must not damage a named slot or the archived session.
            with slots.prepare_backup(backup) as restored:
                self.assertEqual(read_state(restored)["frame"], initial["frame"] + 121)
            self.assertEqual(len(slots.list()), 1)
            self.assertEqual((self.root / "Data/FireRed.sav").read_bytes(), b"\xff" * 131072)

    def test_failed_slot_load_preserves_running_session(self):
        slots = Slots(self.root)
        with Game(self.root) as game:
            slot_id = slots.save(game, "Проверка")
            initial = read_state(game)
            (slots.get(slot_id)["directory"] / "FireRed.state").write_bytes(b"broken")
            with self.assertRaises(RuntimeError):
                slots.prepare_load(slot_id)
            self.assertEqual(read_state(game), initial)

    def test_bindings_persist_and_reject_conflicts(self):
        settings = Settings(self.root)
        settings.bind("A", "c")
        settings.set("speed", 2)
        restored = Settings(self.root)
        self.assertEqual(restored["bindings"]["A"], ["c", "e"])
        self.assertEqual(restored["speed"], 2)
        with self.assertRaises(ValueError):
            restored.bind("B", "c")
        with self.assertRaises(ValueError):
            restored.bind("B", "F1")
        restored.reset_bindings()
        self.assertEqual(Settings(self.root)["bindings"]["A"], ["x", "e"])

    def test_invalid_state_is_rejected_without_overwriting_it(self):
        path = self.root / "Data/FireRed.state"
        path.write_bytes(b"not a savestate")
        with self.assertRaises(RuntimeError):
            Game(self.root)
        self.assertEqual(path.read_bytes(), b"not a savestate")

    def test_interrupted_save_keeps_last_complete_checkpoint(self):
        state = self.root / "Data/FireRed.state"
        ordinary = self.root / "Data/FireRed.sav"
        before_state, before_save = state.read_bytes(), ordinary.read_bytes()
        from pokemon_red.persistence import sync_file
        with Game(self.root) as game:
            game.advance(60)
            def incomplete(file, **options):
                path = Path(file.name)
                if path.parent.resolve() == (self.root / 'Data').resolve() and path.name.startswith('FireRed.state.'):
                    raise OSError('interrupted checkpoint staging')
                return sync_file(file, **options)
            with patch('pokemon_red.persistence.sync_file', side_effect=incomplete):
                with self.assertRaises(OSError):
                    game.save()
        self.assertEqual(state.read_bytes(), before_state)
        self.assertEqual(ordinary.read_bytes(), before_save)
        self.assertFalse(list((self.root / "Data").glob("*.tmp")))
        with Game(self.root) as restored:
            self.assertEqual(restored.frame, 120)

    def test_corrupt_or_missing_checkpoint_recovers_last_good_autosave(self):
        with Game(self.root) as game:
            game.advance(60)
            game.save()
            game.advance(60)
            game.save()
        checkpoint = self.root / "Data/FireRed.state"
        checkpoint.write_bytes(b"damaged during power loss")
        with Game(self.root) as restored:
            self.assertEqual(restored.frame, 180)
            self.assertIsNotNone(restored.recovered_from)
        self.assertEqual(checkpoint.read_bytes(), b"damaged during power loss")
        checkpoint.unlink()
        with Game(self.root) as restored:
            self.assertEqual(restored.frame, 180)
            self.assertIsNotNone(restored.recovered_from)
        self.assertEqual(len(Slots(self.root).backups()), 2)

    def test_autosave_history_is_bounded_and_manually_restorable(self):
        with Game(self.root) as game:
            for _ in range(12):
                game.advance(1)
                game.save()
        history = Slots(self.root).backups()
        self.assertEqual(len(history), 12)  # Time-based history retains rapid commits too.
        with Slots(self.root).prepare_backup(history[0]["directory"]) as restored:
            self.assertEqual(restored.frame, 132)  # previous checkpoint 131 + video refresh

    def test_autosave_survives_force_kill_without_shutdown_handler(self):
        checkpoint = self.root / "Data/FireRed.state"
        before = checkpoint.stat().st_mtime_ns
        with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
            process = subprocess.Popen([str(ROOT / "Run.command"), "--watch", "--root", str(self.root)],
                                       stdout=output, stderr=errors)
            def check_alive():
                if process.poll() is not None:
                    errors.seek(0)
                    self.fail(errors.read().decode())
            try:
                # A cold launch prepares and verifies the pinned installation
                # before --watch prints its first snapshot. Do not charge that
                # startup work to the five-second gameplay autosave interval.
                deadline = time.monotonic() + 60
                while not os.fstat(output.fileno()).st_size and time.monotonic() < deadline:
                    check_alive()
                    time.sleep(0.03)
                self.assertGreater(os.fstat(output.fileno()).st_size, 0, "Session startup did not finish")
                deadline = time.monotonic() + 8
                while checkpoint.stat().st_mtime_ns == before and time.monotonic() < deadline:
                    check_alive()
                    time.sleep(0.03)
                self.assertNotEqual(checkpoint.stat().st_mtime_ns, before,
                                    "Autosave did not publish within 8 seconds after session readiness")
                process.kill()  # SIGKILL cannot run finally/close handlers.
                process.wait(timeout=5)
                with Game(self.root) as restored:
                    self.assertGreater(restored.frame, 120)
                    self.assertIsNone(restored.recovered_from)
            finally:
                if process.poll() is None:
                    process.kill()
                process.communicate(timeout=5)

    def test_bot_subprocess_controls_this_exact_emulator_instance(self):
        from pokemon_red.automation import Automation
        from pokemon_red.engine import BUTTONS
        import json
        script = self.root / "live bot.py"
        script.write_text('''import json
def run(bot):
    before = bot.state()['frame']
    action = bot.press('START', frames=3, release_frames=2)
    bot.wait_frames(20)
    after = bot.state()['frame']
    (bot.project_dir / 'live-result.json').write_text(json.dumps([before, action, after]))
''')
        with Game(self.root) as game:
            handle = game.handle
            controller = Automation(self.root, snapshot=lambda: read_state(game),
                                    checkpoint=lambda name: name, set_speed=lambda speed: None,
                                    release=lambda: game.advance(0, 0))
            masks = []
            try:
                controller.start(script)
                deadline = time.monotonic() + 5
                while controller.running and time.monotonic() < deadline:
                    controller.poll()
                    for _ in range(8):
                        mask = controller.next_mask(0)
                        masks.append(mask)
                        game.advance(1, mask)
                        controller.after_frame(game.frame)
                    time.sleep(.002)
                self.assertFalse(controller.running, "Bot did not finish")
                self.assertEqual(controller.status, "finished", "\n".join(controller.logs))
                before, action, after = json.loads((self.root / "live-result.json").read_text())
                self.assertGreaterEqual(before, 120)
                self.assertGreater(after, before)
                self.assertEqual(action['end_frame'] - action['start_frame'], 5)
                self.assertEqual(masks.count(BUTTONS['START']), 3)
                self.assertEqual(game.handle, handle)
                self.assertGreaterEqual(game.frame, after)
            finally:
                controller.close()


if __name__ == "__main__":
    unittest.main()
