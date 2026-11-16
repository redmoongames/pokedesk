"""Throw-only capture of this encounter on a disposable operation core."""
import time
from .telemetry import symbols
from .manual_battle import UNSUPPORTED

def eligibility(state):
    b=state.get('battle') or {};c=state.get('controls',{})
    if not state.get('in_battle') or c.get('callback')!='BattleMainCB2':return 'Открой экран текущего дикого Pokémon'
    if b.get('flags',0)&(UNSUPPORTED|8|0x8000|0x10000):return 'Автопоимка доступна в обычном диком бою'
    if b.get('outcome') or state.get('decision'):return 'Сейчас нельзя бросить покебол'
    if (c.get('controllers') or [''])[0] not in ('HandleInputChooseAction','HandleInputChooseMove','HandleMoveSwitching','HandleInputChooseTarget'):return 'Дождись меню боя с диким Pokémon'
    if not state.get('telemetry_valid',True) or not b.get('telemetry_valid',True):return 'Дожидаемся данных противника'
    enemies=b.get('enemies',[])
    if len(enemies)!=1 or not enemies[0].get('identity_valid',True) or enemies[0].get('hp',0)<=0:return 'Нужен живой противник на экране'
    return None

def ball_count(game):
    from .player_inventory import read_player_inventory
    return sum(r['quantity'] for r in read_player_inventory(game)['items'] if r['pocket']=='balls' and r['id']==4)

def status(c,state=None):
    op=c.operation;active=op.active and getattr(op,'kind',None)=='encounter'
    if active:return dict(active=True,available=True,reason=c.notice or 'Повторяем бросок · отключение вернёт исходную встречу')
    reason=None
    if c.closing or c.session_transition:reason='Дождись сохранения'
    elif op.active or c.automation.running or c.pending_start is not None or getattr(getattr(c,'delivery',None),'enabled',False):reason='Управляет другая автоматизация'
    else:
        fresh=c.session_state() if hasattr(c,'session_state') else state or c.last_state or {};reason=eligibility(fresh)
        if reason is None and not ball_count(c.game):reason='В сумке нет Poké Ball'
    return dict(active=False,available=reason is None,reason=reason or 'Poké Ball · неудача — откат; отключение — исходная встреча')

def validate(c):
    reason=eligibility(c.session_state())
    if reason:raise ValueError(reason)
    if c.automation.running or c.pending_start or getattr(getattr(c,'delivery',None),'enabled',False):raise ValueError('Управляет другая автоматизация')
    if not ball_count(c.game):raise ValueError('В сумке нет Poké Ball')
    from .models import read_inventory
    inventory=read_inventory(c.game)
    if len(inventory['party'])>=6 and len(inventory['boxes'])>=420:raise ValueError('В отряде и PC нет места')
    return c.session_state()['battle']['enemies'][0]['uid']

def set_enabled(c,enabled,requested_at=None):
    if type(enabled) is not bool:raise ValueError('Некорректный режим автопоимки')
    if not enabled:
        if c.operation.active and getattr(c.operation,'kind',None)=='encounter':c.operation.command('cancel',requested_at=requested_at)
        return
    if c.operation.active and getattr(c.operation,'kind',None)=='encounter':return
    return c.operation.begin('encounter',{})

class PokeballOnly:
    def decide(self,enemy,hunter,balls,catch_rate):
        if balls.get(4,0)<=0:return dict(action='attention',reason='Нет Poké Ball')
        return dict(action='throw',ball_id=4,reason='Бросаем Poké Ball · неудачная попытка откатится')

def run(player):
    from .wild_capture import CaptureBattle
    from .models import read_inventory
    from .acquisition_play import AcquisitionAttention
    p=player;initial=p.state();reason=eligibility(initial)
    if reason:raise AcquisitionAttention(reason)
    target=initial['battle']['enemies'][0]['uid'];old=read_inventory(p.g);original={m['uid'] for m in old['party']+old['boxes']}
    p.capture_hunter=initial['battle']['allies'][0]['uid']
    class ThrowBattle(CaptureBattle):
        def throw_failed(self,state):
            s=symbols(self.g.root);pointer=self.g.read32(s['gBattlescriptCurrInstr'])
            return s['BattleScript_ShakeBallThrow']<=pointer<s['BattleScript_TrainerBallBlock']
    ThrowBattle(p,policy=PokeballOnly()).run()
    after=read_inventory(p.g);owned=after['party']+after['boxes'];final={m['uid'] for m in owned}
    mon=next((m for m in owned if m['uid']==target and m['uid'] not in original),None)
    if mon is None or not original<=final:raise AcquisitionAttention('Не подтверждена поимка и сохранность прежних Pokémon')
    return mon
