"""Game actions use the normal Bot SDK and production domain services only."""
import json
import time
from collections import defaultdict
from .model import require, signature, atomic_json

FEAROW='ee83a314:67042a97'
KADABRA='ee83a314:df868df5'
BULBA='ee83a314:16a309dd'
MAGIKARP='ee83a314:25de551a'


def field(s):
    c=s['controls']
    return not s['in_battle'] and c['callback']=='CB2_Overworld' and not c['field_locked'] and not c['moving']


def trainer(bot, target=FEAROW, grind=False):
    from pokemon_red.training import RouteTrainer
    from pokemon_red.grind import GrindTrainer
    s=bot.state()
    t=(GrindTrainer if grind else RouteTrainer)(bot,dict(trainee=target,target=100,
        fighters=[m['uid'] for m in s['party']],auto_team=grind,heal_percent=20,route='DiglettsCave_B1F'))
    t.want_heal=False;t.runner=KADABRA;t.route='DiglettsCave_B1F'
    return t


def walk(bot, spec):
    t=trainer(bot);before=t.state();require(field(before),'walk requires open field')
    for _ in range(10):t.go((12,18));t.go((12,8))
    after=t.state();require(field(after),'walk did not settle');require(signature(after)==signature(before),'walk changed final state')
    return dict(units=200)


def menu(bot, spec):
    t=trainer(bot);before=t.state()
    for _ in range(6):
        for uid in (FEAROW,KADABRA):
            t.lead(uid);require(t.state()['party'][0]['uid']==uid,'wrong party leader')
    after=t.state();require(field(after),'party menu remained open');require(signature(after)==signature(before),'party order or resources changed')
    return dict(units=12)


def rpc(bot, spec):
    before=bot.state()
    for _ in range(4000):
        s=bot.state();require(s['map']==before['map'] and s['position']==before['position'],'RPC changed map/coordinates')
    return dict(units=4000)


