"""Offline, version-specific Pokémon reference and exact Gen III XP arithmetic."""
from functools import lru_cache
import json
from .engine import ROOT

@lru_cache
def catalog(root=ROOT):
    from .database import load_reference
    return load_reference(root)

def species(number, root=ROOT): return catalog(root)['species'].get(str(number), {})
def move(number, root=ROOT): return catalog(root)['moves'].get(str(number), {})
def ability(number, root=ROOT): return catalog(root)['abilities'].get(str(number), {})

def experience_reward(base_xp, level, *, participants=1, share_holders=0,
                      participated=True, exp_share=False, lucky_egg=False,
                      trainer=False, traded=False, alive=True, recipient_level=1):
    """Cmd_getexp order of integer divisions; no modern level scaling."""
    if not alive or recipient_level >= 100: return 0
    if not 1 <= level <= 100 or participants < 0 or share_holders < 0:
        raise ValueError('Invalid XP calculation inputs')
    base = base_xp * level // 7
    pool = base // 2 if share_holders else base
    xp = max(1, pool // max(1, participants)) if participated and participants else 0
    if exp_share and share_holders: xp += max(1, pool // share_holders)
    for enabled in (lucky_egg, trainer, traded):
        if enabled: xp = xp * 150 // 100
    return xp

def effectiveness(move_type, defender_types, root=ROOT):
    result = 1.0
    for typ in set(defender_types):
        result *= next((m for a,b,m in catalog(root)['effectiveness'] if a==move_type and b==typ),1)
    return result

def evolution_text(evolution, root=ROOT):
    method, p = evolution['method'], evolution['parameter']
    item = catalog(root)['items'].get(str(p), str(p))
    return {1:'Повышение уровня при дружбе ≥220',2:'Дружба ≥220, днём (в FireRed нет смены дня)',
            3:'Дружба ≥220, ночью (в FireRed нет смены дня)',4:f'Уровень {p}',5:'Обмен',
            6:f'Обмен с предметом {item}',7:f'Использовать {item}',
            8:f'Уровень {p}, Attack > Defense',9:f'Уровень {p}, Attack = Defense',
            10:f'Уровень {p}, Attack < Defense',11:f'Уровень {p}, ветка по personality',
            12:f'Уровень {p}, ветка по personality',13:f'Уровень {p}',
            14:f'Уровень {p}, свободный слот и Poké Ball',15:f'Красота ≥{p}, повышение уровня'}.get(method, f'Метод {method}, параметр {p}')
