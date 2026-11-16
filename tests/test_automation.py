"""Real subprocess + loopback SDK tests; emulator callbacks remain on this thread."""
from pathlib import Path
import json
import queue
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from pokemon_red.automation import Automation, Request
from pokemon_red.engine import BUTTONS


class AutomationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="Pokemon bot ")
        self.root = Path(self.temporary.name)
        self.frame = 100
        self.speed = 1
        self.paused = False
        self.masks = []
        self.releases = []
        self.checkpoints = []
        self.controller = Automation(self.root, snapshot=self.snapshot, checkpoint=self.checkpoint,
                                     set_speed=self.change_speed, release=lambda: self.releases.append(0))

    def tearDown(self):
        self.controller.close()
        self.temporary.cleanup()

    def snapshot(self):
        return {"frame": self.frame, "money": 3210, "party": [{"level": 7, "hp": 22}],
                "session": {"paused": self.paused, "speed": self.speed}}

    def test_handoff_is_normal_completion_preserves_reason_and_releases_input(self):
        events=[]
        self.controller.event_sink=lambda code,message,details:events.append((code,message,details))
        self.script("def run(bot):\n    bot.handoff('move_choice_required', 'Выбери замену TACKLE', pokemon='BULBASAUR', move='POISONPOWDER')\n    bot.press('A')\n")
        self.drive(lambda:not self.controller.running)
        self.assertEqual(self.controller.status,'attention')
        self.assertEqual(self.controller.reason,'Выбери замену TACKLE')
        self.assertFalse(any(self.masks))
        self.assertTrue(self.releases)
        event=next(e for e in events if e[0]=='move_choice_required')
        self.assertEqual(event[2]['pokemon'],'BULBASAUR')

    def checkpoint(self, name):
        self.checkpoints.append(name)
        return "slot-123"

    def test_exception_is_structured_and_terminal_event_retains_session_and_reason(self):
        events=[];self.controller.event_sink=lambda *a:events.append(a)
        self.script("def run(bot):\n    raise KeyError('missing reason')\n")
        self.drive(lambda:not self.controller.running)
        event=next(e for e in events if e[0]=='script_error');detail=event[2]
        self.assertEqual(detail['error_type'],'KeyError');self.assertEqual(detail['outcome'],'failed');self.assertIn('missing reason',event[1]);self.assertIn('raise KeyError',detail['traceback']);self.assertTrue(detail['log_file']);self.assertEqual(detail['automation_session_id'],next(e[2]['automation_session_id'] for e in events if e[0]=='script_started'));self.assertTrue(self.releases)

    def change_speed(self, speed):
        self.paused = speed == 0
        if speed:
            self.speed = speed

    def script(self, source):
        path = self.root / "custom bot.py"
        path.write_text(source)
        self.controller.start(path)

    def drive(self, until, *, batch=8, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.controller.poll()
            if until():
                return
            if not self.paused:
                for _ in range(batch):
                    mask = self.controller.next_mask(BUTTONS["B"])
                    if self.controller.running:
                        self.masks.append(mask)
                    self.frame += 1
                    self.controller.after_frame(self.frame)
            time.sleep(0.002)
        self.fail("Bot test timed out: " + repr(self.controller.info()) + "\n" + "\n".join(self.controller.logs))

    def test_live_state_exact_button_frames_and_normal_completion(self):
        self.script('''from pathlib import Path
import json
def run(bot):
    state = bot.state()
    assert state['money'] == 3210
    bot.log('LIVE_STATE_OK')
    press = bot.press('RIGHT+A', frames=7, release_frames=3)
    wait = bot.wait_frames(11)
    slot = bot.checkpoint('Перед тестом')
    bot.set_speed(8)
    Path(bot.project_dir / 'result.json').write_text(json.dumps([press, wait, slot]))
''')
        self.drive(lambda: not self.controller.running)
        self.assertEqual(self.controller.status, "finished")
        press, wait, slot = json.loads((self.root / "result.json").read_text())
        self.assertEqual(press["end_frame"] - press["start_frame"], 10)
        self.assertEqual(wait["end_frame"] - wait["start_frame"], 11)
        self.assertEqual(self.masks.count(BUTTONS["RIGHT"] | BUTTONS["A"]), 7)
        self.assertNotIn(BUTTONS["B"], self.masks)
        self.assertEqual(slot, "slot-123")
        self.assertEqual(self.speed, 8)
        self.assertEqual(self.checkpoints, ["Перед тестом"])
        self.assertIn("LIVE_STATE_OK", "\n".join(self.controller.logs))

    def test_all_speed_values_and_pause_work_without_releasing_bot_ownership(self):
        self.script("def run(bot):\n    for speed in (0.5, 1.5, 2.75, 3, 4, 6, 8, 10, 12, 16, 0, 1):\n        bot.set_speed(speed)\n        state = bot.state()\n        assert state['session']['paused'] == (speed == 0)\n        if speed:\n            assert state['session']['speed'] == speed\n    for invalid in (-1, float('nan'), float('inf'), True, '8'):\n        try:\n            bot.set_speed(invalid)\n        except RuntimeError:\n            pass\n        else:\n            raise AssertionError('invalid speed accepted')\n    bot.wait_frames(3)\n")
        self.drive(lambda: not self.controller.running)
        self.assertEqual(self.controller.status, 'finished')
        self.assertEqual(self.speed, 1)
        self.assertFalse(self.paused)

    def test_takeover_revokes_pending_and_late_input_without_waiting(self):
        self.script("def run(bot):\n    bot.press('RIGHT', frames=3600)\n    bot.press('LEFT', frames=3600)\n")
        self.drive(lambda: self.controller.action is not None)
        session = self.controller.session
        pending = self.controller.action["request"]
        start = time.monotonic()
        self.controller.stop()
        self.assertLess(time.monotonic() - start, 0.1)
        self.assertFalse(self.controller.running)
        self.assertEqual(self.controller.next_mask(BUTTONS["A"]), BUTTONS["A"])
        self.assertTrue(pending.done.is_set())
        self.assertTrue(pending.response["cancelled"])
        late = Request(session, "press", {"button": "LEFT", "frames": 50})
        self.controller.requests.put(late)
        self.controller.poll()
        self.assertTrue(late.response["cancelled"])
        self.assertIsNone(self.controller.action)
        self.assertTrue(self.releases)

    def test_pausing_freezes_frame_command_and_resume_finishes_it(self):
        self.script("def run(bot):\n    bot.wait_frames(30)\n")
        self.drive(lambda: self.controller.action is not None)
        remaining = self.controller.info()["action"]["frames_left"]
        frame = self.frame
        self.paused = True
        for _ in range(20):
            self.controller.poll()
            time.sleep(.002)
        self.assertEqual(self.frame, frame)
        self.assertEqual(self.controller.info()["action"]["frames_left"], remaining)
        self.assertTrue(self.controller.running)
        self.paused = False
        self.drive(lambda: not self.controller.running)
        self.assertEqual(self.controller.status, "finished")

    def test_force_killed_script_releases_held_input(self):
        self.script("def run(bot):\n    bot.press('UP', frames=3600)\n")
        self.drive(lambda: self.controller.action is not None)
        self.controller.process.kill()
        self.drive(lambda: not self.controller.running)
        self.assertEqual(self.controller.status, "error")
        self.assertEqual(self.controller.next_mask(0), 0)
        self.assertIsNone(self.controller.action)
        self.assertTrue(self.releases)

    def test_noncooperating_script_cannot_keep_ownership(self):
        self.script('''import signal
def run(bot):
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    bot.log('BUSY_READY')
    while True:
        pass
''')
        self.drive(lambda: any("BUSY_READY" in line for line in self.controller.logs))
        process = self.controller.process
        self.controller.stop()
        self.assertFalse(self.controller.running)
        self.assertEqual(self.controller.next_mask(BUTTONS["DOWN"]), BUTTONS["DOWN"])
        self.drive(lambda: process.poll() is not None)

    def test_invalid_commands_do_not_press_any_button(self):
        self.script('''def run(bot):
    for button, frames in [('INVALID', 2), ('A', -1), ('A', True), ('A', 3601)]:
        try:
            bot.press(button, frames)
        except RuntimeError:
            pass
        else:
            raise AssertionError('Invalid request accepted')
    bot.log('REJECTED_OK')
''')
        self.drive(lambda: not self.controller.running)
        self.assertEqual(self.controller.status, "finished")
        self.assertFalse(any(self.masks))

    def test_script_exception_returns_manual_control(self):
        self.script("def run(bot):\n    raise RuntimeError('INTENTIONAL_TEST_FAILURE')\n")
        self.drive(lambda: not self.controller.running)
        for _ in range(10):
            self.controller.poll()
            time.sleep(.005)
        self.assertEqual(self.controller.status, "error")
        self.assertIn("INTENTIONAL_TEST_FAILURE", "\n".join(self.controller.logs))


if __name__ == "__main__":
    unittest.main()
