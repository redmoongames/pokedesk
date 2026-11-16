"""Versioned, bounded training forecasts. Pure snapshots; no emulator or Tk access.

The resource model is deliberately approximate. Forecasts retain their components,
calibration sources and assumptions; evaluations never rewrite an earlier forecast.
"""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import json
import math
import sqlite3

from .catalog import catalog, species, experience_reward, move
from .mechanics import ranked_attacks, wild_mon
from .navigation import Navigator
from .planning import make_plan, route_matchups, routes_for
from .run_context import RunConfig, build_context, team_fingerprint, context_complete, digest
from .zones import zone_spec
from .automatic_speed import AUTO_RATES,automatic_rates

class PlanningUnavailable(ValueError):
    def __init__(self,excluded):
        self.excluded=excluded
        super().__init__('Не удалось подобрать доступный маршрут и команду. Подробности — «Почему этот маршрут».')

MODEL_VERSION='eta-two-hit-pp-v2'
FPS=59.727500569606
# Game seconds, including ordinary bot menu/text handling. These are priors,
# not measured constants. A complete compatible cycle calibrates the whole model.
PRIORS=dict(step=20/FPS,transition=2.,heal=16.,search=8.,battle=14.,attack=6.,switch=8.,lead=7.,pc_member=8.,teleport=12.)
FAILURES={'battle_lost','training_timeout','unexpected_battle','unexpected_dialog','unexpected_scene','escape_failed','script_failed','script_error','training_blocked'}

def map_names(root):
    spec=zone_spec(root)
    return sorted({e[k] for e in spec['links'] for k in ('source','destination')})

def world_key(world):
    from .planning_state import geometry_key
    return digest([geometry_key(world),world.get('revision',0),world.get('speed',1)])

class SnapshotNavigator(Navigator):
    """Maps are immutable for one request; reuse all local-path searches."""
    def reset(self):pass
    def plan(self,*args,**kwargs):
        kwargs.setdefault('diagnose',False)
        return super().plan(*args,**kwargs)

def snapshot_navigator(root,world):
    from .planning_state import planning_world
    world=planning_world(world)
    def read(name=None):return world['grids'].get(name or world['state']['map']['name'])
    nav=SnapshotNavigator(SimpleNamespace(root=root,bot=SimpleNamespace(map=read),state=lambda:world['state']))
    nav.planning_world=world
    return nav

def read_evidence(root):
    """Read-only SQL, never History(): it would open a timeline/end active runs."""
    from .paths import session_paths
    path=session_paths(root).profile.journal
    if not path.exists():return dict(cycles=[],battles=[])
    try:
        with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=.5) as db:
            db.row_factory=sqlite3.Row
            cycles=[]
            for row in db.execute('SELECT c.*,r.route,r.target_uid,r.strategy FROM training_cycles c JOIN training_runs r ON c.run_id=r.id WHERE c.ended_at IS NOT NULL ORDER BY c.id DESC LIMIT 2000'):
                r=dict(row);r['body']=json.loads(r['body']);cycles.append(r)
            battles=[];by_run={}
            for cycle in cycles:by_run.setdefault(cycle['run_id'],[]).append(cycle)
            for row in db.execute('SELECT id,detail FROM battles ORDER BY id DESC LIMIT 2000'):
                b=json.loads(row['detail']);b['_record_id']=row['id']
                if b.get('outcome')==1 and not b.get('interrupted') and b.get('run_id') and b.get('frames',0)>0:
                    owner=next((c for c in by_run.get(b['run_id'],[]) if c['start_frame']<=b['start'] and (c['end_frame'] or 0)>=b['start']+b['frames']),None)
                    speeds={i['speed'] for i in owner['body'].get('speed_intervals',[])} if owner else set()
                    b['_speed']=next(iter(speeds)) if len(speeds)==1 else None;battles.append(b)
            return dict(cycles=cycles,battles=battles)
    except (sqlite3.Error,ValueError):return dict(cycles=[],battles=[],unavailable=True)

