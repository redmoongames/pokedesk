"""Build a role-based team using only currently owned live Pokémon."""
import hashlib
import json
from .catalog import catalog,species,experience_reward
from .mechanics import wild_mon,ranked_attacks,escape_info,incoming_risk

STRATEGIES={'adaptive':'Автоматический выбор бойца','switch':'Слабый Pokémon · с помощниками','solo':'Сильный Pokémon · самостоятельно'}
from .run_context import team_fingerprint,RunConfig
def __getattr__(name):
    if name == 'ROUTES':
        from .engine import ROOT
        return routes_for(ROOT)
    raise AttributeError(name)

def routes_for(root):
    from .zones import zone_spec
    return tuple(zone_spec(root)['zones'])

def fingerprint(team):
    return team_fingerprint(team)

def route_matchups(mon,route,root):
    mon=dict(mon,hp=mon['max_hp'],status_code=0,stages={},moves=[dict(a,current_pp=a.get('max_pp',a.get('pp',0))) for a in mon['moves']])
    result=[]
    for entry in catalog(root)['routes'][route]['mons']:
        for level in range(entry['min_level'],entry['max_level']+1):
            foe=wild_mon(entry['species_id'],level,root);ranked=ranked_attacks(mon,foe,root)
            best=ranked[0][1] if ranked else dict(turns=1000,ohko=0,move='Нет подходящей атаки',mean=0)
            result.append(dict(species=foe['species'],species_id=foe['species_id'],level=level,attacker=mon['nickname'],attacker_uid=mon['uid'],incoming_risk=incoming_risk(mon,foe,root),weight=entry['weight']/(entry['max_level']-entry['min_level']+1),**best))
    return result

