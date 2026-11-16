"""One explicitly requested battle; uses the normal automation cancellation scope."""

from .paths import resource
from .game_layout import main_flags
from pathlib import Path
from .telemetry import symbols,read_decision,read_learning_control

SCRIPT='auto_battle.py'
# Ordinary single wild/trainer battles only; special battle modes need decisions.
UNSUPPORTED=1|2|0x40|0x80|0x100|0x200|0x800

def is_script(controller):
    """Bind canonical script identity once per run, never stat paths per frame.

    A new session ID or script/folder invalidates the binding. Thus a symlink
    change is revalidated on the next run while a loaded script keeps its role.
    """
    automation=controller.automation;script=getattr(automation,'script',None)
    if not script:return False
    session=getattr(automation,'session',None)
    key=(getattr(session,'id',None),script,controller.folder)
    cached=getattr(controller,'_battle_script_identity',None)
    if cached is not None and cached[0]==key:return cached[1]
    result=Path(script).resolve()==(resource(controller.folder,'Bots')/SCRIPT).resolve()
    controller._battle_script_identity=(key,result)
    return result

def owns(controller):return controller.automation.running and is_script(controller)

def battle_key(state):
    b=state.get('battle') or {}
    return (b.get('trainer_id'),b.get('flags'),tuple(m['uid'] for m in b.get('enemy_party',[])))

def eligibility(state):
    b=state.get('battle') or {}
    if not state.get('in_battle') or not b:return 'Автобой доступен во время боя'
    if b.get('flags',0)&UNSUPPORTED:return 'Этот режим боя требует ручного управления'
    from .battle_flow import phase,ready
    p=phase(state)
    if p=='lost':return 'Бой проигран · проверь команду'
    if p=='learn_move':return 'Сначала выбери новый приём'
    if not ready(state):return 'Дожидаемся данных боя'
    return None

def status(controller,state=None):
    pending=getattr(controller,'_battle_auto_pending',None)
    pending=pending is not None and pending is getattr(controller,'pending_start',None)
    active=owns(controller)
    if active or pending:return dict(active=active,pending=pending,available=True,reason='Только текущий бой · F9 — взять управление')
    reason=None
    if controller.closing or controller.session_transition:reason='Дождись завершения сохранения'
    elif controller.operation.active or getattr(getattr(controller,'delivery',None),'enabled',False):reason='Управляет автоловля / обмен'
    elif controller.automation.running or controller.pending_start is not None:reason='Управляет другая автоматизация'
    elif getattr(controller,'safety_notice',None):reason='Сначала возьми управление через F9'
    else:reason=eligibility(controller.session_state() if hasattr(controller,'session_state') else state or controller.last_state or {})
    return dict(active=False,pending=False,available=reason is None,reason=reason or 'Только этот бой · без ловли и предметов')

def set_enabled(c,enabled):
    if type(enabled) is not bool:raise ValueError('Некорректный режим автобоя')
    if not enabled:
        info=status(c)
        if info['active'] or info['pending']:
            c.take_control(focus=False);c.pause(save=False);c.notice='Автобой выключен · игра на паузе';c.update_panel()
        return
    state=c.session_state();info=status(c,state)
    if info['active'] or info['pending']:return
    if not info['available']:raise RuntimeError(info['reason'])
    if getattr(c.history.db,'error',None):raise RuntimeError('Журнал недоступен: сохрани игру и перезапусти приложение')
    token=c.pending_start=object();c._battle_auto_pending=token;key=battle_key(state);game=c.game;generation=c.game.state_generation
    def begin(_):
        if c.pending_start is not token or c.closed or c.closing:return
        c.pending_start=None
        fresh=c.session_state();reason=eligibility(fresh)
        if c.game is not game or c.game.state_generation!=generation or battle_key(fresh)!=key:reason='Бой изменился: включи автобой заново'
        if c.operation.active or c.automation.running or getattr(getattr(c,'delivery',None),'enabled',False):reason='Управляет другая автоматизация'
        if reason:c.notice=reason;c.update_panel();return
        c.keys.clear();c.game.advance(0,0);c.automation.start(resource(c.folder,'Bots')/SCRIPT)
        c._battle_auto_session=c.automation.session
        if c.paused:c.set_speed(c.settings['speed'])
        c.notice='Автобой · только текущий бой';c.update_panel()
    try:c.create_slot('Перед автобоем',on_saved=begin)
    except BaseException:c.pending_start=None;raise
    c.notice='Сохраняем точку перед автобоем';c.update_panel()

def frame_guard(c):
    """Before and after every frame: no late A can dismiss a post-battle choice."""
    if not owns(c):
        observed=getattr(c,'_battle_auto_session',None);c._battle_auto_session=None
        if observed is not None and is_script(c) and c.automation.status in ('attention','error'):
            c.pause(save=False);return True
        return False
    c._battle_auto_session=c.automation.session
    s=symbols(c.folder);reason=None;attention=False
    if not main_flags(c.game,s)&2:reason='Бой завершён · автобой выключен'
    elif c.game.read8(s['gBattleOutcome']) in (2,3,9):reason='Бой завершён · проверь команду';attention=True
    elif read_decision(c.game):reason='Нужен твой выбор нового приёма';attention=True
    else:
        learning=read_learning_control(c.game)
        if learning['evo']:reason='Нужен твой выбор эволюции';attention=True
        elif (learning.get('summary') or {}).get('mode') in (2,3):reason='Нужен твой выбор приёма';attention=True
    if reason:
        c.automation.stop(reason,status='attention' if attention else 'finished');c.keys.clear();c.game.advance(0,0);c.pause(save=False);c.notice=reason;c.update_panel();return True
    return False


def run(bot):
    from .battle_fighter import BattleFighter
    from .bot import ControlLost
    try:BattleFighter(bot).run()
    except ControlLost:raise
    except (RuntimeError,ValueError,TimeoutError) as error:bot.handoff('autobattle_attention','Автобой остановлен: '+str(error))