def compatible_cycles(plan,config,root,farm,evidence):
    context=build_context(root,config,plan);fingerprint=plan['team_fingerprint'];rows=[]
    for row in evidence.get('cycles',[]):
        body=row['body'];old=body.get('context')
        if not context_complete(old):continue
        if row['route']!=plan['route'] or row['target_uid']!=plan['trainee']:continue
        if body.get('team_base_fingerprint')!=fingerprint:continue
        if any(old.get(k)!=context.get(k) for k in ('rules','versions','roles')):continue
        speeds={i['speed'] for i in body.get('speed_intervals',[])}
        if config.get('auto_speed'):
            if body.get('automatic_speed_interrupted') or not speeds or not speeds <= automatic_rates(config.get('max_auto_speed',12)):continue
        elif speeds!={config.get('_speed',1)}:continue
        if body.get('clinic')!=farm['hub'] or body.get('area')!=[list(p) for p in farm['pair']]:continue
        if row.get('game_seconds',0)>0:rows.append(row)
    return rows

def remaining_xp(target,goal,root):
    curve=catalog(root)['growth'][species(target['species_id'],root)['growth']]
    return max(0,curve[int(goal)]-target['experience'])

def cycle_geometry(nav,farm,root):
    """Walking always remains verified. Teleport is an optional return shortcut."""
    actions=len(farm.get('field_actions',[]))*8
    total=farm['cost'][1]*PRIORS['step']+farm['cost'][0]*.08*18+actions
    out=farm.get('outbound_cost');back=farm.get('return_cost')
    outbound=(out[1]*PRIORS['step']+out[0]*.08*18+actions/2) if out else total/2
    result=dict(farm=farm,travel_seconds=total,outbound_seconds=outbound,walk_return_seconds=max(0,total-outbound))
    from .field_teleport import destinations,OUTDOOR_TYPES
    destination=destinations(root).get(farm['hub']);hub=zone_spec(root)['hubs'][farm['hub']]
    if destination and nav.grid(farm['map']).get('map_type') in OUTDOOR_TYPES:
        try:
            entrance=nav.plan(destination['map'],destination['point'],hub['map'],hub['nurse'])
            result['teleport_return_seconds']=PRIORS['teleport']+entrance['cost'][1]*PRIORS['step']+len(entrance['links'])*PRIORS['transition']+entrance['cost'][0]*.08*18+len(entrance.get('field_actions',[]))*8
        except (ValueError,RuntimeError):pass
    return result

def route_geometry(nav,route,root):
    cache=getattr(nav,'planning_cache',None)
    if cache is not None:
        return cache.route_geometry(nav,route,root,lambda:_route_geometry(nav,route,root))
    return _route_geometry(nav,route,root)

def _route_geometry(nav,route,root):
    farm=nav.choose_farm(route);hub=zone_spec(root)['hubs'][farm['hub']]
    nearest,first=nav.nearest_clinic((hub['map'],hub['nurse']),before_preparation=True);near=zone_spec(root)['hubs'][nearest]
    onward=nav.plan(near['map'],near['nurse'],hub['map'],hub['nurse'])
    prep_steps=first['cost'][1]+onward['cost'][1]
    prep_transitions=len(first['links'])+len(onward['links'])
    prep_grass=first['cost'][0]+onward['cost'][0]
    # Include menu swaps, three heals (same clinic may be visited twice), and
    # possible escape encounters on the one-time journey.
    prep=prep_steps*PRIORS['step']+prep_transitions*PRIORS['transition']+3*PRIORS['heal']+prep_grass*.08*18
    actions=[*farm.get('field_actions',[]),*first.get('field_actions',[]),*onward.get('field_actions',[])]
    required=sorted({a['tool'] for a in actions})
    prep+=(len(onward.get('field_actions',[]))+len(first.get('field_actions',[])))*8
    return dict(cycle_geometry(nav,farm,root),required_tools=required,field_actions=actions,preparation_seconds=prep,preparation_steps=prep_steps,preparation_grass=prep_grass,nearest_clinic=nearest)

