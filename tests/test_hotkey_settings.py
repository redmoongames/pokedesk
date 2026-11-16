"""Portable key migration, alias lifetimes and editable digit speeds."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from pokemon_red.settings import Settings, DEFAULTS, LEGACY_BINDINGS, PREVIOUS_BINDINGS
from pokemon_red.hotkey_settings import HotkeySettings
import test_keyboard
from test_keyboard import event


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'Data').mkdir()
        self.settings = Settings(self.root)

    def load(self, value):
        (self.root / 'Data/settings.json').write_text(json.dumps(value))
        return Settings(self.root)

    def test_untouched_legacy_upgrades_without_losing_other_preferences(self):
        s = self.load(dict(bindings=LEGACY_BINDINGS, speed=2.75, volume=37, scale=2))
        self.assertEqual(s['bindings'], DEFAULTS['bindings'])
        self.assertEqual(s['speed'], 2.75)
        self.assertEqual(s['volume'], 37)
        self.assertEqual(s['scale'], 2)
        s.save()
        self.assertEqual(Settings(self.root).values, s.values)

    def test_previous_default_preset_gains_qe_without_shoulder_conflicts(self):
        s=self.load(dict(bindings=PREVIOUS_BINDINGS,volume=37))
        self.assertEqual(s['bindings']['B'],['z','q']);self.assertEqual(s['bindings']['A'],['x','e'])
        self.assertEqual(s['bindings']['L'],['bracketleft']);self.assertEqual(s['bindings']['R'],['bracketright'])
        self.assertEqual(s['volume'],37)

    def test_custom_legacy_assignments_are_not_overwritten(self):
        legacy = dict(LEGACY_BINDINGS, A='c')
        s = self.load(dict(bindings=legacy))
        self.assertEqual(s['bindings'], {b: [k] for b, k in legacy.items()})
        s.bind('A', 'v', 1)
        self.assertEqual(Settings(self.root)['bindings']['A'], ['c', 'v'])

    def test_two_slots_can_be_rebound_removed_and_disabled(self):
        s = self.settings
        s.bind('A', 'c', 1)
        self.assertEqual(Settings(self.root)['bindings']['A'], ['x', 'c'])
        s.bind('A', 'v', 1)
        s.unbind('A', 0)
        self.assertEqual(s['bindings']['A'], ['v'])
        s.unbind('A', 0)
        self.assertEqual(Settings(self.root)['bindings']['A'], [])
        s.bind('A', 'c', 1)
        self.assertEqual(s['bindings']['A'], ['c'])
        s.reset_bindings()
        self.assertEqual(Settings(self.root)['bindings'], DEFAULTS['bindings'])

    def test_invalid_conflicts_never_apply_or_persist_partial_bindings(self):
        s = self.settings
        before = deepcopy(s.values)
        s.save()
        for key, slot in [('w', 1), ('W', 1), ('x', 1), ('F9', 1), ('1', 1), ('', 1), ('c', 2), ('c', True), (None, 0)]:
            with self.subTest(key=key, slot=slot), self.assertRaises(ValueError):
                s.bind('A', key, slot)
            self.assertEqual(s.values, before)
            self.assertEqual(Settings(self.root).values, before)

    def test_speed_mapping_accepts_pause_fractional_and_large_rates(self):
        speeds = dict(DEFAULTS['speed_bindings'], **{'0': 2.75, '1': 0, '9': 32})
        self.settings.set('speed_bindings', speeds)
        self.assertEqual(Settings(self.root)['speed_bindings'], speeds)
        speeds['9'] = 4  # Incoming dictionaries must not be mutable aliases.
        self.assertEqual(self.settings['speed_bindings']['9'], 32)
        self.settings.reset_speed_bindings()
        self.assertEqual(Settings(self.root)['speed_bindings'], DEFAULTS['speed_bindings'])

    def test_corrupt_speed_map_falls_back_as_a_whole(self):
        for invalid in ({'1': 3}, dict(DEFAULTS['speed_bindings'], **{'4': -1}),
                        dict(DEFAULTS['speed_bindings'], **{'9': float('nan')})):
            with self.subTest(value=invalid):
                self.assertEqual(self.load({'speed_bindings': invalid})['speed_bindings'], DEFAULTS['speed_bindings'])
                before = deepcopy(self.settings.values)
                with self.assertRaises(ValueError):
                    self.settings.set('speed_bindings', invalid)
                self.assertEqual(self.settings.values, before)


class AliasInputTests(unittest.TestCase):
    setUp = test_keyboard.KeyboardTests.setUp
    tearDown = test_keyboard.KeyboardTests.tearDown
    def test_releasing_either_alias_keeps_other_held(self):
        for first, second in ((126, 13), (13, 126)):
            with self.subTest(first=first):
                m = self.monitor
                m.command.reset_mock()
                m.key_down(event(first, widget=self.widget))
                m.key_down(event(second, widget=self.widget))
                m.key_down(event(second, widget=self.widget))  # OS repeat
                self.assertEqual(m.keys, {'UP'})
                m.command.assert_called_once_with('manual', 'UP', True)
                m.key_up(event(first, widget=self.widget))
                self.assertEqual(m.keys, {'UP'})
                m.command.assert_called_once()
                m.key_up(event(second, widget=self.widget))
                self.assertEqual(m.keys, set())
                self.assertEqual(m.command.call_count, 2)
                m.command.assert_called_with('manual', 'UP', False)
                m.key_up(event(second, widget=self.widget))  # bind_all duplicate
                self.assertEqual(m.command.call_count, 2)

    def test_q_and_e_duplicate_z_and_x_in_russian_layout(self):
        for virtual,char,button in ((12,'й','B'),(14,'у','A'),(6,'я','B'),(7,'ч','A')):
            self.monitor.key_down(event(virtual,char,widget=self.widget));self.assertEqual(self.monitor.keys,{button})
            self.monitor.key_up(event(virtual,char.upper(),widget=self.widget));self.assertFalse(self.monitor.keys)

    def test_all_wasd_work_with_russian_symbols(self):
        for virtual, char, expected in ((13, 'ц', 'UP'), (1, 'ы', 'DOWN'), (0, 'ф', 'LEFT'), (2, 'в', 'RIGHT')):
            self.monitor.key_down(event(virtual, char, widget=self.widget))
            self.assertEqual(self.monitor.keys, {expected})
            self.monitor.key_up(event(virtual, char.upper(), widget=self.widget))
            self.assertFalse(self.monitor.keys)

    def test_rebinding_held_key_cannot_leave_old_button_stuck(self):
        m = self.monitor
        m.key_down(event(7, widget=self.widget))
        self.settings.bind('A', 'c')
        m.key_up(event(7, widget=self.widget))
        self.assertFalse(m.keys)
        m.command.assert_called_with('manual', 'A', False)

    def test_focus_loss_and_f9_clear_both_alias_sources(self):
        m = self.monitor
        m.key_down(event(126, widget=self.widget))
        m.key_down(event(13, widget=self.widget))
        m.take_control(focus=False)
        self.assertFalse(m.keys)
        self.assertFalse(m._held_keys)
        m.key_up(event(13, widget=self.widget))
        m.key_down(event(126, widget=self.widget))
        self.assertEqual(m.keys, {'UP'})
        m.save_if_changed = Mock()
        m.focus_out(None)
        self.assertFalse(m.keys)
        self.assertFalse(m._held_keys)
        m.key_down(event(13, widget=self.widget))
        self.assertEqual(m.keys, {'UP'})

    def test_custom_digit_mapping_is_used_with_any_layout(self):
        self.settings.set('speed_bindings', dict(DEFAULTS['speed_bindings'], **{'1': 0, '0': 2.75}))
        self.monitor.key_down(event(0x12, '!', widget=self.widget))
        self.assertTrue(self.monitor.paused)
        self.monitor.key_down(event(0x1d, ')', widget=self.widget))
        self.assertFalse(self.monitor.paused)
        self.assertEqual(self.monitor.settings['speed'], 2.75)


class HotkeyWidgetTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from pokemon_red.panel import TrainerPanel
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.window = tk.Tk()
        self.window.geometry('540x820')
        self.errors = []
        self.window.report_callback_exception = lambda *args: self.errors.append(str(args[1]))
        self.monitor = SimpleNamespace(settings=Settings(Path(self.temp.name)), release_manual_keys=Mock(),
                                       physical_key=Mock(), take_control=Mock(), emergency_stop=Mock())
        panel = SimpleNamespace(window=self.window, monitor=self.monitor)
        from types import MethodType
        panel.label = MethodType(TrainerPanel.label, panel)
        panel.button = MethodType(TrainerPanel.button, panel)
        self.parent = tk.Frame(self.window, bg='#101820')
        self.parent.pack(fill='both', expand=True)
        self.view = HotkeySettings(panel, self.parent)
        self.window.update()

    def tearDown(self):
        self.window.destroy()

    def test_speed_form_applies_atomically_and_normalizes_values(self):
        self.view.speed_vars['2'].set('2,75')
        self.view.speed_vars['9'].set('oops')
        self.view.apply_speeds()
        self.assertEqual(self.monitor.settings['speed_bindings'], DEFAULTS['speed_bindings'])
        self.assertIn('9', self.view.speed_hint.cget('text'))
        self.view.speed_vars['9'].set('32')
        self.view.apply_speeds()
        self.assertEqual(self.monitor.settings['speed_bindings']['2'], 2.75)
        self.assertEqual(self.view.speed_vars['2'].get(), '2.75')
        self.assertEqual(Settings(Path(self.temp.name))['speed_bindings']['9'], 32)
        self.view.reset_speeds()
        self.assertEqual(self.view.speed_vars['9'].get(), '20')
        self.assertFalse(self.errors)

    def test_capture_second_key_respects_conflicts_layout_and_safety(self):
        # A focus_force/update sequence can deliver macOS pending/repeat keys
        # into the finite mock sequence. Exercise the real bound handler through
        # a virtual event, without taking keyboard focus from another app.
        self.window.withdraw()
        self.window.update()
        self.monitor.physical_key.side_effect = ['w', 'c', 'F9', 'Escape']
        dialog = self.view.capture_key('A', 1)
        def press():
            handler = dialog.bind('<KeyPress>')
            self.assertTrue(handler)
            dialog.bind('<<CaptureKeyTest>>', handler)
            dialog.event_generate('<<CaptureKeyTest>>')
            self.window.update()
        press()  # W is already UP; dialog must stay open.
        self.assertTrue(dialog.winfo_exists())
        self.assertEqual(self.monitor.settings['bindings']['A'], ['x','e'])
        press()
        self.assertFalse(dialog.winfo_exists())
        self.assertEqual(self.monitor.settings['bindings']['A'], ['x', 'c'])
        self.assertEqual(self.view.binding_buttons['A', 1].cget('text'), 'C')
        self.view.remove_key('A', 1)
        self.monitor.release_manual_keys.assert_called()
        self.assertEqual(self.monitor.settings['bindings']['A'], ['x'])
        dialog = self.view.capture_key('A', 1)
        press()
        self.monitor.take_control.assert_called_once()
        dialog = self.view.capture_key('A', 1)
        press()
        self.monitor.emergency_stop.assert_called_once()
        self.assertFalse(self.errors)

    def test_two_slots_and_speed_fields_fit_standard_panel_width(self):
        for widget in [*self.view.binding_buttons.values(), *self.view.speed_entries.values()]:
            self.assertGreater(widget.winfo_width(), 50)
            self.assertLessEqual(widget.winfo_rootx()+widget.winfo_width(), self.window.winfo_rootx()+self.window.winfo_width())
        self.assertFalse(self.errors)


if __name__ == '__main__':
    unittest.main()
