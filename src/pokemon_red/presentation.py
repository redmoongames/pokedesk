"""Pure state-to-presentation contract, shared by the automation page and dock."""
from dataclasses import dataclass
from enum import StrEnum

class RunState(StrEnum):
    READY='ready'
    RUNNING='running'
    BOT_PAUSED='bot_paused'
    MANUAL_PAUSED='manual_paused'
    ATTENTION='attention'
    ERROR='error'
    FINISHED='finished'

@dataclass(frozen=True)
class RunPresentation:
    state:RunState
    message:str
    primary:str
    secondary:str
    controls_visible:bool

def present(info,paused,speed,validation=''):
    running=info.get('running',False);status=info.get('status','idle')
    if status in ('attention','error') and not running:
        return RunPresentation(RunState.ATTENTION if status=='attention' else RunState.ERROR,info.get('reason','Нужно твоё внимание'),'В игру · решить вручную · 1×','Пауза игры',True)
    if running:
        return RunPresentation(RunState.BOT_PAUSED if paused else RunState.RUNNING,('Бот на паузе' if paused else info.get('stage') or 'Бот работает'),'Играть самому · 1×' if paused else 'Играть самому · F9',f'Продолжить бота · {speed}×' if paused else 'Пауза бота',True)
    if paused:return RunPresentation(RunState.MANUAL_PAUSED,info.get('reason','') if status=='finished' else validation,'Играть вручную · 1×',f'Продолжить игру · {speed}×',True)
    return RunPresentation(RunState.FINISHED if status=='finished' else RunState.READY,info.get('reason','') if status=='finished' else validation,'В игру','Пауза игры',False)
