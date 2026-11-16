"""Shared one/two-hit certificates and finite-PP learner resource policy.

Hits exclude misses; accuracy still contributes to expected battle time. Route
certificates use upper-bound wild HP/defenses and every possible ability.
"""
from collections import Counter
from functools import lru_cache
import json
from .catalog import catalog,species,move
from .models import calculate_stats
from .mechanics import estimate,wild_mon,ranked_attacks

MIN_LEARNER_COVERAGE=.8

def hit_limit(config):return 2 if config.get('allow_two_hits',True) else 1

def finish_plan(options,pp,hp,max_hits):
    """Find an executable certificate, including two different last-PP moves."""
    safe=[r for r in options if r.get('min',0)>0 and not r.get('approximate',False) and pp.get(r['move_id'],0)>=1 and r.get('effect_name') not in ('SUPER_FANG','ENDEAVOR')]
    candidates=[]
    for first in safe:
        if first['min']>=hp:sequences=[(first,)]
        elif max_hits>=2:sequences=[(first,second) for second in safe if first['min']+second['min']>=hp and pp.get(first['move_id'],0)>=1+int(first['move_id']==second['move_id'])]
        else:sequences=[]
        for sequence in sequences:
            counts=dict(Counter(r['move_id'] for r in sequence));turns=sum(1/max(.001,r['accuracy']) for r in sequence)
            result=dict(first,certified_hits=len(sequence),move_sequence=[r['move_id'] for r in sequence],pp_costs=counts,turns=turns)
            candidates.append((len(sequence),turns,-sum(r['min'] for r in sequence),first['move_id'],result))
    return min(candidates,key=lambda p:p[:-1])[-1] if candidates else None

def live_plan(mon,enemy,root,max_hits):
    options=[]
    for index,row in ranked_attacks(mon,enemy,root):options.append(dict(row,index=index,effect_name=move(row['move_id'],root).get('effect_name')))
    pp={a['id']:a.get('current_pp',a.get('pp',0)) for a in mon['moves']}
    return finish_plan(options,pp,enemy['hp'],max_hits)

def profile_key(mon):
    value={k:mon.get(k) for k in ('species_id','level','stats','types','type_ids','ability_id','held_item','friendship','max_hp')}
    if value.get('friendship') is None:value['friendship']=70
    value['moves']=[dict(id=a['id'],max_pp=a.get('max_pp',a.get('pp',0))) for a in mon['moves']]
    return json.dumps(value,sort_keys=True,separators=(',',':'))

@lru_cache(maxsize=256)
def _profile(root,route,key,trainee):
    ready=json.loads(key);ready.update(hp=ready['max_hp'],status_code=0,stages={})
    if not ready.get('types'):ready.pop('types',None)
    ready['moves']=[dict(move(a['id'],root),current_pp=a['max_pp']) for a in ready['moves']]
    result=[]
    for entry in catalog(root)['routes'][route]['mons']:
        info=species(entry['species_id'],root)
        for level in range(entry['min_level'],entry['max_level']+1):
            foe=wild_mon(entry['species_id'],level,root);foe['stats']=calculate_stats(info,level,[31]*6)
            for stat in ('defense','special_defense'):foe['stats'][stat]=foe['stats'][stat]*110//100
            foe['hp']=foe['max_hp']=foe['stats']['hp'];options=[]
            for index,attack in enumerate(ready['moves']):
                if not attack.get('power') or not attack['current_pp']:continue
                variants=[]
                for aid in set(info['abilities']):
                    own=dict(ready,stages={'attack':-1}) if trainee and aid==22 and ready.get('ability_id') not in (29,52,73) else ready
                    variants.append(estimate(own,dict(foe,ability_id=aid),attack,root))
                worst=dict(min(variants,key=lambda r:(r.get('ohko_on_hit',0),r['mean'])))
                worst.update(min=min(r['min'] for r in variants),ohko_on_hit=min(r.get('ohko_on_hit',0) for r in variants),ohko=min(r['ohko'] for r in variants),index=index,effect_name=attack.get('effect_name'))
                if worst['mean']>0:options.append(worst)
            result.append(dict(species_id=entry['species_id'],species=info['name'],level=level,hp=foe['hp'],weight=entry['weight']/(entry['max_level']-entry['min_level']+1),options=options))
    return tuple(result)

def route_profile(mon,route,root,*,trainee=True):return _profile(root,route,profile_key(mon),trainee)

def coverage_rows(mon,route,root,*,trainee=False,max_hits=1,refill=True):
    pp={a['id']:a.get('max_pp',a.get('pp',0)) if refill else a.get('current_pp',a.get('pp',0)) for a in mon['moves']};rows=[]
    for profile in route_profile(mon,route,root,trainee=trainee):
        options=profile['options'];best=finish_plan(options,pp,profile['hp'],max_hits)
        if best is None:
            available=[r for r in options if pp.get(r['move_id'],0)>=1]
            best=dict(min(available,key=lambda r:(-r.get('ohko_on_hit',0),-r['accuracy'],r['turns']))) if available else dict(mean=0,min=0,max=0,ohko=0,ohko_on_hit=0,turns=1000,move='Нет подходящей атаки',move_id=0,accuracy=0)
            best['certified_hits']=None
        rows.append(dict({k:v for k,v in profile.items() if k!='options'},attacker=mon.get('nickname',mon.get('species','Pokémon')),attacker_uid=mon.get('uid'),**best))
    return rows

def route_resources(mon,route,root,config,*,threshold=MIN_LEARNER_COVERAGE):
    limit=hit_limit(config);profile=route_profile(mon,route,root,trainee=True)
    full={a['id']:a.get('max_pp',a.get('pp',0)) for a in mon['moves']};live={a['id']:a.get('current_pp',a.get('pp',0)) for a in mon['moves']}
    coverage=lambda pp:sum(r['weight'] for r in profile if finish_plan(r['options'],pp,r['hp'],limit))/100
    baseline,current=coverage(full),coverage(live)
    return dict(full=baseline,current=current,max_hits=limit,threshold=threshold,depleted=baseline+1e-9>=threshold and current+1e-9<threshold)

def strongest(mon):
    """Deterministic combat strength for selecting one primary mentor."""
    return (mon['level'],max(mon.get('stats',{}).get('attack',0),mon.get('stats',{}).get('special_attack',0)),mon.get('max_hp',0),sum(a.get('max_pp',a.get('pp',0)) for a in mon['moves'] if a.get('power',0)),mon['uid'])
