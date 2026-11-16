"""Prepared teams and measured Center → grass → Center training cycles."""
from .training import RouteTrainer,TrainingProblem,ALLOWED,ROUTE2_TRANSIT,path_to,trainer_zones
from .planning import make_plan,plan_preview
from .mechanics import ranked_attacks,incoming_risk,wild_mon
from .catalog import catalog
from .storage import Storage
from .navigation import Navigator
from .zones import zone_spec,zone_label
from .engine import ROOT

LOCATIONS={e[k] for e in zone_spec()['links'] for k in ('source','destination')}
def locations(root):return {e[k] for e in zone_spec(root)['links'] for k in ('source','destination')}

def validate_start(state,root=ROOT):
    if not state.get('ready'):raise ValueError('Дождись загрузки игры')
    if state.get('in_battle'):raise ValueError('Сначала закончи текущий бой')
    if state['map']['name'] not in locations(root):raise ValueError('Начни в поддерживаемой зоне гринда, соседнем городе или Pokémon Center')
    c=state['controls']
    if c['callback']!='CB2_Overworld' or c['field_locked']:raise ValueError('Закрой меню и диалоги')
    if not any(m['hp']>0 for m in state['party']):raise ValueError('Нет живого Pokémon для дороги в Center')

def recovery_reasons(state):
    """Keep the training error contract around the shared, pure predicate."""
    from .healing import recovery_reasons as inspect_recovery,HealingTelemetryError
    try:return inspect_recovery(state)
    except HealingTelemetryError as error:raise TrainingProblem('healing_telemetry',str(error)) from error


