"""Spawn-weighted learner one/two-hit policy, independent from ETA and accuracy.

Certification is conservative: wild HP/IV at the upper bound, defensive nature
bound, both abilities, minimum noncritical roll. Accuracy remains in ETA/live UI.
"""
from functools import lru_cache
from .catalog import catalog,species,move
from .planning import make_plan,routes_for
from .run_context import RunConfig,team_fingerprint
from .i18n import t

VERSION='coverage-two-hit-pp-v3'

def certified(row):return bool(row.get('certified_hits')) if 'certified_hits' in row else row.get('ohko_on_hit',0)>=1-1e-10 and not row.get('approximate',False)

def matchup_rows(mon,route,root,*,trainee=False,max_hits=1):
    from .combat_policy import coverage_rows
    return coverage_rows(mon,route,root,trainee=trainee,max_hits=max_hits)

def covered(rows):return sum(row['weight'] for row in rows if certified(row))/100

def cover_mask(rows):return sum(1<<i for i,row in enumerate(rows) if certified(row))

def support_cover(matrix,candidates,*,initial=0,mandatory=(),capacity=4):
    """Exact bounded set cover after merging equal masks; no top-species cutoff."""
    count=len(next(iter(matrix.values())));all_bits=(1<<count)-1;by_uid={m['uid']:m for m in candidates};chosen=list(dict.fromkeys(mandatory))
    if any(u not in by_uid for u in chosen) or len(chosen)>capacity:return None
    masks={u:cover_mask(matrix[u]) for u in by_uid};start=initial
    for u in chosen:start|=masks[u]
    def utility(u):
        m=by_uid[u];return (sum(a.get('max_pp',a.get('pp',0)) for a in m['moves'] if a.get('power',0)>0),m['level'],m['max_hp'])
    groups={}
    for u,mask in masks.items():
        if u in chosen or not mask:continue
        if mask not in groups or utility(u)>utility(groups[mask]):groups[mask]=u
    options=sorted(groups.values(),key=lambda u:(-masks[u].bit_count(),tuple(-v for v in utility(u)),u));union=start
    for u in options:union|=masks[u]
    if union!=all_bits:return None
    @lru_cache(maxsize=None)
    def solve(bits,left):
        if bits==all_bits:return ()
        if left==0:return None
        missing=[i for i in range(count) if not bits>>i&1]
        row=min(missing,key=lambda i:sum(bool(masks[u]>>i&1) for u in options))
        for u in options:
            if not masks[u]>>row&1:continue
            next_bits=bits|masks[u]
            if next_bits==bits:continue
            tail=solve(next_bits,left-1)
            if tail is not None:return (u,*tail)
        return None
    answer=solve(start,capacity-len(chosen))
    return None if answer is None else list(dict.fromkeys([*chosen,*answer]))

def difficulty(route,root):
    d=catalog(root)['routes'][route]['difficulty'];return (d['mean_level'],d['expected_wild_xp'],d['max_level'],route)

def trapped_matchups(target,rows,root):
    """Predict possible switch failures; recovery is decided from live battle state.

    A trapping ability is a risk, not a reason to exclude an otherwise useful route.
    Run Away/Smoke Ball improve escape, never permission to switch.
    """
    from .battle_conditions import passive_switch_blockers
    own=dict(target,types=target.get('type_ids') or species(target['species_id'],root)['type_ids'])
    blocked=[]
    for row in rows:
        if certified(row) or row['weight']<=0:continue
        info=species(row['species_id'],root)
        reasons=passive_switch_blockers(own,[dict(hp=1,ability_id=a) for a in info['abilities']])
        if reasons:blocked.append(dict(species=row['species'],level=row['level'],reasons=reasons))
    return blocked


