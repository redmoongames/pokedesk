"""Reviewable travel reachability and ordinary-button main-game journeys."""
from pathlib import Path
from types import SimpleNamespace
from .navigation import Navigator
from .travel_policy import eligible_trainers,trainer_grid
from .training import RouteTrainer,TrainingProblem,trainer_zones
from .location_reference import reference
from .locations import location_name
from .run_context import digest


def goal_for(spec,name):return next((h['nurse'] for h in spec['hubs'].values() if h['map']==name),None)
def strongest(party):return max((m for m in party if m.get('hp',0)>0 and not m.get('is_egg')),key=lambda m:(m['level'],m.get('stats',{}).get('attack',0)+m.get('stats',{}).get('special_attack',0)),default=None)

def navigator(root,state,inventory,provider,allow=False):
    def grid(name):
        raw=provider(name)
        return trainer_grid(raw,[t['trainer_id'] for t in eligible_trainers(raw)]) if allow else raw
    t=SimpleNamespace(root=Path(root),bot=SimpleNamespace(map=grid),state=lambda:state)
    return Navigator(t).configure_tools(inventory)


def battle_requirements(nav,trip,provider):
    found={}
    for leg in trip['legs']:
        name=leg['source'];point=leg['start'];plan=leg['plan'];parts=[]
        for edge in plan['links']:
            parts.append((name,nav.local_path(name,point,edge['point'])));name,point=edge['destination'],edge['arrival']
        if leg['goal'] is not None:parts.append((name,nav.local_path(name,point,leg['goal'])))
        for name,path in parts:
            points=set(map(tuple,path));raw=provider(name)
            for trainer in eligible_trainers(raw):
                if not trainer.get('defeated') and points&trainer_zones(dict(raw,trainers=[trainer])):found.setdefault(name,set()).add(trainer['trainer_id'])
    return {name:sorted(ids) for name,ids in found.items()}


def destination_plan(nav,permitted,provider,inventory,name,allow=False):
    state=nav.t.state();label=location_name(name)
    if name==state['map']['name']:return dict(name=name,label=label,reachable=False,reason='Вы уже в этой локации',current=True)
    leader=strongest(inventory.get('party',[]))
    if leader is None:return dict(name=name,label=label,reachable=False,reason='В отряде нет боеспособного Pokémon')
    preferred=[m['uid'] for m in sorted(inventory['party']+inventory.get('boxes',[]),key=lambda m:-m['level']) if m.get('checksum_valid',True) and not m.get('is_egg')]
    goal=goal_for(nav.spec,name);trip=None;reason='';chosen=nav
    try:trip=nav.itinerary(name,goal,pinned=[leader['uid']],preferred=preferred)
    except (RuntimeError,ValueError) as error:reason=str(error)
    if trip is None:
        try:other=permitted.itinerary(name,goal,pinned=[leader['uid']],preferred=preferred)
        except (RuntimeError,ValueError):other=None
        if other is not None:
            needed=battle_requirements(permitted,other,provider)
            if needed and not allow:return dict(name=name,label=label,reachable=False,reason='Путь перекрыт обзором тренеров. Включите «Сражаться с NPC на пути».',can_battle=True,battles=sum(map(len,needed.values())))
            if allow:trip=other;chosen=permitted
    if trip is None:return dict(name=name,label=label,reachable=False,reason=reason or 'Нет проверенного безопасного пути')
    needed=battle_requirements(chosen,trip,provider) if chosen is permitted else {}
    return dict(name=name,label=label,reachable=True,reason='',goal=goal,steps=sum(l['plan']['cost'][1] for l in trip['legs']),tools=sorted({t for l in trip['legs'] for t in l['required_tools']}),battles=sum(map(len,needed.values())),trainer_ids=needed,legs=[{k:v for k,v in l.items() if k!='plan'} for l in trip['legs']],preferred=preferred,pinned=[leader['uid']])


def destinations(root,state,inventory,provider,allow=False):
    nav=navigator(root,state,inventory,provider);permitted=navigator(root,state,inventory,provider,True)
    reviewed={e[k] for e in nav.spec['links'] for k in ('source','destination')};rows=[]
    for name in reference(root)['maps']:
        if name==state['map']['name']:rows.append(dict(name=name,label=location_name(name),reachable=False,reason='Вы уже в этой локации',current=True))
        elif name not in reviewed:rows.append(dict(name=name,label=location_name(name),reachable=False,reason='Переходы к этой карте пока не проверены для автопутешествия'))
        else:rows.append(destination_plan(nav,permitted,provider,inventory,name,allow))
    issue='' if state['map']['name'] in reviewed else 'Для текущей локации ещё не добавлены переходы автопутешествия. Это ограничение навигации приложения, а не вашего прогресса в игре.'
    return dict(origin=state['map']['name'],position=state['position'],allow_trainers=allow,rows=rows,origin_issue=issue)

def reachability_summary(result):
    if result.get('origin_issue'):return result['origin_issue']
    count=sum(r['reachable'] for r in result['rows']);battles=sum(bool(r.get('can_battle')) for r in result['rows'])
    text=f'Проверено · доступно {count} локаций'
    if battles:text+=f' · ещё {battles} при разрешении боёв с NPC'
    if not count:text+=' · выберите локацию, чтобы увидеть препятствие'
    return text


class TravelBot:
    def __init__(self,bot,allowed):self.raw=bot;self.project_dir=bot.project_dir;self.allowed=allowed;self.installed=None
    def __getattr__(self,name):return getattr(self.raw,name)
    def map(self,name=None):
        raw=self.raw.map(name);ids=self.allowed.get(raw['name'],[])
        if name is None and self.installed!=(raw['name'],tuple(ids)):
            self.raw.travel_policy(raw['name'],ids);self.installed=(raw['name'],tuple(ids))
        return trainer_grid(raw,ids)


