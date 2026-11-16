from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pokemon_red.session_controller import SessionController as Monitor


class AutosaveTimerTests(unittest.TestCase):
    def test_timer_uses_five_seconds_and_skips_unchanged_or_disabled_sessions(self):
        monitor = Monitor.__new__(Monitor)
        monitor.settings = {"autosave_enabled": True, "autosave_seconds": 5}
        monitor.game = SimpleNamespace(frame=300)
        monitor.last_save = 100
        monitor.last_saved_frame = 120
        monitor.save_failed = False
        monitor.save = Mock()
        monitor.save_if_due(104.9)
        monitor.save.assert_not_called()
        monitor.save_if_due(105)
        monitor.save.assert_called_once_with()
        monitor.save.reset_mock()
        monitor.last_saved_frame = 300
        monitor.save_if_due(110)
        monitor.save.assert_not_called()
        monitor.last_saved_frame = 120
        monitor.settings["autosave_enabled"] = False
        monitor.save_if_due(110)
        monitor.save.assert_not_called()
        monitor.settings["autosave_enabled"] = True
        monitor.save_failed = True
        monitor.save_if_due(110)
        monitor.save.assert_not_called()

    def test_pausing_writes_dirty_progress_immediately(self):
        monitor = Monitor.__new__(Monitor)
        monitor.settings = {"autosave_enabled": True}
        monitor.game = SimpleNamespace(frame=300)
        monitor.last_saved_frame = 120
        monitor.save_failed = False
        monitor.keys = {"A"}
        monitor.save = Mock()
        monitor.update_panel = Mock()
        monitor.pause()
        self.assertTrue(monitor.paused)
        self.assertFalse(monitor.keys)
        monitor.save.assert_called_once_with()
