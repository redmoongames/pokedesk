"""Training approaches and turn-by-turn survival estimates; no core or Tk access."""
from copy import deepcopy
from math import ceil,isfinite
from .i18n import t
from .mechanics import ranked_attacks,wild_mon,attacks
from .battle_strategy import attack_plan
from .rules import stage_multiplier
from .battle_conditions import switch_blockers
APPROACHES=('auto','careful','mentor','fast','local')

def critical_bound(enemy,mon,root):
    """Gen III 2x critical bound, ignoring unfavorable offensive/defensive stages."""
    attacker=deepcopy(enemy);defender=deepcopy(mon)
    attacker['stages']={k:max(0,v) if k in ('attack','special_attack') else v for k,v in attacker.get('stages',{}).items()}
    defender['stages']={k:min(0,v) if k in ('defense','special_defense') else v for k,v in defender.get('stages',{}).items()}
    rows=ranked_attacks(attacker,defender,root);normal=max((r['max'] for _,r in ranked_attacks(enemy,mon,root)),default=0)
    critical=max((r['max']*2+2 for _,r in rows),default=0)
    # Unsupported damaging moves cannot be treated as harmless. Refuse an
    # exchange until the opponent is safely knocked out before it can act.
    modelled={i for i,_ in rows}
    if any(i not in modelled for i,_ in attacks(enemy,root)):
        normal=max(normal,mon['max_hp']);critical=max(critical,mon['max_hp'])
    return normal,critical

def live_mon(mon,state):
    own=deepcopy(mon)
    ally=next((a for a in (state.get('battle') or {}).get('allies',[]) if a.get('uid')==mon['uid'] or not a.get('uid') and mon.get('slot') is not None and a.get('party_slot')==mon['slot']),None)
    if ally:
        own.update(deepcopy(ally))
    return own

