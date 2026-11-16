"""Validated ordinary-input prologue options, independent of UI and core."""
from dataclasses import dataclass,asdict
from math import prod
from string import ascii_letters,digits
from .i18n import t
from .search_odds import nature_ids
from .iv_preferences import priorities

STATS=('hp','attack','defense','speed','special_attack','special_defense')
NAME_CHARS=ascii_letters+digits+" .,!?♂♀/-…“”‘’"
GENDER_RATIO=31  # All three Kanto starters: female when PID low byte < 31.

def valid_name(value,limit=7):
    if not isinstance(value,str) or not value.strip() or value!=value.strip() or len(value)>limit or any(c not in NAME_CHARS for c in value):
        raise ValueError(t('prologue.invalid_name',limit=limit))
    return value

@dataclass(frozen=True)
class NewGameConfig:
    player_name:str='ALEX'
    rival_name:str='GARY'
    player_gender:int=0
    species_id:int=1
    shiny:bool=False
    gender:str='any'
    nature:int|None=None
    natures:tuple=()
    search_workers:int=2
    min_ivs:tuple=(0,0,0,0,0,0)
    priority_ivs:tuple=()

    @classmethod
    def parse(cls,data,game='firered'):
        if game not in ('firered','leafgreen'):raise ValueError(t('prologue.kanto_only'))
        if not isinstance(data,dict):raise ValueError(t('prologue.invalid_options'))
        d=asdict(cls());d.update({k:v for k,v in data.items() if k in d})
        valid_name(d['player_name']);valid_name(d['rival_name'])
        if type(d['player_gender']) is not int or d['player_gender'] not in (0,1) or type(d['species_id']) is not int or d['species_id'] not in (1,4,7):raise ValueError(t('prologue.invalid_options'))
        if type(d['shiny']) is not bool or d['gender'] not in ('any','male','female') or d['nature'] is not None and (type(d['nature']) is not int or not 0<=d['nature']<25):raise ValueError(t('prologue.invalid_options'))
        explicit=d['natures'];d['natures']=nature_ids(explicit,d['nature'])
        if explicit:d['nature']=d['natures'][0] if len(d['natures'])==1 else None
        if type(d['search_workers']) is not int or not 1<=d['search_workers']<=4:raise ValueError(t('odds.invalid_workers'))
        d['priority_ivs']=priorities(d['priority_ivs'])
        ivs=d['min_ivs']
        if not isinstance(ivs,(list,tuple)) or len(ivs)!=6 or any(type(v) is not int or not 0<=v<=31 for v in ivs):raise ValueError(t('prologue.invalid_ivs'))
        d['min_ivs']=tuple(ivs);return cls(**d)
    def json(self):return asdict(self)
    def matches(self,mon):
        return bool(mon and mon.get('checksum_valid') and not mon.get('is_egg') and mon.get('species_id')==self.species_id
            and (not self.shiny or mon.get('shiny')) and (self.gender=='any' or mon_gender(mon)==self.gender)
            and (not (self.natures or nature_ids((),self.nature)) or mon.get('nature') in (self.natures or nature_ids((),self.nature)))
            and all(mon.get('ivs',{}).get(k,-1)>=v for k,v in zip(STATS,self.min_ivs)))
    def expected_attempts(self):
        from .search_odds import starter_odds
        return starter_odds(self)['expected_candidates']

def mon_gender(mon):return 'female' if (mon['personality']&255)<GENDER_RATIO else 'male'
