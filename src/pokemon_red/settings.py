"""Portable preferences; UI changes are persisted by the owner's FileWriter."""
from copy import deepcopy
import json
from pathlib import Path

from .engine import atomic_bytes
from .i18n import normalize_locale
from .speeds import SPEED_KEYS, normalize_speed

LEGACY_BINDINGS = {
    'UP': 'Up', 'DOWN': 'Down', 'LEFT': 'Left', 'RIGHT': 'Right',
    'A': 'x', 'B': 'z', 'START': 'Return', 'SELECT': 'Shift_R', 'L': 'q', 'R': 'w',
}
DEFAULTS = {
    'bindings': {
        'UP': ['Up', 'w'], 'DOWN': ['Down', 's'],
        'LEFT': ['Left', 'a'], 'RIGHT': ['Right', 'd'],
        'A': ['x', 'e'], 'B': ['z', 'q'], 'START': ['Return'], 'SELECT': ['Shift_R'],
        'L': ['bracketleft'], 'R': ['bracketright'],
    },
    'speed_bindings': dict(SPEED_KEYS),
    'language': 'en',
    'scale': 3, 'speed': 1, 'sound_enabled': False, 'volume': 80,
    'autosave_enabled': True, 'autosave_seconds': 5, 'panel_on_start': True, 'encounters_on_start': False,
    'auto_focus_game': False, 'prevent_app_nap': True, 'ai_control_overlay': True,
}
# Migrate only the complete untouched prior preset; preserve custom layouts.
PREVIOUS_BINDINGS=dict(deepcopy(DEFAULTS['bindings']),A=['x'],B=['z'],L=['q'],R=['e'])
RESERVED = {*SPEED_KEYS, 'space', 'Escape', 'F1', 'F5', 'F8', 'F9',
            'Meta_L', 'Meta_R', 'Super_L', 'Super_R'}


def normalize_key(key: str) -> str:
    if not isinstance(key, str) or not 0 < len(key) < 40:
        raise ValueError('Нужна физическая клавиша клавиатуры')
    return key.lower() if len(key) == 1 else key


def key_name(key: str) -> str:
    return {'Up': '↑', 'Down': '↓', 'Left': '←', 'Right': '→', 'Return': 'Enter',
            'Shift_R': 'Правый Shift', 'Shift_L': 'Левый Shift', 'Tab': 'Tab',
            'bracketleft': '[', 'bracketright': ']', 'BackSpace': 'Backspace'}.get(key, key.upper() if len(key) == 1 else key)


def normalize_bindings(bindings):
    """Accept old single-key preferences and produce one canonical list model."""
    if not isinstance(bindings, dict) or set(bindings) != set(DEFAULTS['bindings']):
        raise ValueError('Нужны назначения для всех кнопок GBA')
    result, used = {}, {}
    for button, assigned in bindings.items():
        keys = [assigned] if isinstance(assigned, str) else assigned
        if not isinstance(keys, list) or len(keys) > 2:
            raise ValueError('На кнопку можно назначить до двух клавиш')
        result[button] = []
        for raw in keys:
            key = normalize_key(raw)
            if key in RESERVED:
                raise ValueError('Клавиша зарезервирована для управления приложением')
            if key in used:
                raise ValueError(f'Клавиша уже назначена кнопке {used[key]}')
            used[key] = button
            result[button].append(key)
    return result


def normalize_speed_bindings(bindings):
    if not isinstance(bindings, dict) or set(bindings) != set(SPEED_KEYS):
        raise ValueError('Задай скорость для каждой цифры от 0 до 9')
    return {key: normalize_speed(bindings[key]) for key in SPEED_KEYS}


class Settings:
    def __init__(self, root: Path):
        self.path = root / 'Data/settings.json'
        self.save_hook = None
        self.values = deepcopy(DEFAULTS)
        try:
            raw = json.loads(self.path.read_text())
        except (FileNotFoundError, ValueError, OSError):
            raw = {}
        if not isinstance(raw, dict):
            raw = {}
        self.values['language'] = normalize_locale(raw.get('language', 'en'))
        for key in ('sound_enabled', 'autosave_enabled', 'panel_on_start', 'encounters_on_start', 'auto_focus_game', 'prevent_app_nap', 'ai_control_overlay'):
            if type(raw.get(key)) is bool:
                self.values[key] = raw[key]
        if type(raw.get('volume')) is int and 0 <= raw['volume'] <= 100:
            self.values['volume'] = raw['volume']
        for key, choices in (('scale', (1, 2, 3, 4, 5)),
                             ('autosave_seconds', (5, 10, 15, 30, 60, 120))):
            if type(raw.get(key)) is int and raw.get(key) in choices:
                self.values[key] = raw[key]
        try:
            self.values['speed'] = normalize_speed(raw.get('speed', 1), allow_pause=False)
        except ValueError:
            pass
        bindings = raw.get('bindings')
        if bindings is not None and bindings not in (LEGACY_BINDINGS, PREVIOUS_BINDINGS):
            # Custom assignments retain their exact meaning. Untouched presets
            # upgrade to arrows/WASD, X/E, Z/Q, and separate shoulder keys.
            try:
                self.values['bindings'] = normalize_bindings(bindings)
            except ValueError:
                pass
        try:
            self.values['speed_bindings'] = normalize_speed_bindings(raw.get('speed_bindings'))
        except ValueError:
            pass

    def __getitem__(self, key):
        return self.values[key]

    def set(self, key, value, *, persist=True):
        if key == 'language':
            value = normalize_locale(value)
        elif key == 'speed':
            value = normalize_speed(value, allow_pause=False)
        elif key == 'bindings':
            value = normalize_bindings(value)
        elif key == 'speed_bindings':
            value = normalize_speed_bindings(value)
        self.values[key] = value
        if persist:
            self.save()

    def bind(self, button: str, key: str, slot: int = 0):
        if button not in self.values['bindings']:
            raise ValueError('Неизвестная кнопка GBA')
        if type(slot) is not int or slot not in (0, 1):
            raise ValueError('На кнопку можно назначить до двух клавиш')
        bindings = deepcopy(self.values['bindings'])
        keys = bindings[button]
        key = normalize_key(key)
        if slot < len(keys):
            keys[slot] = key
        else:
            keys.append(key)
        self.set('bindings', bindings)

    def unbind(self, button: str, slot: int):
        if button not in self.values['bindings'] or type(slot) is not int or slot not in (0, 1):
            raise ValueError('Неизвестное назначение клавиши')
        bindings = deepcopy(self.values['bindings'])
        if slot < len(bindings[button]):
            bindings[button].pop(slot)
            self.set('bindings', bindings)

    def reset_bindings(self):
        self.set('bindings', deepcopy(DEFAULTS['bindings']))

    def reset_speed_bindings(self):
        self.set('speed_bindings', dict(SPEED_KEYS))

    def save(self):
        if self.save_hook is not None:
            return self.save_hook()
        atomic_bytes(self.path, (json.dumps(self.values, ensure_ascii=False, indent=2) + '\n').encode(), durable=True)
