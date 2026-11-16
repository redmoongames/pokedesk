"""Version-specific link menus; exchange rules and verification stay shared."""
from dataclasses import dataclass
from .game_layout import hoenn,flag

@dataclass(frozen=True)
class TradeLayout:
    pointer:str
    graph:str
    cursor:int
    allowed:int
    mode:int
    remote:int
    attendant:tuple
    stairs_up:tuple
    stairs_down:tuple

FRLG=TradeLayout('sTradeMenu','sCursorMoveDestinations',0x35,0x38,0x6f,0x7e,(10,4),(2,6),(2,6))
RS=TradeLayout('gUnknown_03004824','gTradeNextSelectedMonTable',0x41,0x44,0x7b,0x8a,(7,4),(2,6),(2,5))
def layout(game):return RS if hoenn(game) else FRLG

def learning_prompt(game,state):
    for task in state['controls']['tasks']:
        if task['name']=='Task_TradeEvolutionScene':
            d=task['data']
            if hoenn(game):return d[0]==17 and d[8]==4
            return d[0]==20 and d[6]==4
    return False

def preflight(a,b):
    from .editions import edition
    errors=[]
    for own,other in ((a,b),(b,a)):
        if not hoenn(own) and hoenn(other) and not flag(own,0x844):
            errors.append(f'{edition(own.root).name}: для обмена с Хоэнном нужно завершить задание Селио с Ruby и Sapphire на островах Севии')
    return errors
