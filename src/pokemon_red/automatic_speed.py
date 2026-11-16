"""Temporary 8×/4×/12× pacing; input and safety remain frame-owned.

Slow before accepting menu input. Speed up only after twelve stable frames.
The lease ends on stop/error/F9 without persisting phase rates or resuming pause.
"""
from .game_layout import main_flags
from dataclasses import dataclass
import struct

from .telemetry import symbols, address_names
from .engine import BUTTONS

VERSION = 'adaptive-walk-run-cap-v4'
BASE = 8
MENU = 4
FAST = 12
AUTO_RATES = frozenset((MENU, BASE, FAST))
def speed_cap(value):
    if type(value) is not int or not 1<=value<=16:raise ValueError('Максимальная скорость ИИ: целое число 1–16×')
    return value

def automatic_rates(maximum=12):return frozenset(min(speed_cap(maximum),n) for n in AUTO_RATES)

RAMP_FRAMES = 12
DIRECTIONS = {BUTTONS[key]: key for key in ('UP', 'DOWN', 'LEFT', 'RIGHT')}
MENU_CALLBACKS = frozenset(('CB2_PokeStorage', 'CB2_UpdatePartyMenu',
    'CB2_PokemonSummaryScreen', 'CB2_InitPokemonSummaryScreen',
    'CB2_RunPokemonSummaryScreen'))
MENU_TASKS = ('Task_StartMenu', 'Task_HandleChooseMon', 'Task_HandleSelectionMenu',
              'Task_Multichoice', 'Task_HandleReplaceMove')


@dataclass(frozen=True)
class SpeedDecision:
    speed: int
    phase: str


def decide(context):
    tasks = context.get('tasks', ())
    callback = context.get('callback', '')
    if any('YesNo' in task or 'Yes_No' in task for task in tasks):
        return SpeedDecision(MENU, 'Выбор Yes/No')
    if context.get('interaction') == 'storage' or callback in MENU_CALLBACKS:
        return SpeedDecision(MENU, 'Меню команды / PC / приёмов')
    if context.get('managed_menu') or any(task.startswith(MENU_TASKS) for task in tasks):
        return SpeedDecision(MENU, 'Выбор по меню / плану')
    if context.get('directional') and (context.get('managed_choice') or context.get('field_action')):
        return SpeedDecision(MENU, 'Управляемый выбор стрелками')
    if context.get('battle'):
        if context.get('controller') in ('HandleInputChooseAction', 'HandleInputChooseMove', 'WaitForMonSelection'):
            return SpeedDecision(MENU, 'Выбор действия в бою')
        if callback == 'BattleMainCB2':
            return SpeedDecision(FAST, 'Текст / анимация боя')
        return SpeedDecision(BASE, 'Переход состояния боя')
    if any(task.startswith('Task_EvolutionScene') for task in tasks):
        return SpeedDecision(FAST, 'Анимация эволюции')
    if callback == 'CB2_Overworld':
        if context.get('locked'):
            # Unknown scripts are still intercepted by the independent frame
            # guard. Only an owned/verified interaction can fast-forward text.
            if context.get('interaction') == 'healing' or context.get('field_action') or context.get('recovery'):
                return SpeedDecision(FAST, 'Подтверждённый диалог / анимация')
            return SpeedDecision(BASE, 'Проверка сценария')
        if context.get('waiting') and not context.get('buttons'):
            return SpeedDecision(FAST, 'Ожидание без нажатых кнопок')
        if context.get('movement_mode')=='run':return SpeedDecision(MENU, 'Бег по прямой · 4×')
        return SpeedDecision(BASE, 'Ходьба / точный подход · 8×')
    return SpeedDecision(BASE, 'Базовая скорость / переход')


def button_name(mask):
    return DIRECTIONS.get(mask, 'other' if mask else '')


def action_buttons(action):
    walk = action.get('walk')
    if walk:
        return walk.button
    phases = action.get('phases')
    return button_name(phases[0][0] if phases else 0)


def input_runtime(automation):
    """Same ownership order as Automation.next_mask(), including managed arrows."""
    if automation.recovery_runtime:
        return automation.recovery_runtime
    if automation.field_runtime:
        return automation.field_runtime
    if automation.move_runtime and automation.move_runtime.owns_input:
        return automation.move_runtime
    return None


def read_context(game, automation):
    addresses = symbols(game.root)
    names = address_names(game.root)
    name = lambda pointer: names.get(pointer & ~1, '')
    data = game.read_bytes(addresses['gTasks'], 16 * 40)
    tasks = [name(struct.unpack_from('<I', data, i * 40)[0]) for i in range(16) if data[i * 40 + 4]]
    action = automation.action or {}
    owned = input_runtime(automation)
    buttons = button_name(owned.mask) if owned else action_buttons(action)
    moves = automation.move_runtime
    field = automation.field_runtime
    managed_menu = bool(moves and moves.active) or bool(field and getattr(field, 'phase', '') in ('start_menu', 'party', 'options', 'closing'))
    return dict(callback=name(game.read32(addresses['gMain'] + 4)),
                battle=bool(main_flags(game) & 2),
                controller=name(game.read32(addresses['gBattlerControllerFuncs'])),
                locked=bool(game.read8(addresses['sLockFieldControls'])), tasks=tasks,
                interaction=automation.interaction, managed_menu=managed_menu,
                managed_choice=bool(moves and moves.owns_input),
                field_action=bool(field), recovery=bool(automation.recovery_runtime),
                directional=buttons in DIRECTIONS.values(), buttons=buttons,
                movement_mode=action['walk'].mode if owned is None and action.get('walk') else None,
                waiting=owned is None and getattr(action.get('request'), 'method', None) == 'wait_frames')


class AutomaticSpeed:
    def __init__(self, apply):
        self.apply = apply
        self.enabled = False
        self.speed = None
        self.phase = 'Ручная скорость'
        self.candidate = None
        self.since = 0
        self.max_speed = 12

    def configure(self, enabled, max_speed=12):
        max_speed=speed_cap(max_speed)
        if enabled == self.enabled and max_speed==self.max_speed:
            return
        self.enabled = enabled
        self.max_speed=max_speed
        self.candidate = None
        self.speed = min(BASE,self.max_speed) if enabled else None
        self.phase = 'Подготовка автоматической скорости' if enabled else 'Ручная скорость'
        self.apply(self.speed, self.phase)

    def step(self, frame, context):
        if not self.enabled:
            return False
        desired = decide(context)
        decision=SpeedDecision(min(desired.speed,self.max_speed),desired.phase)
        if decision.speed == self.speed:
            self.candidate = None
            self.phase = decision.phase
            return False
        if decision.speed > self.speed:
            if self.candidate != decision or frame < self.since:
                self.candidate, self.since = decision, frame
            if frame - self.since < RAMP_FRAMES:
                return False
        self.candidate = None
        self.speed, self.phase = decision.speed, decision.phase
        self.apply(self.speed, self.phase)
        return True

    def info(self):
        return dict(enabled=self.enabled, speed=self.speed, phase=self.phase, max_speed=self.max_speed, version=VERSION)
