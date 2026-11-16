"""Game boundaries for the Pokémon shell; shared services use canonical models.

New engines register their own memory/menu/navigation/codec implementation.
A ROM name never implies support for a service. Per-service capabilities are
explicit, and unsupported operations fail before acquiring emulator input.
"""
from dataclasses import dataclass
from functools import lru_cache

@dataclass(frozen=True)
class MemoryLayout:
    save_blocks_are_pointers:bool
    flags:int
    variables:int
    money:int
    money_key:int|None
    main_flags:int
    primary_metatiles:int
    attribute_size:int
    tileset_attributes:int
    bag:tuple
    badge_flag:int
    running_flag:int
    daycare:tuple
    battle_struct:int|None=None
    choice_move:int=0xc8
    next_party:int=0x5c

@dataclass(frozen=True)
class GameAdapter:
    family:str
    codec:str
    menus:str
    memory:MemoryLayout
    services:frozenset
    def supports(self,feature):return feature in self.services
    def require(self,feature):
        if not self.supports(feature):raise ValueError(f'Для этого движка ещё не адаптирован сервис: {feature}')

SHARED=frozenset({'manual','saves','collection','inventory','battle','training','capture','travel','trade','background_hunt'})
FRLG=GameAdapter('kanto','gen3-box80-party100','frlg',MemoryLayout(True,0xee0,0x1000,0x290,0xf20,0x439,640,4,20,
    (('items','Предметы',0x310,42),('key','Ключевые',0x3b8,30),('balls','Покеболы',0x430,13),('tmhm','TM / HM',0x464,58),('berries','Ягоды',0x54c,43),('pc','PC',0x298,30)),0x820,0x82f,((0x3c98,'Route 5',1),(0x2f80,'Four Island',1),(0x300c,'Four Island',2))),SHARED)
RS=GameAdapter('hoenn','gen3-box80-party100','rs',MemoryLayout(False,0x1220,0x1340,0x490,None,0x43d,512,2,16,
    (('items','Предметы',0x560,20),('key','Ключевые',0x5b0,20),('balls','Покеболы',0x600,16),('tmhm','TM / HM',0x640,64),('berries','Ягоды',0x740,46),('pc','PC',0x498,50)),0x807,0x860,((0x2f9c,'Route 117',1),(0x2fec,'Route 117',2)),0x02016000,0xe8,0x68),SHARED)
REGISTRY={'firered':FRLG,'leafgreen':FRLG,'ruby':RS,'sapphire':RS}
def for_id(identifier):
    try:return REGISTRY[identifier]
    except KeyError as error:raise ValueError('Для игры не зарегистрирован адаптер') from error
@lru_cache(maxsize=128)
def adapter(root):
    from .editions import edition
    return for_id(edition(root).id)

def capability_summary(root):
    value=adapter(root)
    return dict(family=value.family,codec=value.codec,menus=value.menus,services=sorted(value.services))
