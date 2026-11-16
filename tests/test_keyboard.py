"""Regression tests for actual Tk Aqua packed keycodes, without OS input hooks."""
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import Mock
from concurrent.futures import Future

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from pokemon_red.keyboard import COMMAND_MASK, event_key
from pokemon_red.gui import Monitor
from pokemon_red.settings import Settings


def event(virtual, character="", *, keysym="", modifiers=0, state=0, widget=None):
    return SimpleNamespace(keycode=(virtual << 24) | (modifiers << 22) | (ord(character) if character else 0),
                           keysym=keysym or character, state=state, widget=widget)


class KeyboardTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "Data").mkdir()
        self.settings = Settings(self.root)
        self.monitor = Monitor.__new__(Monitor)
        self.monitor.settings = self.settings
        self.monitor.window = Mock()
        self.monitor.canvas=Mock();self.monitor.closed=False;self.monitor.paused=False
        self.monitor.safety_notice=None;self.monitor.render=Mock();self.monitor.model=None;self.monitor.status={};self.monitor.pending_start=False;self.monitor.pending_takeover=0;self.monitor.callbacks=[]
        self.monitor.operation=SimpleNamespace(active=False);self.monitor.automation=SimpleNamespace(running=False)
        self.monitor.diagnostics=Mock();self.monitor.command=Mock();self.monitor.update_panel=Mock()
        self.monitor.runtime=Mock();self.monitor.runtime.take_control.return_value=1
        future=Future();future.set_result(None);self.monitor.runtime.submit.return_value=future
        self.monitor.keys = set()
        self.widget = SimpleNamespace(winfo_toplevel=lambda: self.monitor.window)

    def tearDown(self):
        self.temporary.cleanup()

    def test_layouts_do_not_change_physical_binding(self):
        for virtual, chars, expected in ((7, "xXчЧχ", "x"), (6, "zZяЯw", "z"),
                                          (12, "qQйЙa", "q"), (13, "wWцЦz", "w"), (0, "aAфФq", "a")):
            for character in chars:
                with self.subTest(virtual=virtual, character=character):
                    self.assertEqual(event_key(event(virtual, character)), expected)

    def test_release_after_layout_and_modifier_change_unsets_button(self):
        self.monitor.key_down(event(7, "Ч", keysym="Cyrillic_CHE", modifiers=1, widget=self.widget))
        self.assertEqual(self.monitor.keys, {"A"})
        self.monitor.key_up(event(7, "x", widget=self.widget))
        self.assertEqual(self.monitor.keys, set())

    def test_remapping_in_russian_persists_as_physical_key(self):
        self.settings.bind("A", event_key(event(8, "с", keysym="Cyrillic_es")))
        self.monitor.settings = Settings(self.root)
        self.assertEqual(self.monitor.settings["bindings"]["A"], ["c", "e"])
        self.monitor.key_down(event(8, "c", widget=self.widget))
        self.assertEqual(self.monitor.keys, {"A"})
        with self.assertRaises(ValueError):
            self.settings.bind("B", event_key(event(8, "C", modifiers=1)))

    def test_arrows_shift_and_synthetic_text(self):
        self.assertEqual(event_key(event(126, keysym="Up")), "Up")
        self.assertEqual(event_key(event(60, keysym="Shift_R")), "Shift_R")
        self.assertIsNone(event_key(event(255, "ч")))
        self.monitor.key_down(event(255, "ч", widget=self.widget))
        self.assertFalse(self.monitor.keys)

    def test_command_s_works_in_russian_and_does_not_press_game_button(self):
        self.settings.unbind("DOWN", 1)
        self.settings.bind("A", "s")
        calls = []
        self.monitor.save = lambda **kwargs: calls.append(kwargs)
        press = event(1, "ы", keysym="Cyrillic_yeru", state=COMMAND_MASK, widget=self.widget)
        self.monitor.key_down(press)
        self.monitor.shortcut_down(press)
        self.assertFalse(self.monitor.keys)
        self.assertEqual(calls, [{"manual": True}])

    def test_typing_in_trainer_panel_does_not_control_game(self):
        panel_widget = SimpleNamespace(winfo_toplevel=object)
        self.monitor.key_down(event(7, "ч", widget=panel_widget))
        self.assertFalse(self.monitor.keys)

    def test_focus_round_trip_keeps_running_and_accepts_keyboard(self):
        monitor = self.monitor
        monitor.closed = False
        monitor.paused = False
        monitor.settings.set("speed", 2)
        monitor.settings.set('auto_focus_game',True)
        monitor.window = Mock()
        monitor.window.after_idle.side_effect = lambda callback: callback()
        monitor.window.focus_get.return_value = None
        monitor.canvas = Mock()
        monitor.save_if_changed = Mock()
        monitor.key_down(event(7, "x", widget=self.widget))
        self.assertEqual(monitor.keys, {"A"})
        monitor.focus_out(None)
        self.assertFalse(monitor.paused)
        self.assertEqual(monitor.settings["speed"], 2)
        self.assertFalse(monitor.keys)
        monitor.save_if_changed.assert_called_once_with()
        monitor.focus_in(SimpleNamespace(widget=self.widget))
        monitor.canvas.focus_set.assert_called_once_with()
        monitor.window.focus_get.return_value = monitor.canvas
        monitor.key_down(event(7, "ч", widget=self.widget))
        self.assertEqual(monitor.keys, {"A"})
        self.assertFalse(monitor.paused)

    def test_digit_speed_controls_are_physical_and_manual_pause_resumes(self):
        monitor = self.monitor
        monitor.paused = False
        monitor.update_panel = Mock()
        monitor.save_if_changed = Mock()
        monitor.automation = Mock(running=False)
        for virtual, character, speed in ((0x12, "1", 1), (0x13, '"', 2), (0x14, "№", 3), (0x15, "$", 4),
                                           (0x17, "%", 6), (0x16, ":", 8), (0x1A, "?", 12),
                                           (0x1C, "*", 16), (0x19, "(", 20)):
            monitor.key_down(event(virtual, character, widget=self.widget))
            self.assertFalse(monitor.paused)
            self.assertEqual(monitor.settings["speed"], speed)
            self.assertEqual(Settings(self.root)["speed"], speed)
        monitor.automation.stop.assert_not_called()
        monitor.key_down(event(0x1D, "0", widget=self.widget))
        self.assertTrue(monitor.paused)
        monitor.command.assert_any_call('pause',True)
        monitor.key_down(event(0x12, "1", widget=self.widget))
        self.assertFalse(monitor.paused)
        self.assertEqual(monitor.settings["speed"], 1)
        for key in "0123456789":
            with self.assertRaises(ValueError):
                monitor.settings.bind("A", key)

    def test_unsupported_speeds_are_rejected_before_changing_session(self):
        for value in (-1, float('nan'), float('inf'), float('-inf'), True, '8', None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.monitor.set_speed(value)

    def test_automatic_focus_can_be_disabled_without_pausing_or_stopping_bot(self):
        monitor=self.monitor;monitor.closed=False;monitor.paused=False;monitor.window=Mock();monitor.canvas=Mock()
        monitor.automation=Mock(running=True);monitor.save_if_changed=Mock()
        monitor.window.after_idle.side_effect=lambda callback:callback()
        monitor.window.focus_get.return_value=None
        monitor.settings.set('auto_focus_game',False)
        monitor.focus_out(None);monitor.focus_in(SimpleNamespace(widget=self.widget))
        monitor.canvas.focus_set.assert_not_called();monitor.automation.stop.assert_not_called();self.assertFalse(monitor.paused)

    def test_real_native_key_fallback_when_tk_has_no_physical_byte(self):
        monitor=self.monitor;monitor.input=Mock();monitor.input.current_keycode.return_value=7
        press=event(255,'ч',widget=self.widget)
        press.time=123
        monitor.key_down(press)
        self.assertEqual(monitor.keys,{'A'})
        monitor.input.current_keycode.assert_called_with(True)
        press.type='3';monitor.key_up(press)
        self.assertFalse(monitor.keys)
        monitor.input.current_keycode.assert_called_with(False)

    def test_synthetic_text_does_not_use_a_stale_native_event(self):
        monitor=self.monitor;monitor.input=Mock();monitor.input.current_keycode.return_value=7
        press=event(255,'ч',widget=self.widget);press.send_event=True
        monitor.key_down(press)
        self.assertFalse(monitor.keys);monitor.input.current_keycode.assert_not_called()

    def test_pause_then_recover_resumes_manual_game_at_one_x(self):
        monitor=self.monitor;monitor.closed=False;monitor.paused=True;monitor.window=Mock();monitor.canvas=Mock()
        monitor.game=Mock(frame=100);monitor.diagnostics=Mock();monitor.update_panel=Mock()
        monitor.settings.set('speed',8);monitor.automation=Mock(running=True)
        monitor.automation.stop.side_effect=lambda:setattr(monitor.automation,'running',False)
        monitor.keys={'UP'}
        monitor.recover_input()
        monitor.runtime.take_control.assert_called_once_with();monitor.command.assert_any_call('recover_input')
        self.assertFalse(monitor.keys);monitor.game.advance.assert_not_called()
        monitor.paused=False;monitor.automation=SimpleNamespace(running=False)
        monitor.key_down(event(126,keysym='Up',widget=self.widget))
        self.assertEqual(monitor.keys,{'UP'})

    def test_takeover_key_is_consumed_until_release_and_next_press_controls_game(self):
        monitor=self.monitor;monitor.automation=SimpleNamespace(running=True)
        press=event(7,'ч',widget=self.widget)
        monitor.key_down(press)
        monitor.runtime.take_control.assert_called_once_with()
        monitor.command.assert_not_called();self.assertFalse(monitor.keys)
        monitor.automation.running=False;monitor.pending_takeover=0
        monitor.key_down(press);monitor.command.assert_not_called()
        monitor.key_up(press);monitor.key_down(press)
        monitor.command.assert_called_once_with('manual','A',True)

    def test_unbound_key_speed_command_and_space_all_reclaim_without_actions(self):
        for virtual,char in ((8,'c'),(0x12,'1'),(1,'s'),(0x31,' '),(0x38,'')):
            with self.subTest(virtual=virtual):
                monitor=self.monitor;monitor._reclaim_keys=set();monitor.pending_takeover=0
                monitor.automation=SimpleNamespace(running=True);monitor.runtime.take_control.reset_mock();monitor.command.reset_mock()
                press=event(virtual,char,state=COMMAND_MASK if virtual==1 else 0,widget=self.widget)
                if virtual==0x31:monitor.toggle_pause(press)
                else:monitor.key_down(press)
                monitor.runtime.take_control.assert_called_once_with();monitor.command.assert_not_called()

    def test_pending_start_and_external_operation_can_be_revoked_by_unbound_key(self):
        monitor=self.monitor
        for operation in (False,True):
            monitor.pending_takeover=0;monitor._reclaim_keys=set();monitor.runtime.take_control.reset_mock()
            monitor.pending_start=not operation;monitor.operation.active=operation
            monitor.key_down(event(8,'c',widget=self.widget))
            monitor.runtime.take_control.assert_called_once_with();monitor.command.assert_not_called()

    def test_escape_stops_bot_and_pauses(self):
        monitor = self.monitor
        monitor.automation = Mock(running=True)
        monitor.update_panel = Mock()
        monitor.pause = Mock(return_value="break")
        self.assertEqual(monitor.emergency_stop(), "break")
        monitor.runtime.take_control.assert_called_once_with(pause=True)
        self.assertTrue(monitor.paused)

    def test_f9_returns_control_without_pausing_game(self):
        monitor = self.monitor
        monitor.automation = Mock(running=True)
        monitor.update_panel = Mock()
        monitor.paused = False
        self.assertEqual(monitor.shortcut_down(event(0x65, keysym="F9", widget=self.widget)), "break")
        monitor.runtime.take_control.assert_called_once_with()
        self.assertFalse(monitor.paused)


if __name__ == "__main__":
    unittest.main()