def forecast_cycle(plan,config,root,geometry,evidence=None):
    """Expected-encounter depletion of HP/PP, bounded to 128 encounters.

    Every species/level slot keeps its encounter weight. Wild stats and incoming
    damage are approximations. We model the existing adaptive battle policy.
    """
    evidence=evidence or dict(cycles=[],battles=[]);team=deepcopy(plan['team']);mons={m['uid']:m for m in team};uid=plan['trainee'];target=mons[uid]
    for m in team:
        m.update(hp=m['max_hp'],status_code=0,stages={})
        for a in m['moves']:a['current_pp']=a.get('max_pp',a.get('pp',0))
    hp={m['uid']:float(m['max_hp']) for m in team};pp={(m['uid'],a['id']):float(a['current_pp']) for m in team for a in m['moves']}
    threshold=config.get('heal_percent',40)/100;ko=config.get('target_ohko_threshold',.9)
    enemies=[];tables={};incoming={}
    for entry in catalog(root)['routes'][plan['route']]['mons']:
        for level in range(entry['min_level'],entry['max_level']+1):
            foe=wild_mon(entry['species_id'],level,root);weight=entry['weight']/100/(entry['max_level']-entry['min_level']+1);key=(entry['species_id'],level)
            enemies.append((key,foe,weight))
            for m in team:
                tables[m['uid'],key]=sorted([dict(r,effect_name=move(r['move_id'],root).get('effect_name')) for _,r in ranked_attacks(m,foe,root)],key=lambda r:(-r.get('ohko_on_hit',0),-r['accuracy'],r['turns']) if config.get('training_policy')=='coverage' else (-r['ohko'],r['turns'],-r['mean']))
                incoming[m['uid'],key]=max((r['mean'] for _,r in ranked_attacks(foe,m,root)),default=0)*.6
    items=catalog(root)['items'];share=sum(items.get(str(m.get('held_item',0)))=='EXP. SHARE' for m in team);item=items.get(str(target.get('held_item',0)))
    xp=0.;seconds=0.;battles=0;switches=0.;actions=0.;transferred=set();historical={}
    for index,b in enumerate(evidence.get('battles',[])):
        if b.get('_speed')!=config.get('_speed',1):continue
        enemies_seen=list(b.get('enemies',{}).values());gain=next((g for g in b.get('gains',[]) if g['uid']==uid),None)
        participants=sum(g.get('xp',0)>0 for g in b.get('gains',[]))
        if gain and abs(gain.get('from_level',0)-target['level'])<=1 and len(enemies_seen)==1:
            e=enemies_seen[0];historical.setdefault((e['species_id'],e['level'],participants),[]).append((index,b['frames']/FPS))
    from .combat_policy import finish_plan,hit_limit,route_resources
    def usable(u,key):
        if hp[u]<mons[u]['max_hp']*threshold:return None
        options=tables[u,key];available={a['id']:pp[u,a['id']] for a in mons[u]['moves']}
        if config.get('training_policy')=='coverage':
            limit=hit_limit(config) if u==uid else 1
            choice=finish_plan(options,available,next(foe['hp'] for k,foe,_ in enemies if k==key),limit)
            if choice:return choice
            if u==uid or u==plan.get('primary_mentor'):return None
        return next((r for r in options if pp[u,r['move_id']]>=1),None)
    tactical=config.get('training_approach','legacy')!='legacy'
    for _ in range(128):
        if config.get('training_policy')=='coverage' and plan['strategy']=='adaptive':
            guard=plan.get('primary_mentor') or uid;probe=dict(mons[guard],moves=[dict(a,current_pp=pp[guard,a['id']]) for a in mons[guard]['moves']])
            resource=route_resources(probe,plan['route'],root,dict(config,allow_two_hits=False) if plan.get('primary_mentor') else config,threshold=1 if plan.get('primary_mentor') else .8)
            if resource['depleted']:break
        choices=[];skipped=0
        for key,foe,weight in enemies:
            if tactical:
                from .training_tactics import choose
                # Depletion is an expectation and can be fractional. The live
                # battle policy needs whole usable actions; never invent an
                # extra attack by rounding the remaining budget upwards.
                party=[dict(m,hp=hp[u],moves=[dict(a,current_pp=max(0,int(pp[u,a['id']]))) for a in m['moves']]) for u,m in mons.items()]
                current=next(m for m in party if m['uid']==uid)
                decision=choose(dict(party=party,battle=dict(enemies=[foe])),current,uid,root,mode=plan.get('tactic','careful'),mentor=plan.get('primary_mentor'),fighters=set(plan['fighters']))
                if decision is None:skipped+=weight;continue
                best_u=decision['mon']['uid'];best=next((r for r in tables[best_u,key] if r['move_id']==decision['mon']['moves'][decision['index']]['id']),None)
                if best:choices.append((key,foe,weight,best_u,best))
                continue
            own=usable(uid,key) if uid in plan['fighters'] else None
            options=[(u,usable(u,key)) for u in plan['fighters']];options=[(u,r) for u,r in options if r]
            if not options:break
            if config.get('training_policy')=='coverage':
                helpers=[(u,r) for u,r in options if u!=uid]
                best_u,best=min(helpers or options,key=lambda p:(-p[1].get('ohko_on_hit',0),p[1]['turns'],incoming[p[0],key]/mons[p[0]]['max_hp']))
                primary=next(((u,r) for u,r in helpers if u==plan.get('primary_mentor')),None)
                if primary:best_u,best=primary
                if own and own.get('certified_hits') and plan.get('training_mode')!='assisted':best_u,best=uid,own
            else:
                best_u,best=min(options,key=lambda p:(-p[1]['ohko'],p[1]['turns'],incoming[p[0],key]/mons[p[0]]['max_hp'],-hp[p[0]]/mons[p[0]]['max_hp']))
                if own and (own['ohko']>=ko or (own['ohko']>=best['ohko'] and own['turns']<=best['turns']+1)):best_u,best=uid,own
            if plan['strategy']=='switch' and best_u==uid:break
            choices.append((key,foe,weight,best_u,best))
        if not choices or not tactical and len(choices)!=len(enemies):break
        if tactical:seconds+=skipped*(PRIORS['search']+PRIORS['battle'])
        for key,foe,weight,attacker,attack in choices:
            switched=attacker!=uid;turns=attack['turns'];parts=2 if switched else 1
            reward=experience_reward(species(foe['species_id'],root)['base_xp'],foe['level'],participants=parts,share_holders=share,exp_share=item=='EXP. SHARE',lucky_egg=item=='LUCKY EGG',traded=target.get('traded',False))
            battle_time=PRIORS['battle']+turns*PRIORS['attack']+switched*(PRIORS['switch']+PRIORS['lead'])
            similar=historical.get((*key,parts),[])[:12]
            if similar:
                battle_time=(battle_time*3+sum(v for _,v in similar))/(3+len(similar));transferred.update(i for i,_ in similar)
            xp+=weight*reward;seconds+=weight*(PRIORS['search']+battle_time);switches+=weight*switched;actions+=weight*turns
            if attack.get('pp_costs'):
                by_move={r['move_id']:r for r in tables[attacker,key]}
                for move_id,count in attack['pp_costs'].items():pp[attacker,move_id]=max(0,pp[attacker,move_id]-weight*count/max(.001,by_move[move_id]['accuracy']))
            else:pp[attacker,attack['move_id']]=max(0,pp[attacker,attack['move_id']]-weight*turns)
            if switched:hp[uid]-=weight*incoming[uid,key]
            hits=max(0,turns-1)+int(foe['stats']['speed']>=mons[attacker]['stats']['speed'])
            hp[attacker]-=weight*incoming[attacker,key]*hits
        battles+=1
        if hp[uid]<target['max_hp']*threshold:break
    if not battles or xp<=0:raise ValueError('Команда не покрывает противников с доступными атакующими приёмами')
    from .field_tools import knows
    method='teleport' if geometry.get('teleport_return_seconds') is not None and any(knows(m,100) for m in plan['team']) else 'walk'
    outward=geometry.get('outbound_seconds',geometry['travel_seconds']/2)
    returning=geometry['teleport_return_seconds'] if method=='teleport' else geometry.get('walk_return_seconds',geometry['travel_seconds']/2)
    travel=outward+returning;heal=PRIORS['heal'];base_seconds=seconds+travel+heal
    model=dict(target_xp=xp,game_seconds=base_seconds,battles=battles)
    rows=[r for r in compatible_cycles(plan,config,root,geometry['farm'],evidence) if r['body'].get('return_method',(r['body'].get('forecast') or {}).get('return_method','walk'))==method];complete=[r for r in rows if r['status']=='completed'];failed=[r for r in rows if r['status'].removeprefix('partial:') in FAILURES]
    # Two predicted cycles as a weak prior; aggregate rewards and time, never
    # average per-cycle rates. Legacy/incompatible cycles cannot enter this sum.
    n=len(complete);denom=n+2
    target_xp=(2*xp+sum(r['target_xp'] or 0 for r in complete))/denom
    duration=(2*base_seconds+sum(r['game_seconds'] for r in complete)+sum(r['game_seconds'] for r in failed))/denom
    count=(2*battles+sum(r['battles'] or 0 for r in complete))/denom
    remaining=remaining_xp(target,config['target'],root);rate=target_xp*60/max(1,duration)
    # Fractional final cycle: no unnecessary return to Center after reaching goal.
    cycles=remaining/max(1,target_xp);full=max(0,math.ceil(cycles)-1);tail=min(1,max(0,cycles-full))
    eta=full*duration+tail*max(0,duration-returning-heal)
    context=build_context(root,config,plan)
    return dict(version=MODEL_VERSION,route=plan['route'],trainee=uid,team_fingerprint=plan['team_fingerprint'],rules=context['rules'],versions=context['versions'],
        target_xp=target_xp,game_seconds=duration,battles=count,xp_game_minute=rate,remaining_xp=remaining,start_xp=target['experience'],remaining_game_seconds=eta,speed=config.get('_speed',1),
        return_method=method,components=dict(travel_seconds=travel,outbound_seconds=outward,return_seconds=returning,heal_seconds=heal,search_seconds=battles*PRIORS['search'],battle_seconds=seconds-battles*PRIORS['search'],expected_switches=switches,expected_attacks=actions),
        model=model,evidence=dict(exact_cycles=n,failed_cycles=len(failed),transferred_battles=len(transferred),legacy_cycles=sum(not context_complete(r['body'].get('context')) for r in evidence.get('cycles',[]))),
        clinic=geometry['farm']['hub'],area=[list(p) for p in geometry['farm']['pair']],
        source_ids=dict(cycles=[r['id'] for r in complete],failures=[r['id'] for r in failed],battles=[evidence['battles'][i].get('_record_id') for i in sorted(transferred)]),
        assumptions='Приближённые HP/PP, нейтральные дикие Pokémon; рост характеристик и новые приёмы до цели не предсказаны. Пересчёт после цикла. Исторические бои — другие условия.')

