"""Reusable ordinary-button navigation, PC and local hunting in a main-save copy."""
from .acquisition_play import Player,AcquisitionAttention
from .engine import BUTTONS
from .telemetry import read_map,read_field_badges
from .models import read_inventory
from .navigation import Navigator,safe_grass_pair
from .catalog import catalog
from .capture import SLEEP_MOVES

class DirectBot:
    def __init__(self,player):self.p=player;self.project_dir=player.g.root
    def state(self):return self.p.state()
    def map(self,name=None):return read_map(self.p.g,name)
    def inventory(self):return read_inventory(self.p.g)
    def press(self,button,frames=2,release_frames=1):self.p.advance(frames,sum(BUTTONS[k] for k in button.split('+')));self.p.advance(release_frames)
    def wait_frames(self,frames):self.p.advance(frames)
    def event(self,code,message,**details):self.p.w.event(code,dict(details,message=message))
    def checkpoint(self,name):return str(self.p.checkpoint('journey-'+__import__('uuid').uuid4().hex))

class Journey(Player):
    def __init__(self,game,worker):
        super().__init__(game,worker);self.root=game.root;self.bot=DirectBot(self);self.trainee=None
        self.nav=Navigator(self);inv=self.bot.inventory();inv['field_badges']=read_field_badges(game);self.nav.configure_tools(inv,'party')
    # The navigator supplies these guards for each portal; the starter player
    # predates them. Validate them before taking ordinary movement steps.
    def transition(self,key,destination,*,source=None,point=None,encounters='escape'):
        s=self.state()
        if source is not None and s['map']['name']!=source:raise AcquisitionAttention('Изменилась карта перехода')
        if point is not None and (s['position']['x'],s['position']['y'])!=tuple(point):raise AcquisitionAttention('Изменилась точка перехода')
        return super().transition(key,destination,encounters=encounters)
    def mon(self,state,uid):
        from .training import RouteTrainer
        return RouteTrainer.mon(self,state,uid)
    def party_select(self,*args,**kwargs):
        from .training import RouteTrainer
        return RouteTrainer.party_select(self,*args,**kwargs)
    def lead(self,uid):
        from .training import RouteTrainer
        return RouteTrainer.lead(self,uid)
    def go(self,*args,**kwargs):
        result=super().go(*args,**kwargs)
        s=self.state()
        if not s['in_battle'] and not s['controls']['field_locked']:self.w.safe_point()
        return result
    def wait(self,frames=10):self.advance(frames)
    def expect_interaction(self,*_):pass
    def wait_for(self,predicate,limit=900):
        for _ in range(limit//6):
            s=self.state()
            if predicate(s):return s
            self.advance(6)
        raise AcquisitionAttention('Не завершилось действие в игровом меню')
    def center(self):
        """Travel to the nearest clinic and ensure recovery before returning its hub."""
        key,_=self.nav.nearest_clinic();hub=self.nav.spec['hubs'][key];self.nav.travel(hub['map'],hub['nurse']);self.heal();return hub
    def ensure_party(self,uid):
        from .storage import Storage
        inv=self.bot.inventory()
        if any(m['uid']==uid for m in inv['party']):return
        if not any(m['uid']==uid for m in inv['boxes']):raise AcquisitionAttention('Выбранный Pokémon больше не найден')
        storage=Storage(self)
        if len(inv['party'])>=6:
            # Reversible PC deposit, never a release or overwrite.
            candidates=[m for m in inv['party'] if not m.get('is_egg') and not 121<=m.get('held_item',0)<=132]
            chosen=min(candidates,key=lambda m:(m.get('shiny',False),m['level'],m['slot']))
            self.w.event('temporary_party_space',dict(uid=chosen['uid'],species=chosen['species']));storage.deposit(chosen['uid'])
        storage.withdraw(uid)
    def hunt(self,species_id=0,shiny=False,route=None,*,hunter_uid=None):
        inventory=self.bot.inventory();before={m['uid'] for m in inventory['party']+inventory['boxes']}
        if not self.ball_count():raise AcquisitionAttention('Нужны обычные Poké Ball в сумке; сначала купи их')
        if hunter_uid:
            self.capture_policy='venusaur';self.capture_hunter=hunter_uid
            if not self.state()['in_battle']:self.lead(hunter_uid)
        current=self.state()['map']['name'];routes=catalog(self.root)['routes']
        if route is None:
            from .editions import edition
            route=current if current in routes else 'Route101' if edition(self.root).family=='hoenn' else 'Route1'
        if route not in routes or species_id and not any(m['species_id']==species_id for m in routes[route]['population']):raise AcquisitionAttention('Выбранный Pokémon не встречается на указанном маршруте')
        self.w.update(stage='Ищем Pokémon · '+route)
        if self.state()['in_battle']:
            if current!=route:raise AcquisitionAttention('Сначала закончи текущий бой; маршрут отличается')
        else:
            if any(m['hp']<m['max_hp']*.5 or m.get('status_code') for m in self.state()['party'] if m['hp']>0):self.center()
            self.nav.travel(route)
        farm=safe_grass_pair(read_map(self.g),(self.state()['position']['x'],self.state()['position']['y']),terrain=routes[route].get('terrain','grass'))
        for step in range(100000):
            s=self.state()
            if s['in_battle']:
                enemies=(s.get('battle')or{}).get('enemies',[]);enemy=enemies[0] if enemies else None
                # Do not inspect stale enemy RAM during the battle transition.
                if s['controls']['controllers'][0]!='HandleInputChooseAction':self.tap('B' if s['controls']['controllers'][0]=='HandleInputChooseMove' else 'A');continue
                wanted=enemy and (not species_id or enemy['species_id']==species_id) and (not shiny or enemy['shiny'])
                if wanted:
                    if hasattr(self.w,'record_encounter'):self.w.record_encounter(enemy)
                    self.w.update(stage='Pokémon найден · сохраняем встречу и ловим',status='capturing')
                    self.battle('catch');after=self.bot.inventory();found=[m for m in after['party']+after['boxes'] if m['uid'] not in before]
                    if found:
                        mon=found[0]
                        if species_id and mon['species_id']!=species_id or shiny and not mon['shiny']:raise AcquisitionAttention('Не совпал пойманный Pokémon')
                        self.checkpoint('caught-'+mon['uid'].replace(':','-'),permanent=True);self.persist();self.w.event('local_pokemon_caught',dict(pokemon=mon));return mon
                    raise AcquisitionAttention('Не подтверждён пойманный Pokémon в команде или PC')
                if hasattr(self.w,'record_encounter'):self.w.record_encounter(enemy)
                self.battle('escape');continue
            if hunter_uid:
                hunter=next(m for m in s['party'] if m['uid']==hunter_uid)
                pp={m['id']:m['current_pp'] for m in hunter['moves']}
                offensive=sum(m['current_pp'] for m in hunter['moves'] if m.get('power',0)>0)
                if hunter['hp']<hunter['max_hp']*.65 or hunter.get('status_code') or max((pp.get(n,0) for n in SLEEP_MOVES),default=0)<3 or offensive<6:
                    self.w.update(status='preparing',stage='Возвращаем охотника на лечение')
                    self.center();self.lead(hunter_uid);self.nav.travel(route)
                    farm=safe_grass_pair(read_map(self.g),(self.state()['position']['x'],self.state()['position']['y']),terrain=routes[route].get('terrain','grass'))
                    self.w.update(status='searching',stage='Ищем Pokémon · '+route)
            self.go(farm['pair'][step%2],encounters='local')
            self.w.safe_point()
        raise AcquisitionAttention('Поиск приостановлен: достигнут лимит шагов')