def build_roster(inventory,cfg,route,root,geometry,matrix,mode):
    owned=[m for m in inventory.get('party',[])+inventory.get('boxes',[]) if m.get('checksum_valid') and not m.get('is_egg')];by_id={m['uid']:m for m in owned}
    blocked=trapped_matchups(by_id[cfg['trainee']],matrix[cfg['trainee']],root)
    actual=dict(cfg,route=route,_required_tools=geometry.get('required_tools',[]));base=make_plan(inventory,actual,root)
    target=cfg['trainee'];runner=base['runner'];utilities=set(base.get('utility_uids',[]))-{target,runner}
    candidates=[m for m in owned if m['uid'] not in (target,runner) and any(r['mean']>0 for r in matrix[m['uid']])]
    combat_utils=utilities&{m['uid'] for m in candidates};noncombat=utilities-combat_utils
    capacity=min(4,6-1-int(runner is not None)-len(noncombat))
    initial=0 if mode=='assisted' else cover_mask(matrix[target])
    mentor=cfg.get('_primary_mentor')
    selected=sorted(combat_utils|{mentor}) if mode=='assisted' and mentor else support_cover(matrix,candidates,initial=initial,mandatory=sorted(combat_utils),capacity=capacity)
    if selected is not None and (len(selected)>capacity or any(u not in {m['uid'] for m in candidates} for u in selected)):selected=None
    if selected is None:
        if mode=='assisted':
            missing=[]
            for i,row in enumerate(matrix[target]):
                if any(certified(matrix[m['uid']][i]) for m in candidates):continue
                best=max((matrix[m['uid']][i] for m in candidates),key=lambda r:r.get('min',0),default=None)
                text=f"{row['species']} Lv {row['level']} · до {row['hp']} HP"
                if best:text+=f" · {best['attacker']}: минимум {best.get('min',0)} урона"
                if text not in missing:missing.append(text)
            raise ValueError('До четырёх помощников не покрывают 100% встреч одной атакой при попадании'+(': '+ '; '.join(missing[:3]) if missing else ' при доступных слотах и обязательных HM'))
        selected=[u for u in base['reserves'] if u in {m['uid'] for m in candidates}][:capacity]
    bits=initial
    for u in selected:bits|=cover_mask(matrix[u])
    # Keep spare PP/health in the remaining support slots. Every species remains
    # in the certificate, including rare spawns and every possible level.
    remaining=[m for m in candidates if m['uid'] not in selected]
    while remaining and len(selected)<capacity:
        chosen=max(remaining,key=lambda m:((cover_mask(matrix[m['uid']])&~bits).bit_count(),covered(matrix[m['uid']]),sum(a.get('max_pp',a.get('pp',0)) for a in m['moves'] if a.get('power',0)>0),m['level'],m['uid']))
        selected.append(chosen['uid']);bits|=cover_mask(matrix[chosen['uid']]);remaining.remove(chosen)
    plan=make_plan(inventory,actual,root,helper_uids=selected)
    from .combat_policy import hit_limit,MIN_LEARNER_COVERAGE
    plan.update(training_mode=mode,primary_mentor=mentor,learner_max_hits=hit_limit(cfg),coverage=dict(target=covered(matrix[target]),supports=sum(row['weight'] for i,row in enumerate(matrix[target]) if any(certified(matrix[u][i]) for u in selected))/100,combined=sum(row['weight'] for i,row in enumerate(matrix[target]) if bits>>i&1)/100,threshold=MIN_LEARNER_COVERAGE,minimum=MIN_LEARNER_COVERAGE),difficulty=catalog(root)['routes'][route]['difficulty'])
    rows=[]
    for i,own in enumerate(matrix[target]):
        best=matrix[mentor][i] if mode=='assisted' and mentor else own if certified(own) else min((matrix[u][i] for u in selected),key=lambda r:(not certified(r),-r.get('ohko_on_hit',0),r['turns']),default=own)
        rows.append(dict(best,trainee_one_hit=own.get('ohko_on_hit',0)>=1-1e-10,trainee_hits=own.get('certified_hits'),trainee_move=own['move']))
    plan['battle_risks']=blocked
    if blocked:plan['warnings'].append('Ловушки (Arena Trap и похожие): замена ученика иногда невозможна. Он сражается сам; после обморока возвращаемся лечиться. Прогноз времени этого риска пока приблизительный.')
    plan['expected_attacks']=sum(r['turns']*r['weight'] for r in rows)/100
    plan['matchups']=rows;plan['ohko_chance']=sum(r['weight']*r['ohko'] for r in rows)/100
    plan['assumptions']='Покрытие ученика — доля встреч с KO за '+str(hit_limit(cfg))+' попадания или быстрее; помощники — одно попадание в консервативной модели: верхние HP/IV, защитная природа, обе способности, минимальный урон без критов. Точность отдельно; сложные непроверенные атаки не сертифицируются.'
    if plan['coverage']['combined']<1-1e-9:plan['warnings'].append('Для части редких встреч помощнику может потребоваться несколько атак.')
    return plan,actual

