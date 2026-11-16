from .editions import reference_path,rom_sha1
"""Exact, immutable wild-capture filters; identity comes from decrypted party data."""
from dataclasses import dataclass,asdict
from functools import lru_cache
from pathlib import Path
import json
from .models import STAT_KEYS
from .search_odds import nature_ids
from .iv_preferences import priorities,score_ivs

@lru_cache(maxsize=8)
def hunt_atlas(root):
    from .i18n import t
    atlas=json.loads(reference_path(root,'hunt_atlas.json').read_text())
    if atlas.get('rom_sha1')!=rom_sha1(root):raise ValueError(t('capture.wrong_reference'))
    return atlas

@lru_cache(maxsize=8)
def catchable_species(root):
    from .pokemon_sources import encounter_index
    atlas=hunt_atlas(root);ordinary=set(encounter_index(Path(root)))
    return frozenset(int(number) for number,rows in atlas['entries'].items() if int(number) in ordinary and any(row['map'] in atlas['maps'] and any(weight>0 for weight in row['levels'].values()) for row in rows))

def genders(species_id,root):
    ratio=hunt_atlas(root)['species'][str(species_id)]['gender_ratio']
    return ('genderless',) if ratio==255 else ('male',) if ratio==0 else ('female',) if ratio==254 else ('female','male')

def gender_of(mon,root):
    ratio=hunt_atlas(root)['species'][str(mon['species_id'])]['gender_ratio']
    if ratio==255:return 'genderless'
    if ratio==254:return 'female'
    if ratio==0:return 'male'
    return 'female' if (mon['personality']&255)<ratio else 'male'

@dataclass(frozen=True)
class CaptureTarget:
    species_id:int
    shiny:bool=False
    gender:str='female'
    min_ivs:tuple=(10,10,10,10,10,10)
    min_level:int=1
    max_level:int=100
    route:str|None=None
    method:str|None=None

    natures:tuple=()
    priority_ivs:tuple=()
    search_workers:int=1
    stat_preferences:tuple|None=None
    exact_ivs:bool=True
    search_seconds:int|None=None

    @classmethod
    def parse(cls,data,root):
        number=data.get('species_id');index=hunt_atlas(root)
        if type(number) is not int or str(number) not in index['species']:raise ValueError('Выберите вид Pokémon')
        shiny=data.get('shiny',False);gender=data.get('gender','female' if 'female' in genders(number,root) else genders(number,root)[0]);low=data.get('min_level',1);high=data.get('max_level',100)
        if type(shiny) is not bool:raise ValueError('Shiny: требуется переключатель')
        if gender not in (*genders(number,root),'any'):raise ValueError('Этот пол невозможен для выбранного вида')
        if type(low) is not int or type(high) is not int or not 1<=low<=high<=100:raise ValueError('Уровни: от 1 до 100, минимум не выше максимума')
        ivs=data.get('min_ivs',dict.fromkeys(STAT_KEYS,10))
        if not isinstance(ivs,dict) or set(ivs)!=set(STAT_KEYS) or any(type(v) is not int or not 0<=v<=31 for v in ivs.values()):raise ValueError('Минимальные IV: шесть целых значений от 0 до 31')
        route=data.get('route');method=data.get('method')
        if route is not None and (not isinstance(route,str) or route not in index['maps']):raise ValueError('Неизвестная карта охоты')
        if method is not None and method not in ('land_mons','water_mons','rock_smash_mons','old_rod','good_rod','super_rod'):raise ValueError('Неизвестный способ встреч')
        workers=data.get('search_workers',1)
        if type(workers) is not int or not 1<=workers<=6:
            from .i18n import t
            raise ValueError(t('capture.invalid_workers'))
        from .catch_preferences import normalize_preferences,accepted_natures
        from .search_budget import seconds
        preferences=normalize_preferences(data['stat_preferences']) if data.get('stat_preferences') is not None else None
        exact=data.get('exact_ivs',preferences is None)
        if type(exact) is not bool:
            from .i18n import t
            raise ValueError(t('capture.invalid_exact_ivs'))
        duration=seconds(data.get('search_seconds'))
        preferred=tuple(k for k,r in zip(STAT_KEYS,preferences) if r=='positive') if preferences is not None else priorities(data.get('priority_ivs',()))
        natures=accepted_natures(preferences) if preferences is not None else nature_ids(data.get('natures',()))
        return cls(number,shiny,gender,tuple(ivs[k] for k in STAT_KEYS),low,high,route,method,natures,preferred,workers,preferences,exact,duration)
    def as_dict(self):
        return dict(asdict(self),min_ivs=dict(zip(STAT_KEYS,self.min_ivs)),stat_preferences=dict(zip(STAT_KEYS,self.stat_preferences)) if self.stat_preferences is not None else None)
    @property
    def required_ivs(self):return self.min_ivs if self.exact_ivs else (0,)*6
    def rating(self,values):
        if self.stat_preferences is None:return score_ivs(values,self.required_ivs,self.priority_ivs)
        from .catch_preferences import score
        return score(values,self.stat_preferences,self.min_ivs,exact=self.exact_ivs)
    def should_capture(self,mon,root):
        if not self.matches(mon,root):return False
        return self.search_seconds is None or all(mon['ivs'][k]==31 for k in STAT_KEYS)
    def identity_matches(self,mon,root):
        if not mon.get('checksum_valid') or mon.get('is_egg') or mon.get('species_id')!=self.species_id:return False
        if type(mon.get('shiny')) is not bool or mon['shiny']!=self.shiny:return False
        if type(mon.get('level')) is not int or not self.min_level<=mon['level']<=self.max_level:return False
        if type(mon.get('personality')) is not int or not 0<=mon['personality']<=0xffffffff:return False
        if self.natures and mon['personality']%25 not in self.natures:return False
        if self.gender!='any' and gender_of(mon,root)!=self.gender:return False
        return self.rating(mon.get('ivs')) is not None
    def assess(self,mon,root):
        if not self.identity_matches(mon,root):return None
        rated=self.rating(mon['ivs'])
        fields=('uid','species_id','personality','nature','ivs','shiny','checksum_valid','level')
        return dict(rated,pokemon={k:mon[k] for k in fields if k in mon})
    def matches(self,mon,root):
        rated=self.assess(mon,root)
        return rated is not None and not rated['missing']


def candidates(target,root):
    values=[]
    if target.species_id not in catchable_species(root):return values
    from .pokemon_sources import encounter_index
    ordinary=encounter_index(Path(root)).get(target.species_id,[])
    for entry in hunt_atlas(root)['entries'].get(str(target.species_id),[]):
        canonical=next((r for r in ordinary if r['map']==entry['map'] and r['method']==entry['method']),None)
        if canonical is None:continue
        if target.route and target.route!=entry['map'] or target.method and target.method!=entry['method']:continue
        levels={int(lv):weight for lv,weight in canonical['levels'].items() if target.min_level<=int(lv)<=target.max_level and weight>0}
        if levels:values.append(dict(entry,levels=levels,probability=sum(levels.values())))
    return values
