"""Keyboard settings UI; physical input and persistence stay with Monitor."""
from . import localized_tk as tk

from .settings import key_name
from .speeds import parse_speed, speed_text
from .ui import BG, CARD, TEXT, MUTED, AMBER


class HotkeySettings:
    def __init__(self, panel, parent):
        self.panel = panel
        self.monitor = panel.monitor
        self.binding_buttons = {}
        self.remove_buttons = {}
        self.speed_vars = {}
        label, button = panel.label, panel.button
        label(parent, 'Игровые кнопки', size=17, bold=True, pady=6)
        label(parent, 'До двух клавиш · работают в любой раскладке', size=10, color=MUTED, pady=4)
        grid = tk.Frame(parent, bg=BG)
        grid.pack(fill='x', pady=(0, 6))
        grid.columnconfigure((1, 3), weight=1)
        titles = {'UP': '↑', 'DOWN': '↓', 'LEFT': '←', 'RIGHT': '→',
                  'A': 'A', 'B': 'B', 'START': 'Start', 'SELECT': 'Select', 'L': 'L', 'R': 'R'}
        for row, action in enumerate(self.monitor.settings['bindings']):
            label(grid, titles[action], size=12, pack=False).grid(row=row, column=0, sticky='w', padx=(4, 12))
            for slot in (0, 1):
                widget = button(grid, '', lambda a=action, s=slot: self.capture_key(a, s),
                                height=30, width=110, font=('Helvetica', 11, 'bold'))
                widget.grid(row=row, column=1+slot*2, sticky='ew', pady=2)
                self.binding_buttons[action, slot] = widget
                remove = button(grid, '×', lambda a=action, s=slot: self.remove_key(a, s),
                                height=30, width=28, variant='ghost')
                remove.grid(row=row, column=2+slot*2, padx=(1, 6))
                self.remove_buttons[action, slot] = remove
        button(parent, 'Сбросить игровые клавиши', self.reset_bindings, variant='ghost').pack(anchor='w')
        label(parent, 'Скорость по цифрам 0–9', size=17, bold=True, pady=10)
        label(parent, 'Любое значение × · 0 ставит игру на паузу', size=10, color=MUTED, pady=2)
        speeds = tk.Frame(parent, bg=BG)
        speeds.pack(fill='x', pady=6)
        speeds.columnconfigure((1, 4), weight=1)
        self.speed_entries = {}
        for index, digit in enumerate('0123456789'):
            row, col = index % 5, index // 5 * 3
            label(speeds, digit, size=12, bold=True, pack=False).grid(row=row, column=col, padx=(8, 12))
            var = tk.StringVar(value=speed_text(self.monitor.settings['speed_bindings'][digit]))
            self.speed_vars[digit] = var
            entry = tk.Entry(speeds, textvariable=var, width=8, bg=CARD, fg=TEXT,
                             insertbackground=TEXT, relief='flat', font=('Helvetica', 12))
            entry.grid(row=row, column=col+1, sticky='ew', pady=3, ipady=5)
            entry.bind('<Return>', self.apply_speeds)
            self.speed_entries[digit] = entry
            label(speeds, '×', size=12, color=MUTED, pack=False).grid(row=row, column=col+2, padx=(6, 14))
        actions = tk.Frame(parent, bg=BG)
        actions.pack(fill='x', pady=5)
        button(actions, 'Применить скорости', self.apply_speeds, variant='primary').pack(side='left')
        button(actions, 'Сбросить', self.reset_speeds, variant='ghost').pack(side='left', padx=8)
        self.speed_hint = label(parent, '', size=10, color=MUTED, wraplength=430)
        label(parent, 'Space — пауза / продолжить · F9 — забрать управление\nEsc — остановить бота и игру',
              size=10, color=MUTED, pady=10)
        self.refresh_bindings()

    def refresh_bindings(self):
        for (action, slot), widget in self.binding_buttons.items():
            keys = self.monitor.settings['bindings'][action]
            assigned = slot < len(keys)
            widget.configure(text=key_name(keys[slot]) if assigned else '+ Клавиша',
                             variant='secondary' if assigned else 'ghost')
            self.remove_buttons[action, slot].configure(state='normal' if assigned else 'disabled')

    def remove_key(self, action, slot):
        self.monitor.release_manual_keys()
        self.monitor.settings.unbind(action, slot)
        self.refresh_bindings()

    def reset_bindings(self):
        self.monitor.release_manual_keys()
        self.monitor.settings.reset_bindings()
        self.refresh_bindings()

    def capture_key(self, action, slot):
        self.monitor.release_manual_keys()
        dialog = tk.Toplevel(self.panel.window)
        dialog.title(f'Клавиша для {action}')
        dialog.configure(bg=BG)
        dialog.resizable(False, False)
        dialog.transient(self.panel.window)
        self.panel.label(dialog, f'Нажми клавишу для {action}', size=17, bold=True, padx=24, pady=18)
        hint = self.panel.label(dialog, 'Esc — отмена и пауза · F9 — забрать управление',
                                color=MUTED, size=11, padx=24, pady=12)

        def pressed(event):
            key = self.monitor.physical_key(event)
            if key == 'F9':
                self.monitor.take_control()
                dialog.destroy()
                return 'break'
            if key == 'Escape':
                self.monitor.emergency_stop()
                dialog.destroy()
                return 'break'
            if key is None:
                hint.configure(text='Нажми физическую клавишу на клавиатуре.')
                return 'break'
            try:
                self.monitor.settings.bind(action, key, slot)
            except ValueError as error:
                hint.configure(text=str(error), fg=AMBER)
                return 'break'
            self.refresh_bindings()
            dialog.destroy()
            return 'break'

        dialog.bind('<KeyPress>', pressed)
        self.panel.button(dialog, 'Отмена', dialog.destroy, variant='ghost').pack(pady=(0, 12))
        dialog.focus_set()
        return dialog

    def apply_speeds(self, _=None):
        # Parse everything first: one invalid field cannot partially apply a map.
        try:
            values = {}
            for digit, var in self.speed_vars.items():
                try:
                    values[digit] = parse_speed(var.get())
                except ValueError as error:
                    self.speed_entries[digit].focus_set()
                    raise ValueError(f'Клавиша {digit}: {error}') from None
            self.monitor.settings.set('speed_bindings', values)
        except ValueError as error:
            self.speed_hint.configure(text=str(error), fg=AMBER)
            return 'break'
        for digit, value in values.items():
            self.speed_vars[digit].set(speed_text(value))
        self.speed_hint.configure(text='Назначения сохранены', fg=MUTED)
        return 'break'

    def reset_speeds(self):
        self.monitor.settings.reset_speed_bindings()
        for digit, value in self.monitor.settings['speed_bindings'].items():
            self.speed_vars[digit].set(speed_text(value))
        self.speed_hint.configure(text='Стандартные скорости восстановлены', fg=MUTED)
