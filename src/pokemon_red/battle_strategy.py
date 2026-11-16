"""Single-battle choices: expected attacks to KO plus the actual switch cost."""
import math
from .mechanics import ranked_attacks,incoming_risk
from .battle_conditions import switch_blockers

def current_mon(state):
    battle=state.get('battle') or {};live=next(iter(battle.get('allies',[])),None)
    # Party-menu initialization temporarily changes party indexes to the cursor
    # slot while BattleMon still describes the old fighter. Its UID stays valid.
    raw=live or next((m for m in battle.get('unverified_battlers',[]) if not m.get('position',1)&1),None)
    if raw and raw.get('uid'):
        matched=next((m for m in state.get('party',[]) if m.get('uid')==raw['uid']),None)
        if matched:return matched
    slot=live.get('party_slot') if live else state.get('controls',{}).get('player_party_slot')
    return next((m for m in state.get('party',[]) if m.get('slot')==slot),None)

def enemy_mon(state):
    battle=state.get('battle') or {}
    live=next((m for m in battle.get('enemies',[]) if m.get('hp',0)>0),None)
    if live:return live
    rows=[m for m in battle.get('enemy_party',[]) if m.get('hp',0)>0 and m.get('checksum_valid',True)]
    return next((m for m in rows if m['slot']==battle.get('next_enemy_slot')),rows[0] if rows else None)

def attack_plan(mon,enemy,root):
    rows=ranked_attacks(mon,enemy,root)
    if not rows:return None
    index,best=rows[0];hp=max(1,int(enemy['hp']));pp=mon['moves'][index].get('current_pp',mon['moves'][index].get('pp',0))
    if pp>=math.ceil(hp/max(1,best['min'])):return dict(index=index,turns=best['turns'],attack=best)
    # Scarce PP: bounded damage DP can finish with more than one legal move.
    costs=[math.inf]*(hp+1);first=[None]*(hp+1);costs[0]=0
    for index,row in rows:
        damage=max(1,int(row['mean']));available=mon['moves'][index].get('current_pp',mon['moves'][index].get('pp',0))
        for _ in range(min(available,math.ceil(hp/damage))):
            before=costs[:];previous=first[:]
            for done in range(hp):
                if not math.isfinite(before[done]):continue
                target=min(hp,done+damage);cost=before[done]+1/max(.001,row['accuracy'])
                if cost<costs[target]:costs[target]=cost;first[target]=previous[done] if previous[done] is not None else index
    if first[hp] is None:return None
    return dict(index=first[hp],turns=costs[hp],attack=next(r for i,r in rows if i==first[hp]))

def choose_fighter(state,root,*,free_switch=False,forced=False):
    current=current_mon(state);enemy=enemy_mon(state);options=[]
    for mon in state.get('party',[]):
        if mon.get('hp',0)<=0 or mon.get('is_egg') or not mon.get('checksum_valid',True):continue
        same=current is not None and mon['uid']==current['uid']
        if forced and same and state.get('controls',{}).get('player_fainted'):continue
        if not same and not forced and not free_switch and switch_blockers(state):continue
        if enemy is None:
            options.append(dict(mon=mon,index=None,turns=0,switch_cost=0,cost=0,risk=0,same=same,survives=True));continue
        plan=attack_plan(mon,enemy,root)
        if plan is None:continue
        charge=int(not same and not free_switch and not forced)
        incoming=ranked_attacks(enemy,mon,root);damage=incoming[0][1]['mean'] if incoming else 0
        slower=enemy.get('stats',{}).get('speed',0)>=mon.get('stats',{}).get('speed',0)
        exposures=max(0,math.ceil(plan['turns'])-1+int(slower)+charge)
        options.append(dict(plan,mon=mon,switch_cost=charge,cost=plan['turns']+charge,risk=incoming_risk(mon,enemy,root),same=same,survives=damage*exposures<mon['hp']))
    if not options:return None
    safe=[r for r in options if r['survives']];pool=safe or options
    return min(pool,key=lambda r:(r['cost'],not r['same'],r['risk'],-r['mon']['hp']/max(1,r['mon'].get('max_hp',1)),r['mon'].get('slot',0)))
