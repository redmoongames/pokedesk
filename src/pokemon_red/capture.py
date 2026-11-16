"""FireRed's integer catch calculation and conservative capture decisions.

Reference: pret/pokefirered ce6406d8, Cmd_handleballthrow. Probabilities below
are the four-shake model; actual RNG is deterministic and retries vary timing.
"""
from dataclasses import dataclass
from math import isqrt

SOURCE = 'https://github.com/pret/pokefirered/blob/ce6406d8c2eaf46d543c8a2606de0c3cb1951982/src/battle_script_commands.c'

def ball_multiplier(ball_id, *, level=1, types=(), caught=False, turns=0, underwater=False):
    if ball_id in (1, 4, 11, 12):return 10
    if ball_id == 2:return 20
    if ball_id in (3, 5):return 15
    if ball_id == 6:return 30 if 11 in types or 6 in types else 10
    if ball_id == 7:return 35 if underwater else 10
    if ball_id == 8:return max(10, 40-level) if level < 40 else 10
    if ball_id == 9:return 30 if caught else 10
    if ball_id == 10:return min(40, turns+10)
    raise ValueError('Неподдерживаемый покебол')

def catch_probability(catch_rate, hp, max_hp, *, ball_id=4, status=0, level=1,
                      types=(), caught=False, turns=0, underwater=False, safari_factor=None):
    if type(hp) is not int or type(max_hp) is not int or not 0 < hp <= max_hp:
        raise ValueError('Для ловли нужны живой противник и корректные HP')
    if not 0 <= catch_rate <= 255 or not 1 <= level <= 100 or turns < 0:
        raise ValueError('Некорректные параметры ловли')
    if ball_id == 5:
        if safari_factor is None:raise ValueError('Для Safari Ball нужен safari factor')
        catch_rate = safari_factor*1275//100
    multiplier=ball_multiplier(ball_id,level=level,types=types,caught=caught,turns=turns,underwater=underwater)
    odds=(catch_rate*multiplier//10)*(3*max_hp-2*hp)//(3*max_hp)
    if status & (7 | 0x20):odds*=2
    if status & (8 | 0x10 | 0x40 | 0x80):odds=odds*15//10
    if ball_id == 1 or odds > 254:
        return dict(probability=1.0,odds=odds,shake_threshold=65536,multiplier=multiplier,guaranteed=True)
    if odds <= 0:return dict(probability=0.0,odds=0,shake_threshold=0,multiplier=multiplier,guaranteed=False)
    threshold=min(65536,1048560//isqrt(isqrt(16711680//odds)))
    return dict(probability=(threshold/65536)**4,odds=odds,shake_threshold=threshold,multiplier=multiplier,guaranteed=False)

@dataclass(frozen=True)
class CapturePolicy:
    throw_threshold: float = .20
    minimum_survival: float = .99

    def decide(self, chance, hp, actions=()):
        """Require a supplied conservative critical-inclusive upper damage bound.

        Never mistake an OHKO estimate for a safe weakening estimate. Status
        actions must explicitly have no residual damage or recoil risk.
        """
        if not 0 <= chance <= 1 or hp <= 0:raise ValueError('Некорректное состояние ловли')
        if chance >= self.throw_threshold:return dict(action='throw',reason='chance_at_least_threshold',probability=chance)
        safe=[]
        for candidate in actions:
            bound=candidate.get('max_critical_damage')
            survives=bound is not None and 0 <= bound < hp
            if not survives or not candidate.get('verified_bound') or candidate.get('residual_damage') or candidate.get('recoil'):
                continue
            if candidate.get('survival_probability',1) < self.minimum_survival:continue
            after=candidate.get('catch_probability_after',chance)
            if after > chance:safe.append((after,candidate))
        if safe:
            after,best=max(safe,key=lambda item:item[0])
            return dict(action='weaken',reason='verified_survival_bound',move_id=best['move_id'],probability=after)
        return dict(action='throw',reason='no_verified_safe_weakening',probability=chance)

SLEEP_MOVES=(147,79,142,95,47,320)
def capture_kit(mon):
    moves={m['id'] for m in mon.get('moves',[])}
    return 73 in moves and bool(moves.intersection(SLEEP_MOVES))

class VenusaurPolicy:
    """No direct damage: ordinary ball → sleep → better ball → safe seed."""
    def decide(self,enemy,hunter,balls,catch_rate):
        moves={m['id']:m for m in hunter.get('moves',[]) if m.get('current_pp',0)>0}
        def chance(ball):return catch_probability(catch_rate,enemy['hp'],enemy['max_hp'],ball_id=ball,status=enemy.get('status_code',0),level=enemy['level'])['probability']
        available=[b for b in (4,3,2) if balls.get(b,0)>0]
        if not available:return dict(action='attention',reason='Нет Poké Ball, Great Ball или Ultra Ball')
        basic=4 if 4 in available else available[0];prob=chance(basic)
        def throw(ball,reason):return dict(action='throw',ball_id=ball,probability=chance(ball),reason=reason)
        asleep=bool(enemy.get('status_code',0)&7)
        sleep=next((n for n in SLEEP_MOVES if n in moves and not(n in (47,320) and enemy.get('ability_id')==43)),None)
        can_sleep=not enemy.get('status_code',0) and enemy.get('ability_id') not in (15,72) and sleep is not None
        seeded=bool(enemy.get('status3',0)&4)
        if seeded and not asleep and can_sleep:return dict(action='move',move_id=sleep,reason='Цель проснулась · повторяем усыпление')
        if prob>=.20:return throw(basic,'Шанс ≥20% · бросаем сразу')
        if not asleep and can_sleep:return dict(action='move',move_id=sleep,reason='Шанс <20% · усыпляем цель')
        if prob>=.10:return throw(basic,'После усыпления шанс ≥10%')
        for ball in available:
            if chance(ball)>=.10:return throw(ball,'Улучшенный покебол · шанс ≥10%')
        best=max(available,key=chance);tick=max(1,enemy['max_hp']//8)
        # Two residual ticks of headroom: the seed turn plus a later action.
        safe=asleep and enemy['hp']>2*tick and not enemy.get('status_code',0)&0x98 and not enemy.get('status2',0)&(1<<28)
        if safe and not seeded and 12 not in enemy.get('types',[]) and 73 in moves:
            return dict(action='move',move_id=73,reason='Сон и лучший шар дают <10% · Leech Seed')
        if safe and seeded and sleep is not None:
            return dict(action='move',move_id=sleep,reason='Ждём безопасный тик Leech Seed · без прямого урона',wait_seed=True)
        # Throwing advances a seed tick too. Every failed throw is rolled back,
        # so the target cannot be lost even at the last safe HP boundary.
        return throw(best,'Безопасное ослабление недоступно · бросок с откатом')