class Traveler(RouteTrainer):
    def __init__(self,bot,config):
        s=bot.state();leader=strongest(s['party'])
        if not leader:raise ValueError('В отряде нет боеспособного Pokémon')
        super().__init__(bot,dict(trainee=leader['uid'],fighters=[m['uid'] for m in s['party']],target=100,heal_percent=40))
        self.preparing=True;self.want_heal=False;self.route='Автопутешествие';self.travel_config=config;self.runner=None
        self.navigator=Navigator(self)
    def handoff(self,code,message,**details):
        self.bot.set_speed(0)
        return super().handoff(code,message,**details)
    def state(self):
        s=self.bot.state()
        if not s.get('telemetry_valid',True):self.bot.wait_frames(2);return self.bot.state()
        c=s.get('controls',{})
        if self.interaction=='travel' and c.get('callback')=='CB2_Overworld' and c.get('field_locked') and not s.get('travel_guard',{}).get('scene'):
            if c.get('message_box') or c.get('field_script_native')=='WaitForMovementFinish':self.handoff('travel_unknown_scene','На пути неизвестный диалог или сюжетная сцена. Продолжите вручную.')
        return s
    def trainer_permission(self,s):return bool(self.travel_config.get('allow_trainers') and s.get('travel_guard',{}).get('battle'))
    def healthy_fighters(self,s):return [m for m in s['party'] if m['hp']>0 and not m.get('is_egg')]
    def choose_fighter(self,s):
        from .mechanics import ranked_attacks,incoming_risk
        enemies=(s.get('battle')or{}).get('enemies',[])
        if not enemies:return None
        choices=[]
        for m in self.healthy_fighters(s):
            attacks=ranked_attacks(m,enemies[0],self.root)
            if attacks:choices.append((m['hp']/m['max_hp']<.4,attacks[0][1]['turns'],incoming_risk(m,enemies[0],self.root),-m['hp'],m['uid'],m))
        return min(choices,key=lambda p:p[:-1])[-1] if choices else None
    def travel_lead(self):
        leader=strongest(self.state()['party'])
        if not leader:raise TrainingProblem('no_living_pokemon','Нет боеспособного Pokémon для дороги')
        self.lead(leader['uid'])
    def heal_here(self):
        from .grind import GrindTrainer
        return GrindTrainer.heal_here(self)
    def settle_trainer(self):
        deadline=self.state()['frame']+6000
        while self.state()['frame']<deadline:
            s=self.state()
            if s['in_battle']:self.fight(retreat=False,travel=True);return
            if not s['controls']['field_locked']:return
            if s.get('travel_guard',{}).get('scene'):self.tap('A',wait=12)
            else:self.wait(6)
        raise TrainingProblem('trainer_approach_timeout','Тренер не начал ожидаемый бой')
    def go(self,*args,**kwargs):
        for _ in range(20):
            self.bot.map() # Install permission for this exact map before movement.
            try:return super().go(*args,**kwargs)
            except TrainingProblem as error:
                s=self.state()
                if error.code=='walking_interrupted' and (s.get('travel_guard',{}).get('scene') or s['in_battle']):self.settle_trainer();continue
                raise
        raise TrainingProblem('travel_retry_limit','Слишком много препятствий на участке')
    def fight(self,retreat=False,travel=False):
        s=self.state()
        if self.trainer_permission(s):
            self.bot.checkpoint('Автопутешествие · перед боем с NPC')
            self.bot.event('travel_trainer_battle','Обычный бой с тренером на пути',trainer_id=s['battle'].get('trainer_id'))
        return super().fight(retreat=retreat,travel=travel)
    def run(self):
        bot=self.bot;cfg=self.travel_config;bot.safety_profile('training');bot.expect_interaction('travel');state=self.state()
        if state['in_battle'] or state['controls']['field_locked']:raise ValueError('Сначала закончите бой или диалог')
        inventory=bot.inventory();provider=lambda name:bot.map(name)
        nav=navigator(self.root,state,inventory,provider);permitted=navigator(self.root,state,inventory,provider,True)
        row=destination_plan(nav,permitted,provider,inventory,cfg['destination'],cfg.get('allow_trainers',False))
        if not row['reachable']:raise TrainingProblem('travel_unavailable',row['reason'])
        bot.checkpoint('Перед автопутешествием · '+row['label'])
        self.bot=TravelBot(bot,row['trainer_ids']);self.bot.map()
        bot.manage_speed(cfg.get('auto_speed',True),max_speed=cfg.get('max_auto_speed',12))
        self.navigator=Navigator(self).configure_tools(inventory)
        self.stage('Путешествие · '+row['label']);self.travel_lead()
        result=self.navigator.travel_prepared(cfg['destination'],row['goal'],pinned=row['pinned'],preferred=row['preferred'])
        actual=self.state()
        if actual['map']['name']!=cfg['destination']:raise TrainingProblem('travel_wrong_map','Не подтверждена конечная локация')
        bot.checkpoint('Прибытие · '+row['label']);bot.set_speed(0);bot.event('travel_arrived','Прибыли: '+row['label'],destination=cfg['destination'],position=actual['position'])
        bot.handoff('travel_arrived','Прибыли: '+row['label']+'. Игра на паузе, управление у вас.')


def run_travel(bot):
    import json
    from .bot import ControlLost,HandedOff
    try:Traveler(bot,json.loads((bot.project_dir/'Data/travel.json').read_text())).run()
    except (ControlLost,HandedOff):raise
    except Exception as error:
        bot.set_speed(0);bot.handoff(getattr(error,'code','travel_error'),'Путешествие остановлено: '+str(error))