def make_coverage_plan(inventory,config,root,*,navigator=None,evidence=None,cache=None):
    from .optimizer import route_geometry,forecast_cycle,read_evidence,snapshot_navigator,PlanningUnavailable,PRIORS
    cfg=RunConfig.parse(config).as_dict();requested=cfg['route'];world=inventory.get('_planning');contract=None
    owned=[m for m in inventory.get('party',[])+inventory.get('boxes',[]) if m.get('checksum_valid') and not m.get('is_egg')];target=next((m for m in owned if m['uid']==cfg['trainee']),None)
    if not target:raise ValueError('Выбери Pokémon из команды или PC')
    if cfg.get('final_moves'):
        from .move_plan import compile_plan
        contract=compile_plan(target,cfg['target'],cfg['final_moves'],root,cfg['evolution_mode'])
    def attach(plan):
        if contract:
            plan['move_plan']=contract;plan['warnings']+=contract['warnings']
            if any(not any(move(n,root).get('power',0)>0 for n in step['after']) for step in contract['steps']) and not any(u!=plan['trainee'] for u in plan['fighters']):raise ValueError('Для набора без атакующих приёмов нужен боевой помощник')
        return plan
    if navigator is None and world:navigator=snapshot_navigator(root,world).configure_tools(inventory)
    if cache is not None and hasattr(navigator,'planning_world'):navigator.planning_cache=cache
    if navigator is None:
        if requested=='Auto':raise ValueError('Дождись проверки карт и доступных переходов')
        return attach(make_plan(inventory,cfg,root))
    evidence=read_evidence(root) if evidence is None else evidence;available=[];excluded=[]
    def rows(mon,route):
        trainee=mon['uid']==cfg['trainee']
        from .combat_policy import hit_limit
        limit=hit_limit(cfg) if trainee else 1
        if cache is None:return matchup_rows(mon,route,root,trainee=trainee,max_hits=limit)
        return cache.coverage_rows(mon,route,root,(trainee,limit),lambda:matchup_rows(mon,route,root,trainee=trainee,max_hits=limit))
    for route in routes_for(root) if requested=='Auto' else (requested,):
        try:
            # Encounters/types/HP and the learner's known attacks are independent
            # of the tile world. Reject unsuitable routes before any map RPC.
            matrix={target['uid']:rows(target,route)}
            value=covered(matrix[cfg['trainee']]);available.append(dict(route=route,matrix=matrix,value=value))
        except (RuntimeError,ValueError,KeyError) as error:excluded.append(dict(route=route,reason=str(error)))
    from .combat_policy import MIN_LEARNER_COVERAGE,strongest,hit_limit
    direct=[v for v in available if v['value']+1e-9>=MIN_LEARNER_COVERAGE]
    # One primary mentor, chosen by combat strength among those with a feasible
    # route they cover alone in one hit. Then maximize XP per encounter for it.
    def assisted():
        # This generator is never entered when a feasible learner route exists.
        for mentor in sorted((m for m in owned if m['uid']!=cfg['trainee']),key=strongest,reverse=True):
            for v in sorted(available,key=lambda v:(catalog(root)['routes'][v['route']]['difficulty']['expected_wild_xp'],difficulty(v['route'],root)),reverse=True):
                matrix=v['matrix']
                if mentor['uid'] not in matrix:matrix[mentor['uid']]=rows(mentor,v['route'])
                if covered(matrix[mentor['uid']])>=1-1e-9:yield dict(v,mentor=mentor['uid'])
    groups=[('direct',sorted(direct,key=lambda v:difficulty(v['route'],root),reverse=True)),('assisted',assisted())]
    if config.get('_force_mentor'):groups=groups[1:]
    if config.get('_force_direct'):groups=groups[:1]
    geometry={};blocked={}
    considered=[];chosen=None
    for mode,values in groups:
        for v in values:
            route=v['route']
            if route in blocked:continue
            try:
                if route not in geometry:
                    try:geometry[route]=route_geometry(navigator,route,root)
                    except (RuntimeError,ValueError,KeyError) as error:
                        blocked[route]=str(error);excluded.append(dict(route=route,reason=str(error)));continue
                v['geo']=geometry[route]
                for m in owned:
                    if m['uid'] not in v['matrix']:v['matrix'][m['uid']]=rows(m,route)
                plan,actual=build_roster(inventory,dict(cfg,**({'_primary_mentor':v['mentor']} if mode=='assisted' else {})),v['route'],root,v['geo'],v['matrix'],mode)
                actual['_speed']=(world or {}).get('speed',config.get('_speed',1));forecast=forecast_cycle(plan,actual,root,v['geo'],evidence)
            except (ValueError,RuntimeError,KeyError) as error:
                considered.append(dict(route=v['route'],mode=mode,reason=str(error)));continue
            current={m['uid'] for m in inventory.get('party',[])};desired=set(plan['team_uids']);transfers=len(current-desired)+len(desired-current)
            prep=v['geo']['preparation_seconds']+transfers*PRIORS['pc_member'];forecast.update(preparation_seconds=prep,eta_game_seconds=prep+forecast['remaining_game_seconds'],preparation_steps=v['geo']['preparation_steps'])
            plan['forecast']=forecast;plan['navigation']=v['geo'];chosen=plan;break
        if chosen:break
    if chosen is None:raise PlanningUnavailable([*excluded,*considered] or [dict(route=v['route'],reason=t('training.coverage_rejected',coverage=round(v['value']*100),hits=hit_limit(cfg))) for v in available])
    labels={'direct':f"Маршрут ученика: ≥{MIN_LEARNER_COVERAGE:.0%} встреч за {hit_limit(cfg)} попадания или быстрее",'assisted':'Сильнейший доступный боевой помощник; максимум XP за встречу среди маршрутов с полным покрытием одним попаданием'}
    chosen['selection']=dict(mode=requested,version=VERSION,training_mode=chosen['training_mode'],reason=labels[chosen['training_mode']],alternatives=[dict(route=v['route'],target_coverage=v['value'],difficulty=catalog(root)['routes'][v['route']]['difficulty'],selected=v['route']==chosen['route']) for v in sorted(available,key=lambda v:difficulty(v['route'],root))],excluded=excluded,roster_exclusions=considered)
    return attach(chosen)