def make_training_plan(inventory,config,root,*,navigator=None,evidence=None,cache=None):
    """Choose an attainable route and one of two bounded helper rosters."""
    cfg=RunConfig.parse(config).as_dict()
    if cfg['training_approach']!='legacy':
        from .training_tactics import plan
        return plan(inventory,cfg,root,navigator=navigator,evidence=evidence,cache=cache)
    if cfg['training_policy']=='coverage':
        from .coverage import make_coverage_plan
        return make_coverage_plan(inventory,config,root,navigator=navigator,evidence=evidence,cache=cache)
    requested=cfg['route'];world=inventory.get('_planning')
    contract=None
    if cfg.get('final_moves'):
        from .move_plan import compile_plan
        trainee=next((m for m in inventory.get('party',[])+inventory.get('boxes',[]) if m['uid']==cfg['trainee']),None)
        if trainee is None:raise ValueError('Выбери Pokémon для плана приёмов')
        contract=compile_plan(trainee,cfg['target'],cfg['final_moves'],root,cfg['evolution_mode'])
    def attach(plan):
        if contract:
            plan['move_plan']=contract;plan['warnings']+=contract['warnings']
            from .catalog import move
            if any(not any(move(n,root).get('power',0)>0 for n in step['after']) for step in contract['steps']):
                if not any(u!=plan['trainee'] for u in plan['fighters']):raise ValueError('Для набора без атакующих приёмов нужен боевой помощник')
        return plan
    if navigator is None and world:navigator=snapshot_navigator(root,world).configure_tools(inventory)
    if cache is not None and hasattr(navigator,'planning_world'):navigator.planning_cache=cache
    if navigator is None:
        if requested=='Auto':raise ValueError('Дождись проверки карт и доступных переходов')
        return attach(make_plan(inventory,cfg,root))
    evidence=read_evidence(root) if evidence is None else evidence
    candidates=[];excluded=[];owned=[m for m in inventory.get('party',[])+inventory.get('boxes',[]) if m.get('checksum_valid') and not m.get('is_egg')]
    for route in routes_for(root) if requested=='Auto' else (requested,):
        try:
            geometry=route_geometry(navigator,route,root);actual=dict(cfg,route=route,_required_tools=geometry.get('required_tools',[]),_speed=(world or {}).get('speed',config.get('_speed',1)))
            scores={m['uid']:route_matchups(m,route,root) for m in owned};baseline=make_plan(inventory,actual,root,scores=scores)
            alternatives=[baseline];eligible=[m for m in owned if m['uid'] not in (baseline['trainee'],baseline['runner']) and any(r['mean']>0 for r in scores[m['uid']])]
            def endurance(m):
                rows=scores[m['uid']];pp=sum(a.get('max_pp',a.get('pp',0)) for a in m['moves'] if a.get('power',0)>0)
                return (-sum(r['weight']*r['ohko'] for r in rows)/(1+sum(r['weight']*r['turns'] for r in rows)/100),-pp,m['uid'])
            ids=[m['uid'] for m in sorted(eligible,key=endurance)[:4]]
            if set(ids)!=set(baseline['reserves'] if cfg['strategy']!='switch' else baseline['fighters']):
                try:alternatives.append(make_plan(inventory,actual,root,helper_uids=ids,scores=scores))
                except ValueError:pass
            for plan in alternatives:
                forecast=forecast_cycle(plan,actual,root,geometry,evidence)
                current={m['uid'] for m in inventory.get('party',[])};desired=set(plan['team_uids']);transfers=len(current-desired)+len(desired-current)
                prep=geometry['preparation_seconds']+transfers*PRIORS['pc_member']
                forecast.update(preparation_seconds=prep,eta_game_seconds=prep+forecast['remaining_game_seconds'],preparation_steps=geometry['preparation_steps'])
                plan['forecast']=forecast;plan['_geometry']=geometry;candidates.append(plan)
        except (RuntimeError,ValueError,KeyError) as error:excluded.append(dict(route=route,reason=str(error)))
    if not candidates:raise PlanningUnavailable(excluded)
    candidates.sort(key=lambda p:(p['forecast']['eta_game_seconds'],-p['forecast']['xp_game_minute'],p['route']))
    best=candidates[0];best['navigation']=best.pop('_geometry',None)
    trainee=next(m for m in best['team'] if m['uid']==best['trainee']);known={a['id'] for a in trainee['moves']}
    choices=[r['level'] for r in species(trainee['species_id'],root)['learnset'] if trainee['level']<r['level']<=cfg['target'] and r['move'] not in known]
    if not contract and len(known)>=4 and choices:best['warnings'].append(f"На Lv {min(choices)} возможен выбор нового приёма: бот вернёт управление. Время твоего решения в прогноз не входит.")
    best['selection']=dict(mode=requested,version=MODEL_VERSION,reason='Минимальное прогнозируемое время до цели с учётом перехода и подготовки',
        alternatives=[dict(route=p['route'],team_uids=p['team_uids'],eta_game_seconds=p['forecast']['eta_game_seconds'],xp_game_minute=p['forecast']['xp_game_minute'],exact_cycles=p['forecast']['evidence']['exact_cycles']) for p in candidates[:8]],excluded=excluded)
    return attach(best)