def battle(bot, spec):
    t=trainer(bot);before=t.state();enemy=before['battle']['enemies'][0]
    require(before['in_battle'] and enemy['species_id']==41,'wrong battle fixture')
    t.fight();after=t.state();require(field(after),'battle did not finish')
    a=next(m for m in before['party'] if m['uid']==FEAROW);b=next(m for m in after['party'] if m['uid']==FEAROW)
    require(b['experience']-a['experience']==54*enemy['level']//7,'wrong XP reward')
    require(b['hp']==a['hp'] and b['status_code']==a['status_code'],'unexpected battle damage/status')
    require(b['moves'][0]['id']==64 and b['moves'][0]['current_pp']==a['moves'][0]['current_pp']-1,'Peck was not used exactly once')
    return dict(units=1)


def portals(bot, spec):
    from pokemon_red.navigation import Navigator
    t=trainer(bot);nav=Navigator(t);before=t.state()
    for _ in range(2):
        for name,point in (('Route4',(12,18)),('Route4_PokemonCenter_1F',(7,4))):
            plan=nav.travel(name,point);require(plan['cost'][0]==0,'dry portal path crossed encounters')
    after=t.state();require(field(after),'portal transition did not settle');require(signature(after)==signature(before),'portal final state mismatch')
    return dict(units=4)


def complex_travel(bot, spec):
    from pokemon_red.navigation import Navigator
    t=trainer(bot);nav=Navigator(t);before=t.state()
    require(before['map']['name']=='Route5','complex route must start on Route5')
    # A dry round trip exercises the graph without encounter-count noise.
    plan=nav.travel('VermilionCity_PokemonCenter_1F',(7,4))
    at_center=t.state();require(field(at_center) and at_center['map']['name']=='VermilionCity_PokemonCenter_1F','outward complex route failed')
    returned=nav.travel('Route5',(before['position']['x'],before['position']['y']))
    after=t.state();require(field(after),'complex route did not settle')
    require(after['map']==before['map'] and after['position']==before['position'],'wrong complex route return destination')
    require(len(plan['links'])>=5 and len(returned['links'])>=5,'complex route did not exercise multiple directed nodes')
    require(plan['cost'][0]==returned['cost'][0]==0,'fixed complex route crossed encounter terrain')
    require({m['uid'] for m in after['party']}=={m['uid'] for m in before['party']},'complex route changed roster')
    return dict(units=len(plan['links'])+len(returned['links']),planned_encounter_tiles=plan['cost'][0]+returned['cost'][0])


def heal(bot, spec):
    from pokemon_red.grind import recovery_reasons
    t=trainer(bot,MAGIKARP,grind=True);t.preparing=True
    require(bool(recovery_reasons(t.state())),'heal fixture is already healthy')
    require(t.heal_here() is True,'first heal was skipped')
    healed=signature(t.state())
    bot.event('check_repeats_start','Healthy repeat calls must send no input')
    for _ in range(3):require(t.heal_here() is False,'healthy party was healed twice')
    require(signature(t.state())==healed and not recovery_reasons(t.state()),'heal did not restore party')
    return dict(units=1,healthy_repeats=3)


def trap(bot, spec):
    from pokemon_red.battle_conditions import switch_blockers
    t=trainer(bot,MAGIKARP,grind=True);t.preparing=False
    require('arena_trap' in switch_blockers(t.state()),'fixture has no Arena Trap')
    t.fight();after=t.state();require(field(after),'trapped battle did not finish')
    require(any(m['hp']>0 for m in after['party']),'whole team lost')
    require(next(m for m in after['party'] if m['uid']==MAGIKARP)['hp']==0,'expected trapped learner faint did not occur')
    return dict(units=1)


def faint(bot, spec):
    t=trainer(bot,MAGIKARP,grind=True);t.preparing=False
    before=t.state();require(next(m for m in before['party'] if m['uid']==MAGIKARP)['hp']==0,'learner is not fainted')
    t.fight(retreat=True);after=t.state();require(field(after),'faint/replacement did not return to field')
    require(any(m['hp']>0 for m in after['party']),'no survivor after replacement')
    return dict(units=1)


def poison_faint(bot,spec):
    t=trainer(bot);s=t.state()
    require(field(s),'known poison notification did not recover')
    require(any(m['hp']==0 for m in s['party']),'fainted member disappeared or was silently healed')
    return dict(units=1)


def learning(bot,spec):
    t=trainer(bot,BULBA);t.fight();s=t.state();mon=next(m for m in s['party'] if m['uid']==BULBA)
    require(field(s),'learning battle did not complete')
    require([m['id'] for m in mon['moves']]==[33,77,73,22],'wrong final move slots')
    require(not s.get('decision'),'learning prompt remains')
    return dict(units=2)


def learning_attention(bot,spec):
    # The per-frame guard must intercept this attempt before any A is applied.
    bot.press('A',frames=120)
    raise AssertionError('unapproved choice was allowed')


def takeover(bot,spec):
    while True:bot.press('B',frames=3600)


def prepare_trap(bot,spec):
    from pokemon_red.grind import GrindTrainer
    from pokemon_red.field_tools import choose_runner
    from pokemon_red.storage import Storage
    inv=bot.inventory();target=next(m for m in inv['boxes'] if m['species_id']==129)
    desired=[target['uid']]+[m['uid'] for m in inv['party'] if m['species_id']!=56]
    t=GrindTrainer(bot,dict(auto_team=True,trainee=target['uid'],target=100,fighters=desired,route='DiglettsCave_B1F'))
    t.plan={'team_uids':desired};t.runner=choose_runner(inv['party'],target['uid'])['uid'];t.preparing=True;t.navigator.configure_tools(inv)
    Storage(t).assemble(desired);t.heal_here();t.navigator.configure_tools(bot.inventory(),'party');t.travel_lead()
    t.farm=t.navigator.choose_farm(t.route);t.clinic=t.farm['hub'];t.navigator.travel('VermilionCity_PokemonCenter_1F',(7,4));t.heal_here();t.preparing=False;t.to_grass()
    for _ in range(60):
        s=t.state()
        if s['in_battle']:t.fight()
        s=t.state()
        if next(m for m in s['party'] if m['uid']==target['uid'])['hp']==0:
            t.heal();return dict(units=1)
        if t.need_heal(s):t.heal();t.to_grass()
        t.lead(target['uid']);p=t.state()['position'];here=(p['x'],p['y']);t.go(t.farm_pair[1] if here==t.farm_pair[0] else t.farm_pair[0],search=True)
    raise AssertionError('natural trapped faint not found')


CASES={f.__name__:f for f in (walk,menu,rpc,battle,portals,complex_travel,heal,trap,faint,poison_faint,learning,learning_attention,takeover,prepare_trap)}


def run(bot):
    spec=json.loads((bot.project_dir/'Data/check-case.json').read_text());call=bot._call
    samples=defaultdict(list)
    def measured(method,**args):
        at=time.perf_counter()
        try:return call(method,**args)
        finally:samples[method].append(time.perf_counter()-at)
    bot._call=measured
    try:
        bot.safety_profile('training')
        if spec['kind']!='learning':bot.event('check_start','Fixed scenario starts',case=spec['id'])
        result=CASES[spec['kind']](bot,spec)
        bot.event('check_complete','Native postconditions verified',case=spec['id'],**result)
    finally:atomic_json(bot.project_dir/'Data/check-rpc.json',samples)