def duel(mon,enemy,root,*,switch=False):
    plan=attack_plan(mon,enemy,root)
    if plan is None:return None
    row=plan['attack'];damage=row.get('min',0)
    if damage<=0 or not isfinite(plan['turns']):return None
    hits=ceil(enemy['hp']/damage)
    if mon['moves'][plan['index']].get('current_pp',mon['moves'][plan['index']].get('pp',0))<hits:return None
    from .catalog import move
    def speed(m):return m.get('stats',{}).get('speed',0)*stage_multiplier(m.get('stages',{}).get('speed',0))*(.25 if m.get('status_code',0)&0x40 else 1)
    priority=move(mon['moves'][plan['index']]['id'],root).get('priority',0)
    enemy_priority=max((a.get('priority',0) for _,a in attacks(enemy,root)),default=0)
    slow=enemy_priority>priority or enemy_priority==priority and speed(enemy)>=speed(mon)
    exposures=max(0,hits-1+int(slow))+int(switch)
    if row.get('accuracy',1)<1:exposures+=1
    normal,critical=critical_bound(enemy,mon,root)
    code=mon.get('status_code',0);residual=max(1,mon['max_hp']//8) if code&0x18 else max(1,mon['max_hp']//4) if code&0x80 else 0
    budget=(critical+max(0,exposures-1)*normal if exposures else 0)+residual*hits
    return dict(mon=mon,index=plan['index'],hits=hits,turns=plan['turns']+int(switch),normal=normal,critical=critical,budget=budget,survives=mon['hp']>budget,entry_safe=not switch or mon['hp']>critical,finishes_first=not slow and hits==1 and row.get('accuracy',1)>=1)

def choose(state,current,learner,root,*,mode='careful',mentor=None,fighters=None,free_switch=False):
    enemies=(state.get('battle') or {}).get('enemies',[])
    if not enemies:return None
    enemy=enemies[0];blocked=bool(switch_blockers(state));choices=[]
    for raw in state.get('party',[]):
        if raw.get('hp',0)<=0 or raw.get('is_egg') or fighters is not None and raw['uid'] not in fighters:continue
        same=current is not None and raw['uid']==current['uid']
        if blocked and not same:continue
        mon=live_mon(raw,state) if same else raw
        if mon.get('status_code',0)&0x27:continue
        row=duel(mon,enemy,root,switch=not same and not free_switch)
        if row and row['survives'] and row['entry_safe']:choices.append(row)
    if not choices:return None
    own=next((r for r in choices if current and r['mon']['uid']==current['uid']),None)
    if own and (own['finishes_first'] or current['uid']!=learner or mode in ('careful','local')):return own
    primary=next((r for r in choices if r['mon']['uid']==mentor),None)
    if mode=='mentor' and primary:return primary
    return min(choices,key=lambda r:(r['turns'],r['mon']['uid']!=(current or {}).get('uid'),-r['mon']['hp']))

def escape_support(state,current,root):
    if switch_blockers(state):return current
    from .mechanics import escape_info
    enemies=(state.get('battle') or {}).get('enemies',[])
    if not enemies:return current
    enemy=enemies[0];choices=[]
    for mon in state.get('party',[]):
        if mon.get('hp',0)<=0 or mon.get('is_egg'):continue
        same=current and mon['uid']==current['uid'];_,crit=critical_bound(enemy,mon,root)
        if not same and mon['hp']<=crit:continue
        escape=escape_info(mon,enemy.get('stats',{}).get('speed',1))
        if same and escape.get('guaranteed'):return current
        choices.append((not escape.get('guaranteed'),-mon.get('stats',{}).get('speed',0),not same,-mon['hp'],mon))
    return min(choices,key=lambda r:r[:-1])[-1] if choices else current

def plan(inventory,config,root,*,navigator=None,evidence=None,cache=None):
    from .optimizer import make_training_plan,PlanningUnavailable
    from .planning import routes_for
    from .catalog import catalog
    approach=config['training_approach'];working=inventory;requested=config['route']
    if approach=='local':
        state=(inventory.get('_planning') or {}).get('state',{});requested=(state.get('map') or {}).get('name')
        if requested not in routes_for(root):raise ValueError(t('training.local_map_required'))
        if not any(m['uid']==config['trainee'] for m in inventory.get('party',[])):raise ValueError(t('training.local_party_required'))
        working=dict(inventory,boxes=[])
        if navigator is not None and hasattr(navigator,'configure_tools'):navigator.configure_tools(working,'party')
    cfg=dict(config,training_approach='legacy',route=requested)
    failures=[];chosen=None;tactic=None
    if approach in ('auto','fast','mentor'):
        try:
            chosen=make_training_plan(working,dict(cfg,training_policy='coverage',allow_two_hits=False,_force_mentor=approach=='mentor',_force_direct=approach=='fast'),root,navigator=navigator,evidence=evidence,cache=cache)
            tactic='mentor' if chosen.get('training_mode')=='assisted' else 'fast'
            if approach in ('fast','mentor') and tactic!=approach:chosen=None
        except PlanningUnavailable as error:failures.extend(error.excluded)
    if chosen is None and approach in ('auto','careful','local'):
        routes=[requested] if requested!='Auto' else sorted(routes_for(root),key=lambda name:catalog(root)['routes'][name]['difficulty']['mean_level'])
        for route in routes:
            try:
                proposal=make_training_plan(working,dict(cfg,route=route,training_policy='eta'),root,navigator=navigator,evidence=evidence,cache=cache)
                team=working['party'] if approach=='local' else proposal['team'];weights=0
                for row in catalog(root)['routes'][route]['mons']:
                    for level in range(row['min_level'],row['max_level']+1):
                        enemy=wild_mon(row['species_id'],level,root)
                        if any((r:=duel(dict(m,hp=m['max_hp'],status_code=0,stages={},moves=[dict(a,current_pp=a.get('max_pp',a.get('pp',0))) for a in m['moves']]),enemy,root)) and r['survives'] for m in team if not m.get('is_egg')):weights+=row['weight']/(row['max_level']-row['min_level']+1)
                if weights<=0:raise ValueError(t('training.no_survivable_route',coverage=round(weights)))
                proposal['survivable_coverage']=weights/100
                if weights<100:proposal['warnings'].append(t('training.skip_unsafe',coverage=round(weights)))
                chosen=proposal;tactic='local' if approach=='local' else 'careful';chosen['training_mode']=tactic;break
            except (ValueError,RuntimeError) as error:failures.append(dict(route=route,reason=str(error)))
    if chosen is None:raise PlanningUnavailable(failures or [dict(route=requested,reason=t('training.no_tactic'))])
    if approach=='local':
        chosen['team']=deepcopy(inventory['party']);chosen['team_uids']=[m['uid'] for m in inventory['party']];chosen['reserves']=[m['uid'] for m in inventory['party'] if m['uid']!=config['trainee'] and not m.get('is_egg')]
    if tactic in ('careful','local'):
        chosen['fighters']=[m['uid'] for m in chosen['team'] if not m.get('is_egg') and any(a.get('power',0)>0 for a in m.get('moves',[]))]
    from .run_context import team_fingerprint
    chosen['team_fingerprint']=team_fingerprint(chosen['team']);chosen['tactic']=tactic;chosen['effective_policy']='coverage' if tactic in ('mentor','fast') else 'eta';chosen['keep_party']=approach=='local'
    chosen['selection']=dict(chosen.get('selection') or {},mode=config['route'],tactic=tactic,reason=t('training.tactic_'+tactic),excluded=failures+list((chosen.get('selection') or {}).get('excluded',[])))
    if chosen.get('navigation'):
        from .optimizer import forecast_cycle
        actual=dict(config,training_policy=chosen['effective_policy'],_speed=(inventory.get('_planning') or {}).get('speed',1))
        forecast=forecast_cycle(chosen,actual,root,chosen['navigation'],evidence)
        prep=0 if chosen['keep_party'] else chosen.get('forecast',{}).get('preparation_seconds',0)
        forecast.update(preparation_seconds=prep,eta_game_seconds=prep+forecast['remaining_game_seconds'])
        chosen['forecast']=forecast
    return chosen