def make_plan(inventory,config,root,*,helper_uids=None,scores=None):
    config=dict(config,**RunConfig.parse(config).as_dict())
    if not inventory.get('ready'):raise ValueError('Дождись загрузки сохранения')
    owned=[m for m in inventory.get('party',[])+inventory.get('boxes',[]) if m.get('checksum_valid') and not m.get('is_egg')]
    by_id={m['uid']:m for m in owned};uid=config.get('trainee');route=config.get('route','Route1');strategy=config.get('strategy','adaptive')
    from .zones import zone_spec
    if route not in zone_spec(root)['zones']:raise ValueError('Выбери поддерживаемую зону гринда из списка')
    if strategy not in STRATEGIES:raise ValueError('Выбери стратегию прокачки')
    if uid not in by_id:raise ValueError('Выбери Pokémon из команды или PC')
    target=by_id[uid];goal=int(config.get('target',15))
    if not 2<=goal<=100:raise ValueError('Целевой уровень: 2–100')
    if target['level']>=goal:raise ValueError('Целевой уровень уже достигнут')
    from .field_tools import choose_runner,knows
    runner=choose_runner([m for m in owned if m['uid']!=config.get('_primary_mentor')],uid);runner_uid=runner['uid'] if runner else None
    utilities=[]
    for tool in config.get('_required_tools',[]):
        if tool!='cut':raise ValueError('Неподдерживаемое полевое действие: '+tool)
        providers=[m for m in owned if knows(m,15)]
        provider=min(providers,key=lambda m:(m['uid'] not in (uid,runner_uid),m.get('location')!='party',-m['level'],m['uid']),default=None)
        if provider is None:raise ValueError('Для маршрута нужен Pokémon с Cut')
        if provider['uid'] not in {m['uid'] for m in utilities}:utilities.append(provider)
    scores=scores or {m['uid']:route_matchups(m,route,root) for m in owned}
    candidates=[m for m in owned if m['uid'] not in (uid,runner_uid) and any(r['mean']>0 for r in scores[m['uid']])]
    def cost(m):return sum(r['turns']*r['weight'] for r in scores[m['uid']])/100
    forced=[m for m in utilities if m['uid'] not in (uid,runner_uid) and any(r['mean']>0 for r in scores[m['uid']])]
    noncombat=[m for m in utilities if m['uid'] not in (uid,runner_uid) and m not in forced]
    helpers=list(forced);remaining=[m for m in candidates if m not in utilities];capacity=6-len({uid,*([runner_uid] if runner_uid else [])})-len(noncombat)
    if helper_uids is not None:
        eligible={m['uid']:m for m in candidates}
        if len(set(helper_uids))!=len(helper_uids) or len(helper_uids)>capacity or any(u not in eligible for u in helper_uids):raise ValueError('Некорректный состав помощников')
        helpers=[*forced,*[eligible[u] for u in helper_uids if u not in {m['uid'] for m in forced}]][:capacity]
    while helper_uids is None and remaining and len(helpers)<capacity:
        def score(candidate):
            squad=[*helpers,candidate]
            rows=[min((scores[m['uid']][i] for m in squad),key=lambda r:(r['turns'],-r['ohko'])) for i in range(len(scores[uid]))]
            return (-sum(r['ohko']*r['weight'] for r in rows)/100,sum(r['turns']*r['weight'] for r in rows)/100,max(r['turns'] for r in rows),cost(candidate),sum(r['incoming_risk']*r['weight'] for r in scores[candidate['uid']])/100,-candidate['max_hp'])
        chosen=min(remaining,key=score);helpers.append(chosen);remaining.remove(chosen)
    if strategy=='switch':
        if not helpers:raise ValueError('Нет помощника с подходящей атакой против диких Pokémon этого маршрута')
        fighters=helpers
        if any(all(scores[m['uid']][i]['mean']<=0 for m in fighters) for i in range(len(scores[uid]))):raise ValueError('Доступные помощники не покрывают всех противников зоны обычными атакующими приёмами')
    elif strategy=='solo':
        if any(r['mean']<=0 for r in scores[uid]):raise ValueError('У цели нет пригодных атак против всех видов маршрута. Выбери прокачку с помощниками.')
        fighters=[target]
    else:
        fighters=[target,*helpers]
        if any(all(scores[m['uid']][i]['mean']<=0 for m in fighters) for i in range(len(scores[uid]))):raise ValueError('У цели и резерва нет пригодной атаки против одного из видов зоны')
    team=list({m['uid']:m for m in [target,*([runner] if runner else []),*utilities,*helpers]}.values());warnings=[]
    if runner is None:warnings.append('Отдельного Pokémon для побега нет: обычный побег зависит от скорости и ограничений боя.')
    elif any(a['id']==100 for a in runner['moves']):warnings.append(runner['nickname']+' использует Teleport для побега; нужны PP, ловушки могут помешать.')
    if utilities:warnings.append('Для пути нужен Cut: '+', '.join(m['nickname'] for m in utilities))
    if len(team)<6:warnings.append(f'Команда {len(team)}/6: остальные доступные Pokémon не подходят или их недостаточно.')
    if strategy=='switch' and len(fighters)<2:warnings.append('Доступен только один помощник: возвращаемся лечиться до его потери.')
    if min(cost(m) for m in fighters)>2:warnings.append('Ожидается больше двух атак на бой; маршрут пока может быть неэффективен.')
    best_rows=[]
    for i in range(len(scores[uid])):
        own=scores[uid][i]
        best=own if strategy=='adaptive' and own['ohko']>=config['target_ohko_threshold'] else min((scores[m['uid']][i] for m in fighters),key=lambda r:(-r['ohko'],r['turns']))
        best_rows.append(best)
    attacks=sum(r['turns']*r['weight'] for r in best_rows)/100;ohko=sum(r['ohko']*r['weight'] for r in best_rows)/100
    items=catalog(root)['items'];share_holders=sum(items.get(str(m.get('held_item',0)))=='EXP. SHARE' for m in team);target_item=items.get(str(target.get('held_item',0)))
    if share_holders:warnings.append('В команде есть Exp. Share: учтено дополнительное разделение XP.')
    xp=0
    for row in catalog(root)['routes'][route]['mons']:
        for level in range(row['min_level'],row['max_level']+1):
            own=next((r for r in scores[uid] if r['species_id']==row['species_id'] and r['level']==level),None)
            participants=2 if strategy=='switch' or strategy=='adaptive' and own and own['ohko']<config['target_ohko_threshold'] and any(m['uid']!=uid for m in fighters) else 1
            xp+=experience_reward(species(row['species_id'],root)['base_xp'],level,participants=participants,share_holders=share_holders,exp_share=target_item=='EXP. SHARE',lucky_egg=target_item=='LUCKY EGG',traded=target.get('traded',False))*row['weight']/100/(row['max_level']-row['min_level']+1)
    return dict(route=route,strategy=strategy,trainee=uid,target=goal,runner=runner_uid,utility_uids=[m['uid'] for m in utilities],field_tools=list(config.get('_required_tools',[])),fighters=[m['uid'] for m in fighters],reserves=[m['uid'] for m in helpers] if strategy in ('solo','adaptive') else [],team=team,team_uids=[m['uid'] for m in team],warnings=warnings,matchups=best_rows,expected_attacks=attacks,expected_target_xp=xp,ohko_chance=ohko,team_fingerprint=fingerprint(team),escape=escape_info(runner),assumptions='Прогноз урона: IV 15, нейтральная природа, без погоды/предметов/критов. XP/мин измеряется по полным циклам, включая дорогу и лечение.')


def plan_preview(plan):
    """Bounded presentation snapshot for a running script, independent of setup UI."""
    keys=('route','strategy','trainee','target','runner','fighters','reserves','utility_uids','field_tools','team_uids','team_fingerprint','warnings','matchups','ohko_chance','assumptions')
    value={key:plan[key] for key in keys}
    value['team']=[{k:m.get(k) for k in ('uid','nickname','species_id','level','hp','location','box_name','shiny')} for m in plan['team']]
    for key in ('forecast','selection','move_plan','training_mode','primary_mentor','learner_max_hits','coverage','difficulty','tactic','effective_policy','keep_party','survivable_coverage'):
        if key in plan:value[key]=plan[key]
    return value