class GrindTrainer(RouteTrainer):
    def __init__(self,bot,config):
        from .run_context import RunConfig
        config=dict(config,**RunConfig.parse(config).as_dict())
        super().__init__(bot,dict(config,fighters=config.get('fighters',[])))
        self.strategy=config.get('strategy','adaptive');self.route=config.get('route','Route1');self.runner=None;self.preparing=True;self.cycle_number=0;self.plan=None;self.clinic=None;self.farm=None;self.navigator=Navigator(self);self.requested_route=self.route;self.coverage_signature=None;self.training_session=None;self.run_id=None

    def check_events(self,s):
        # A boxed target is not in the party until preparation is complete.
        if self.preparing and not any(m['uid']==self.trainee for m in s['party']):
            if s.get('decision'):self.handoff('move_choice_required','Нужен выбор нового приёма. Реши его в окне игры.')
            if s.get('battle') and s['battle'].get('outcome') in (2,3,9):self.handoff('battle_lost','Команда проиграла во время подготовки.')
            from .encounter_safety import shiny_opponents
            if shiny_opponents(s):self.handoff('shiny_encounter','Встречен дикий shiny! Игра на паузе, управление у тебя.')
            return
        super().check_events(s)

    def resource_state(self,mon,*,mentor=False):
        from .combat_policy import route_resources,profile_key,hit_limit
        key=(self.route,profile_key(mon),tuple((a['id'],a.get('current_pp',a.get('pp',0))) for a in mon['moves']),1 if mentor else hit_limit(self.config),mentor)
        cache=getattr(self,'_resource_cache',{})
        if key not in cache:
            if len(cache)>12:cache.clear()
            cache[key]=route_resources(mon,self.route,self.root,dict(self.config,allow_two_hits=False) if mentor else self.config,threshold=1 if mentor else .8)
            self._resource_cache=cache
        return cache[key]

    def pp_recovery(self,s,target):
        if self.strategy!='adaptive' or getattr(self,'config',{}).get('training_policy')!='coverage':return False
        from .combat_policy import live_plan,hit_limit
        from copy import deepcopy
        primary=(getattr(self,'plan',None) or {}).get('primary_mentor')
        mon=self.mon(s,primary) if primary else target;resource=self.resource_state(mon,mentor=bool(primary));depleted=resource['depleted']
        enemies=(s.get('battle') or {}).get('enemies',[])
        if not primary and enemies and resource['full']+1e-9>=resource['threshold'] and not live_plan(target,enemies[0],self.root,hit_limit(self.config)):
            restored=deepcopy(target)
            for attack in restored['moves']:attack['current_pp']=attack.get('max_pp',attack.get('pp',0))
            depleted|=bool(live_plan(restored,enemies[0],self.root,hit_limit(self.config)))
        if not depleted:return False
        self.heal_cause=f"У {'помощника' if primary else 'ученика'} закончились нужные PP: покрытие {resource['current']:.0%}, требуется {resource['threshold']:.0%} за {resource['max_hits']} попадания или быстрее"
        if not self.want_heal:self.bot.event('pp_recovery_required',self.heal_cause,pokemon_uid=mon['uid'],route=self.route,**resource)
        self.want_heal=True
        # Finish an already winnable encounter, then heal before searching again.
        allies=(s.get('battle') or {}).get('allies',[])
        active=next((m for m in s['party'] if allies and m['slot']==allies[0]['party_slot']),None)
        if active and enemies and live_plan(active,enemies[0],self.root,1 if active['uid']!=self.trainee else hit_limit(self.config)):return False
        return True

    def need_heal(self,s):
        if self.preparing:return False
        target=self.mon(s,self.trainee);runner=self.mon(s,self.runner) if self.runner else None
        from .field_tools import teleport_slot,knows
        if runner and knows(runner,100) and teleport_slot(runner) is None:self.heal_cause='У Pokémon для побега закончились PP Teleport';return True
        if runner and (runner['hp']/max(1,runner['max_hp'])<max(.55,self.threshold) or runner['status']!='В норме'):self.heal_cause='Нужен запас HP и нормальный статус у Pokémon для побега';return True
        if target['hp']/max(1,target['max_hp'])<self.threshold or target['status']!='В норме':self.heal_cause='У цели низкие HP или изменён статус';return True
        primary=(getattr(self,'plan',None) or {}).get('primary_mentor')
        if primary:
            mentor=self.mon(s,primary)
            if mentor['hp']/max(1,mentor['max_hp'])<self.threshold or mentor['status']!='В норме':self.heal_cause='Основному помощнику нужно восстановление';return True
        if self.pp_recovery(s,target):return True
        # A reserve cannot save a depleted learner if Arena Trap prevents the
        # initial switch. Recover between encounters, before entering that trap.
        damaging=[a for a in target['moves'] if a.get('power')]
        if not s.get('in_battle') and damaging and not any(a['current_pp'] for a in damaging):
            from .battle_conditions import passive_switch_blockers
            from .catalog import species
            own=dict(target,types=target.get('type_ids') or species(target['species_id'],self.root)['type_ids'])
            enemies=[dict(hp=1,ability_id=ability) for row in catalog(self.root)['routes'][self.route]['mons']
                     for ability in species(row['species_id'],self.root)['abilities']]
            if passive_switch_blockers(own,enemies):
                self.heal_cause='Закончились атакующие PP у цели: на этом маршруте возможна блокировка замены'
                return True
        usable=[m for m in self.healthy_fighters(s) if m['hp']/max(1,m['max_hp'])>=self.threshold and m['status']=='В норме' and any(a['power'] and a['current_pp'] for a in m['moves'])]
        if not usable:self.heal_cause='У цели и резерва не осталось здорового бойца с атакой и PP';return True
        if self.strategy=='adaptive' and not s.get('in_battle'):
            # PP is checked across the whole reserve, not only the last attacker.
            threats={(r['species_id'],r['max_level']) for r in catalog(self.root)['routes'][self.route]['mons']}
            if any(not any(ranked_attacks(m,wild_mon(sp,lv,self.root),self.root) for m in usable) for sp,lv in threats):self.heal_cause='Из-за HP/PP резерв больше не покрывает все виды зоны';return True
        return False

    def attack_rows(self,mon,enemy):
        rows=ranked_attacks(mon,enemy,self.root)
        if self.config.get('training_policy')=='coverage':return sorted(rows,key=lambda p:(-p[1].get('ohko_on_hit',0),-p[1]['accuracy'],p[1]['turns']))
        return sorted(rows,key=lambda p:(-p[1]['ohko'],p[1]['turns'],-p[1]['mean'])) if self.strategy=='adaptive' else rows

    def attack_choice(self,mon,enemy):
        if self.config.get('training_approach','legacy')!='legacy':
            from .battle_strategy import attack_plan
            plan=attack_plan(mon,enemy,self.root)
            return plan['index'] if plan else None
        if self.config.get('training_policy')=='coverage':
            from .combat_policy import live_plan,hit_limit
            choice=live_plan(mon,enemy,self.root,hit_limit(self.config) if mon['uid']==self.trainee else 1)
            if choice:return choice['index']
        rows=self.attack_rows(mon,enemy)
        return rows[0][0] if rows else None

    def battle_fighter(self,s,current):
        if self.strategy!='adaptive':return super().battle_fighter(s,current)
        if self.config.get('training_approach','legacy')!='legacy':
            from .training_tactics import choose
            decision=choose(s,current,self.trainee,self.root,mode=(self.plan or {}).get('tactic','careful'),mentor=(self.plan or {}).get('primary_mentor'),fighters=self.fighters)
            if not decision:
                from .i18n import t
                self.want_heal=True;self.heal_cause=t('training.no_safe_fighter');return None
            self.bot.event('training_duel_decision','Training survival',pokemon_uid=decision['mon']['uid'],critical_bound=decision['critical'],damage_budget=decision['budget'],hits=decision['hits'],switch=bool(current and current['uid']!=decision['mon']['uid']))
            return decision['mon']
        if self.config.get('training_policy')=='coverage':return self.coverage_fighter(s,current)
        enemy=s['battle']['enemies'][0]
        good=lambda m:m and m['uid'] in self.fighters and m['hp']/max(1,m['max_hp'])>=self.threshold and m['status']=='В норме'
        own=self.attack_rows(current,enemy) if good(current) else []
        # Keep a healthy helper already fighting: switching again costs a turn.
        if own and (current['uid']!=self.trainee or own[0][1]['ohko']>=self.config['target_ohko_threshold']):chosen=current;rows=own;reason='target_one_hit' if current['uid']==self.trainee else 'continue_reserve'
        else:
            chosen=self.choose_fighter(s)
            if chosen is None:return None
            rows=self.attack_rows(chosen,enemy);reason='reserve_counter'
            if own and chosen['uid']!=current['uid'] and own[0][1]['ohko']>=rows[0][1]['ohko'] and own[0][1]['turns']<=rows[0][1]['turns']+1:chosen=current;rows=own;reason='avoid_unnecessary_switch'
        row=rows[0][1]
        self.bot.event('combat_decision',f"{chosen['nickname']}: {row['move']} · шанс KO {row['ohko']:.0%}",pokemon_uid=chosen['uid'],enemy=enemy['species'],reason=reason,move_id=row['move_id'],ohko=row['ohko'],expected_attacks=row['turns'],switch=bool(current and current['uid']!=chosen['uid']))
        return chosen

    def coverage_fighter(self,s,current):
        enemy=s['battle']['enemies'][0]
        healthy=lambda m:m['uid'] in self.fighters and m['hp']/max(1,m['max_hp'])>=self.threshold and m['status']=='В норме'
        choices=[]
        for mon in s['party']:
            if not healthy(mon):continue
            rows=self.attack_rows(mon,enemy)
            if rows:choices.append((mon,rows[0][1]))
        if not choices:return None
        own=next((r for m,r in choices if current and m['uid']==current['uid']),None)
        from .combat_policy import live_plan,hit_limit
        primary=(getattr(self,'plan',None) or {}).get('primary_mentor');assisted=(getattr(self,'plan',None) or {}).get('training_mode')=='assisted'
        finish=live_plan(current,enemy,self.root,hit_limit(self.config)) if current and current['uid']==self.trainee and own and not assisted else None
        mentor=next(((m,r) for m,r in choices if m['uid']==primary),None)
        if finish:chosen=current;row=finish
        elif mentor:chosen,row=mentor
        elif own and current['uid']!=self.trainee and own.get('ohko_on_hit',0)>=1-1e-10:chosen=current;row=own
        else:
            # Switch the learner out whenever it cannot guarantee a one-hit KO
            # against the live HP/defenses. A reserve also accounts for accuracy.
            alternatives=[(m,r) for m,r in choices if m['uid']!=self.trainee]
            if not alternatives:alternatives=choices
            chosen,row=min(alternatives,key=lambda p:(p[1].get('ohko_on_hit',0)<1-1e-10,-p[1].get('ohko_on_hit',0),p[1]['turns'],incoming_risk(p[0],enemy,self.root)))
            if current and current['uid']!=self.trainee and own and row.get('ohko_on_hit',0)<=own.get('ohko_on_hit',0) and own['turns']<=row['turns']+1:chosen=current;row=own
        outcome=f"до {row['certified_hits']} попаданий" if row.get('certified_hits') else f"KO при попадании {row.get('ohko_on_hit',0):.0%}"
        self.bot.event('combat_decision',f"{chosen['nickname']}: {row['move']} · {outcome} · точность {row['accuracy']:.0%}",pokemon_uid=chosen['uid'],enemy=enemy['species'],reason='learner_two_hits' if chosen['uid']==self.trainee and row.get('certified_hits')==2 else 'coverage_policy',certified_hits=row.get('certified_hits'),move_id=row['move_id'],ohko_on_hit=row.get('ohko_on_hit',0),accuracy=row['accuracy'],ohko=row['ohko'],switch=bool(current and current['uid']!=chosen['uid']))
        return chosen

    def choose_fighter(self,s):
        enemies=(s.get('battle') or {}).get('enemies',[])
        if not enemies:return None
        candidates=[]
        for mon in self.healthy_fighters(s):
            if mon['hp']/max(1,mon['max_hp'])<self.threshold or mon['status']!='В норме':continue
            ranks=self.attack_rows(mon,enemies[0])
            if ranks:
                row=ranks[0][1];primary=(-row.get('ohko_on_hit',0),row['turns']) if self.config.get('training_policy')=='coverage' else (-row['ohko'],row['turns']) if self.strategy=='adaptive' else (row['turns'],-row['ohko'])
                candidates.append((*primary,incoming_risk(mon,enemies[0],self.root),-mon['hp']/mon['max_hp'],mon))
        return min(candidates,key=lambda r:r[:-1])[-1] if candidates else None

    def travel_lead(self):
        s=self.state();runner=next((m for m in s['party'] if m['uid']==self.runner and m['hp']>0),None)
        if runner:self.lead(runner['uid'])
        elif self.runner is None or self.preparing or self.want_heal:
            mon=max((m for m in s['party'] if m['hp']>0),key=lambda m:m.get('stats',{}).get('speed',0),default=None)
            if mon:self.lead(mon['uid'])
            else:raise TrainingProblem('no_living_pokemon','В команде не осталось живых Pokémon')
        else:raise TrainingProblem('runner_fainted','Pokémon для побега без сознания. Возьми управление.')

    def heal_here(self):
        s=self.state();hubs=zone_spec(self.root)['hubs'];hub=next((h for h in hubs.values() if h['map']==s['map']['name']),None)
        if hub is None:raise TrainingProblem('healing_location','Лечение ожидается в поддерживаемом Pokémon Center')
        reasons=recovery_reasons(s)
        if not reasons:
            self.want_heal=False
            self.bot.event('healing_skipped','Лечение не требуется: HP, статусы и PP восстановлены',purpose='preparation' if self.preparing else 'cycle',team_uids=[m['uid'] for m in s['party']])
            return False
        self.go(tuple(hub['nurse']));self.expect_interaction('healing')
        self.bot.event('healing_started','Лечим команду',purpose='preparation' if self.preparing else 'cycle',reasons=reasons)
        self.tap('UP');self.tap('A');saw_lock=False
        for _ in range(700):
            s=self.state();saw_lock|=s['controls']['field_locked']
            if saw_lock and not s['controls']['field_locked'] and not recovery_reasons(s):break
            self.tap('A',wait=12)
        else:raise TrainingProblem('healing_timeout','Center не подтвердил полное лечение')
        self.want_heal=False;self.expect_interaction('travel')
        self.bot.event('healing_completed','HP, статусы и PP восстановлены',purpose='preparation' if self.preparing else 'cycle',team_uids=[m['uid'] for m in s['party']]);self.stage('Команда вылечена')
        return True

    def prepare_lucky_egg(self,*,allow_pc=False):
        if getattr(self,'config',{}).get('training_approach','legacy')=='legacy' or not self.config.get('equip_lucky_egg',True) or not hasattr(self.bot,'training_item'):return False
        from .i18n import t
        inventory=self.bot.inventory();owned=inventory.get('party',[])+inventory.get('boxes',[]);target=next((m for m in inventory.get('party',[]) if m['uid']==self.trainee),None)
        if not target or target.get('held_item')==197:return False
        if 121<=target.get('held_item',0)<=132:self.bot.event('training_item_skipped',t('training.item_mail'));return False
        bag=sum(r['quantity'] for r in inventory.get('training_items',[]) if r.get('pocket')=='items')
        holder=next((m for m in owned if m.get('held_item')==197),None)
        if not bag:
            if not holder:return False
            party={m['uid'] for m in inventory['party']}
            if holder['uid'] not in party:
                if not allow_pc or (self.plan or {}).get('keep_party'):return False
                desired=list(self.plan['team_uids']);temporary=list(desired)
                if len(temporary)>=6:temporary=[u for u in temporary if u!=self.trainee][:4]+[self.trainee]
                Storage(self).assemble([*temporary,holder['uid']]);self.bot.training_item(holder['uid'],take=True);Storage(self).assemble(desired)
            else:self.bot.training_item(holder['uid'],take=True)
        target=next(m for m in self.state()['party'] if m['uid']==self.trainee)
        if target.get('held_item'):self.bot.training_item(self.trainee,take=True)
        self.bot.training_item(self.trainee)
        if next(m for m in self.state()['party'] if m['uid']==self.trainee).get('held_item')!=197:raise TrainingProblem('training_item_mismatch',t('training.item_changed'))
        self.bot.event('training_item_ready','Lucky Egg',pokemon_uid=self.trainee,item_id=197);return True

    def prepare_at_clinic(self):
        self.stage('Подготовка: собираем команду · '+zone_label(self.route,self.root))
        if not self.plan.get('keep_party'):Storage(self).assemble(self.plan['team_uids'])
        changed=self.prepare_lucky_egg(allow_pc=True)
        self.heal_here()
        if changed:
            inventory=self.bot.inventory();by_id={m['uid']:m for m in inventory['party']+inventory.get('boxes',[])}
            self.plan['team']=[by_id[u] for u in self.plan['team_uids']]
            from .run_context import team_fingerprint
            self.plan['team_fingerprint']=team_fingerprint(self.plan['team']);self.record_run(getattr(self,'run_id',None))

    def heal(self):
        if self.clinic is None:self.clinic,_=self.navigator.nearest_clinic()
        if not self.preparing:self.bot.event('healing_needed',getattr(self,'heal_cause','Возвращаемся на лечение'),clinic=self.clinic,party=[dict(uid=m['uid'],hp=m['hp'],max_hp=m['max_hp'],status=m['status'],pp=[a['current_pp'] for a in m['moves']]) for m in self.state()['party']])
        self.want_heal=True;hub=zone_spec(self.root)['hubs'][self.clinic];self.stage('Лечение · '+hub['label'])
        result=self.bot.teleport_to_clinic(self.clinic) if hasattr(self.bot,'teleport_to_clinic') else dict(teleported=False)
        self.bot.event('return_to_clinic','Возврат к Center: Teleport' if result['teleported'] else 'Возврат к Center пешком',clinic=self.clinic,method='teleport' if result['teleported'] else 'walk',reason=result.get('reason'))
        if not result['teleported']:
            if self.state()['in_battle']:self.fight(retreat=True)
            self.travel_lead()
        # Teleport lands outside the Center. Walking finishes the verified
        # remaining entrance path, or the full route when Teleport was skipped.
        self.navigator.travel(hub['map'],hub['nurse']);self.heal_here()
        if not self.preparing and self.cycle_number:self.bot.event('cycle_complete','Цикл завершён: вернулись и вылечились',number=self.cycle_number,clinic=self.clinic,area=self.farm_pair)

    def to_grass(self):
        if not self.farm:
            self.farm=self.navigator.choose_farm(self.route);self.clinic=self.farm['hub']
        self.travel_lead();self.stage('Идём к месту боя · '+zone_label(self.route,self.root))
        self.navigator.travel(self.farm['map'],self.farm['entry']);grid=self.bot.map()
        # Revalidate against live positions when we enter the destination map.
        from .navigation import safe_grass_pair
        record=zone_spec(self.root)['zones'][self.route]
        from .field_tools import party_cut
        grid=party_cut(grid,self.state()['party'])
        chosen=safe_grass_pair(grid,self.farm['entry'],record.get('bounds'),record.get('terrain','grass'));self.grass=tuple(chosen['pair'][0]);self.farm_pair=tuple(tuple(p) for p in chosen['pair'])
        self.farm.update(pair=chosen['pair'],strip=chosen['strip'],length=chosen['length'],continuous=chosen['continuous'])
        dry=[p for p in chosen['path'] if not grid['tiles'][p[1]][p[0]][3]]
        if dry:self.go(dry[-1])
        self.lead(self.trainee);self.bot.event('grind_area_selected',zone_label(self.route,self.root)+f" · участок {chosen['length']} клеток",route=self.route,tiles=self.farm_pair,strip=chosen['strip'],length=chosen['length'],continuous=chosen['continuous'],clinic=self.clinic)
        self.go(self.grass,search=True)

    def begin_cycle(self):
        from .optimizer import forecast_cycle,read_evidence,cycle_geometry
        from .planning import fingerprint
        state=self.state();self.config['_speed']=max(.000001,state.get('session',{}).get('speed',1));team=state['party'];plan=dict(self.plan,team=team,team_fingerprint=fingerprint(team))
        geometry=cycle_geometry(self.navigator,self.farm,self.root)
        from .field_teleport import destinations
        if (state.get('field_teleport') or {}).get('landing')!=destinations(self.root).get(self.clinic):geometry.pop('teleport_return_seconds',None)
        forecast=forecast_cycle(plan,self.config,self.root,geometry,read_evidence(self.root))
        forecast['issued_frame']=state['frame']
        self.cycle_number+=1;self.bot.event('cycle_start',f'Цикл {self.cycle_number}: выходим из Center',number=self.cycle_number,clinic=self.clinic,area=self.farm['pair'] if self.farm else self.farm_pair,forecast=forecast)

    def planning_snapshot(self):
        from .map_repository import lazy_world
        inventory=self.bot.inventory();snapshot=self.state()
        return dict(inventory,_planning=lazy_world(snapshot,inventory.get('navigation_revision'),self.bot.map,speed=max(.000001,snapshot.get('session',{}).get('speed',1))))

    def coverage_key(self):
        m=self.mon(self.state(),self.trainee)
        return (m['level'],m['species_id'],tuple(a['id'] for a in m['moves']))

    def record_run(self,parent=None):
        import uuid
        from .run_context import build_context
        self.training_session=self.training_session or uuid.uuid4().hex;self.run_id=uuid.uuid4().hex
        self.bot.event('training_run_start','Подготовка команды и маршрута',run_id=self.run_id,training_session=self.training_session,parent_run_id=parent,context=build_context(self.root,self.config,self.plan),preview=plan_preview(self.plan),forecast=self.plan.get('forecast'),selection=self.plan.get('selection'),**{k:self.plan[k] for k in ('route','strategy','trainee','target','team_fingerprint','team_uids')})

    def maybe_replan(self):
        if self.requested_route!='Auto' or (self.plan or {}).get('keep_party'):return False
        if self.config.get('training_approach','legacy')=='legacy' and self.config.get('training_policy')!='coverage':return False
        key=self.coverage_key()
        if key==self.coverage_signature:return False
        from .optimizer import make_training_plan,PlanningUnavailable
        inventory=self.planning_snapshot()
        try:plan=make_training_plan(inventory,dict(self.config,route='Auto'),self.root)
        except PlanningUnavailable as error:
            self.coverage_signature=key
            self.bot.event('training_replan_deferred','Новый маршрут пока не подобран; продолжаем текущий',route=self.route,reasons=error.excluded)
            return False
        self.coverage_signature=key
        old_mode=self.plan.get('training_mode');new_mode=plan.get('training_mode')
        # Graduation from assisted training requires the learner coverage threshold.
        if self.config.get('training_approach','legacy')=='legacy' and old_mode=='assisted' and new_mode!='direct':return False
        if plan['route']==self.route and new_mode==old_mode:return False
        if self.plan.get('move_plan'):plan['move_plan']=self.plan['move_plan']
        old_route=self.route;parent=self.run_id;self.plan=plan;self.runner=plan['runner'];self.fighters=set(plan['fighters']);self.route=plan['route'];self.config['route']=self.route;self.config['training_policy']=plan.get('effective_policy',self.config.get('training_policy','coverage'))
        self.bot.event('training_replanned','Пересчёт после повышения уровня: '+zone_label(old_route,self.root)+' → '+zone_label(self.route,self.root),old_route=old_route,route=self.route,old_mode=old_mode,training_mode=new_mode,target_coverage=plan.get('coverage',{}).get('target'),parent_run_id=parent)
        self.preparing=True;self.want_heal=True
        self.record_run(parent);self.navigator.configure_tools(inventory);self.prepare_at_clinic();self.navigator.configure_tools(self.bot.inventory());self.travel_lead()
        self.farm=self.navigator.choose_farm(self.route);self.clinic=self.farm['hub'];self.farm_pair=tuple(tuple(p) for p in self.farm['pair']);hub=zone_spec(self.root)['hubs'][self.clinic]
        if self.state()['map']['name']!=hub['map']:self.navigator.travel(hub['map'],hub['nurse']);self.heal_here()
        self.preparing=False;self.cycle_number=0;self.bot.event('preparation_complete','Команда и новый маршрут готовы',route=self.route,strategy=self.strategy,clinic=self.clinic,area=self.farm['pair']);return True

    def run(self):
        if hasattr(self.bot,'safety_profile'):self.bot.safety_profile('training')
        from .prepared_plan import resolve_plan
        from .planning_state import PlanningCache
        validate_start(self.state(),self.root);self.prepare_lucky_egg();inventory=self.planning_snapshot();validate_start(self.state(),self.root)
        self.plan,reused,reason=resolve_plan(inventory,self.config,self.root,cache=PlanningCache())
        self.config.pop('_prepared_plan',None)
        self.bot.event('training_plan_reused' if reused else 'training_plan_computed','Готовый план проверен по текущему состоянию' if reused else 'План рассчитан по текущему состоянию',reason=reason,route=self.plan['route'])
        if hasattr(self.bot,'manage_speed'):self.bot.manage_speed(self.config.get('auto_speed',False),max_speed=self.config.get('max_auto_speed',12))
        from .move_plan import require_approval
        if self.plan.get('move_plan'):require_approval(self.plan['move_plan'],self.config.get('approved_plan_id'))
        self.navigator.configure_tools(inventory);self.runner=self.plan['runner'];self.fighters=set(self.plan['fighters']);self.route=self.plan['route'];self.config['route']=self.route;self.config['training_policy']=self.plan.get('effective_policy',self.config.get('training_policy','coverage'))
        if self.config.get('final_moves'):
            installed=self.bot.move_plan(self.trainee,self.target,self.config['final_moves'],evolution_mode=self.config.get('evolution_mode','natural'),approved_plan_id=self.config.get('approved_plan_id'))
            if installed['id']!=self.plan['move_plan']['id']:raise TrainingProblem('move_plan_mismatch','Изменился исходный набор приёмов; выбери итоговые приёмы заново')
        self.record_run()
        for message in self.plan['warnings']:self.bot.event('training_warning',message)
        # Check the whole journey before crossing any one-way ledge. The nearest
        # clinic must still permit onward travel to the selected farming hub.
        self.stage('Проверяем дорогу к зоне и обратный путь')
        from copy import deepcopy
        self.farm=deepcopy(self.plan['navigation']['farm']) if self.plan.get('navigation') else self.navigator.choose_farm(self.route)
        onward=zone_spec(self.root)['hubs'][self.farm['hub']]
        if self.plan.get('keep_party'):
            self.navigator.configure_tools(inventory,'party');self.clinic=self.farm['hub'];self.farm_pair=tuple(tuple(p) for p in self.farm['pair']);self.want_heal=False
        else:
            self.want_heal=True;self.stage('Подготовка: ищем ближайший доступный Center');self.travel_lead();nearest,path=self.navigator.nearest_clinic((onward['map'],onward['nurse']),before_preparation=True);hub=zone_spec(self.root)['hubs'][nearest]
            self.bot.event('preparation_clinic_selected','Ближайший Center: '+hub['label'],clinic=nearest,steps=path['cost'][1],grass=path['cost'][0])
            self.navigator.configure_tools(inventory,'party');self.navigator.travel(hub['map'],hub['nurse']);self.prepare_at_clinic();self.navigator.configure_tools(self.bot.inventory());self.travel_lead()
            self.stage('Подготовка: выбираем безопасную связку Center ↔ трава');self.farm=self.navigator.choose_farm(self.route);self.clinic=self.farm['hub'];self.farm_pair=tuple(tuple(p) for p in self.farm['pair']);hub=zone_spec(self.root)['hubs'][self.clinic]
            self.bot.event('grind_clinic_selected','Клиника зоны: '+hub['label'],clinic=self.clinic,route=self.route,tiles=self.farm['pair'],steps=self.farm['cost'][1])
            # The final roster was already assembled at the first clinic. A different
            # destination clinic restores the farming roster after per-leg utility teams.
            if self.state()['map']['name']!=hub['map']:
                pinned=[self.trainee,self.runner,self.plan.get('primary_mentor')]
                self.navigator.travel_prepared(hub['map'],hub['nurse'],pinned=pinned,preferred=self.plan['team_uids'])
                if {m['uid'] for m in self.state()['party']}!=set(self.plan['team_uids']):Storage(self).assemble(self.plan['team_uids'])
                self.heal_here();self.navigator.configure_tools(self.bot.inventory());self.travel_lead()
        self.preparing=False;self.bot.event('preparation_complete','Команда собрана и вылечена: начинаем учёт циклов',route=self.route,strategy=self.strategy,clinic=self.clinic,area=self.farm['pair'])
        self.coverage_signature=self.coverage_key()
        self.begin_cycle();self.to_grass();deadline=self.state()['frame']+60*60*60*12
        while self.state()['frame']<deadline:
            s=self.state()
            if s['map']['name'] not in locations(self.root):raise TrainingProblem('location_changed','Неожиданная локация: '+s['map']['name'])
            if s['in_battle']:self.fight(retreat=self.want_heal);continue
            self.check_events(s)
            if self.want_heal or self.need_heal(s):self.heal();self.maybe_replan();self.begin_cycle();self.to_grass();continue
            self.lead(self.trainee);self.stage('Ищем бой · '+zone_label(self.route,self.root))
            p=s['position'];here=(p['x'],p['y']);self.go(self.farm_pair[1] if here==self.farm_pair[0] else self.farm_pair[0],search=True)
        raise TimeoutError('Лимит 12 игровых часов; проверь команду')
