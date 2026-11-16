"""Resume combat from messages, any party sub-menu, bag, or move selection."""
from .training import RouteTrainer,best_move
from .battle_flow import phase,ready
from .battle_conditions import switch_blockers
from .battle_strategy import current_mon,enemy_mon,choose_fighter,attack_plan

class BattleFighter(RouteTrainer):
    def __init__(self,bot):
        from .manual_battle import eligibility
        initial=bot.state();reason=eligibility(initial)
        if reason:bot.handoff('autobattle_unavailable',reason)
        living=[m for m in initial.get('party',[]) if m.get('checksum_valid',True) and m.get('hp',0)>0]
        if not living:bot.handoff('autobattle_no_fighter','Нет готового к бою Pokémon')
        super().__init__(bot,dict(trainee=living[0]['uid'],fighters=[m['uid'] for m in living],target=101));self.interaction='battle'
    def state(self):return self.bot.state()
    def check_events(self,state):
        if phase(state)=='learn_move':self.bot.handoff('move_choice_required','Выбери новый приём вручную, затем включи автобой снова')
    def current(self,s):
        return current_mon(s)
    def choose(self,s,*,free_switch=False,forced=False):
        decision=choose_fighter(s,self.root,free_switch=free_switch,forced=forced)
        if decision is None:self.bot.handoff('autobattle_no_move','Нет доступной подходящей атаки. Управление у тебя.')
        return decision['mon']
    def attack_guard(self,s,current,enemy,index):
        signature=repr(((s.get('battle') or {}).get('turn'),current['uid'],enemy.get('uid'),enemy['hp'],current['hp'],[(a['id'],a.get('current_pp'),a.get('unusable_reasons')) for a in current['moves']],current.get('status_code'),current.get('stages'),index))
        attempts=getattr(self,'_attack_attempts',(None,0));count=attempts[1]+1 if attempts[0]==signature else 1
        self._attack_attempts=(signature,count)
        if count>3:self.bot.handoff('autobattle_rejected_move','Игра повторно не принимает приём. Автобой остановлен, управление у тебя.')
    def step(self,s):
        p=phase(s);b=s.get('battle') or {};c=s.get('controls',{})
        self.check_events(s)
        if p=='finished':return False
        if p=='lost':self.bot.handoff('battle_lost','Бой остановлен. Проверь команду.')
        if not ready(s):self.wait(2);return True
        if p in ('summary','bag','party_context','party_blocked','party_message','item_target','move_order','target'):
            self.tap('B',wait=4);return True
        if p=='party':
            current=self.current(s)
            if current and current['hp']>0 and not c.get('player_fainted'):
                free=not any(m.get('hp',0)>0 for m in b.get('enemies',[])) and b.get('next_enemy_slot') is not None
                target=self.choose(s,free_switch=free)
                if target['uid']==current['uid']:self.tap('B',wait=4)
                else:self.party_select(target['uid'])
            else:self.party_select(self.choose(s,forced=True)['uid'])
            return True
        if p=='yes_no':
            # Cmd_yesnobox is shared by optional trainer switching and the
            # wild faint prompt. B would try RUN in the second case.
            if c.get('player_fainted'):
                if c.get('yes_no_cursor',0)!=0:self.tap('UP',wait=2)
                else:self.tap('A',wait=4)
            else:
                if not b.get('flags',0)&8 or b.get('next_enemy_slot') is None:self.tap('B',wait=4)
                else:
                    target=self.choose(s,free_switch=True);current=self.current(s)
                    if current and target['uid']==current['uid']:self.tap('B',wait=4)
                    elif c.get('yes_no_cursor',0)!=0:self.tap('UP',wait=2)
                    else:self.tap('A',wait=4);self.party_select(target['uid'])
            return True
        if p in ('wait','message'):
            if p=='wait':self.wait(2)
            else:self.tap('B',wait=4)
            return True
        current=self.current(s);enemy=enemy_mon(s)
        if current is None or enemy is None or current.get('hp',0)<=0 or enemy.get('hp',0)<=0:
            self.wait(2);return True
        decision=choose_fighter(s,self.root)
        if decision is None:self.bot.handoff('autobattle_no_move','Нет доступной атаки или замены. Управление у тебя.')
        plan=attack_plan(current,enemy,self.root);choice=plan['index'] if plan else None
        if p=='action':
            if decision['mon']['uid']!=current['uid']:
                if switch_blockers(s):self.bot.handoff('autobattle_trapped','Замена заблокирована, подходящей атаки нет')
                reserve=decision['mon'];self.bot.event('battle_switch_plan','Замена сокращает путь к победе',pokemon_uid=reserve['uid'],expected_attacks=decision['turns'],switch_cost=decision['switch_cost'],expected_turns=decision['cost']);self.grid_choice(c['action_cursor'][0],2);self.party_select(reserve['uid'])
            else:self.grid_choice(c['action_cursor'][0],0)
        elif p=='move':
            if choice is None or decision['mon']['uid']!=current['uid']:self.tap('B',wait=4)
            else:
                self.attack_guard(s,current,enemy,choice)
                attack=current['moves'][choice];self.bot.event('battle_attack',current['nickname']+' → '+attack['name'],pokemon_uid=current['uid'],move_id=attack['id']);self.grid_choice(c['move_cursor'][0],choice)
        return True
    def run(self):
        from .manual_battle import battle_key
        start=self.state();key=battle_key(start);deadline=start['frame']+36000;waiting=None;identity_waiting=None
        while True:
            s=self.state();p=phase(s)
            if p=='finished':return
            self.check_events(s)
            if s['frame']>=deadline:raise TimeoutError('Бой длится слишком долго')
            observed=battle_key(s)
            if observed!=key:
                # GetMonData temporarily decrypts a party entry while the next
                # opponent is sent out. A frame can end inside that operation.
                # Wait without input for missing known UIDs; new identities
                # still revoke this single-battle controller immediately.
                if observed[:2]==key[:2] and set(observed[2])<=set(key[2]):
                    if identity_waiting is None:identity_waiting=s['frame']
                    if s['frame']-identity_waiting>1800:self.bot.handoff('autobattle_identity','Данные противника не восстановились. Управление у тебя.')
                    self.wait(2);continue
                self.bot.handoff('autobattle_changed','Начался другой бой. Включи автобой заново.')
            identity_waiting=None
            if p=='wait':
                if waiting is None:waiting=s['frame']
                if s['frame']-waiting>1800:self.bot.handoff('autobattle_menu','Не удалось вернуться из переходного экрана')
            else:waiting=None
            if not self.step(s):return
