"""Frame-owned learning executor. Every button is justified by live menu state."""
from .engine import BUTTONS
from .catalog import move
from .move_plan import PlanTracker,PlanMismatch,ids,level_evolution,allows_evolution
from .telemetry import read_learning_control,read_learning_mon

SUMMARY={'CB2_SetUpPSS','CB2_RunPokemonSummaryScreen'}
TRANSITIONS={'ReshowBattleScreenAfterMenu','CB2_ReshowBattleScreenAfterMenu','CB2_EvolutionSceneLoadGraphics','CB2_BeginEvolutionScene'}
PARENTS={'BattleMainCB2','CB2_EvolutionSceneUpdate'}

class LearningRuntime:
    def __init__(self,plan,*,event,checkpoint,suspend,pending=None):
        self.tracker=PlanTracker(plan);self.plan=plan;self.event=event;self.checkpoint=checkpoint;self.suspend=suspend
        self.active=None;self.evo=None;self.owns_input=False;self.mask=0;self.last_frame=-1;self.last_pulse=-100;self.next_observe=0;self.seen_party=False;self.pending=pending;self.invalid_since=None
    def cancel(self):self.active=None;self.evo=None;self.mask=0;self.owns_input=False
    def info(self):return dict(id=self.plan['id'],uid=self.plan['uid'],index=self.tracker.index,total=len(self.plan['steps']),managed=self.owns_input,final_moves=self.plan['final_moves'])
    def pulse(self,key,frame):
        if frame-self.last_pulse<8:return 0
        self.last_pulse=frame;return BUTTONS[key]
    def observed(self,mon,stable=False):
        for step in self.tracker.observe(mon,stable=stable):self.log(step,'Автоматическое изменение подтверждено')
    def log(self,step,message):
        self.event('move_plan_applied',message,dict(plan_id=self.plan['id'],pokemon_uid=self.plan['uid'],step=step,index=self.tracker.index))
    def complete_choice(self,mon):
        step=self.active['step']
        if ids(mon)!=step['after']:raise PlanMismatch('После выбора получился другой набор приёмов')
        self.tracker.commit(step);self.log(step,'Приём заменён по плану' if step['action']=='replace' else 'Новый приём пропущен по плану');self.active=None
        self.owns_input=self.evo is not None;self.mask=0
    def choice_tick(self,c,mon):
        a=self.active;step=a['step'];frame=c['frame'];source=step['source'];parent='BattleMainCB2' if source=='battle' else 'CB2_EvolutionSceneUpdate'
        if frame-a['started']>2400:raise PlanMismatch('Меню обучения не подтвердило завершение за отведённое время')
        if mon['species_id']!=step['species'] or mon['level']!=step['level'] or mon['slot']!=a['slot']:raise PlanMismatch('Во время обучения изменились Pokémon, уровень или слот команды')
        actual=ids(mon)
        if actual not in (step['before'],step['after']):raise PlanMismatch('Во время обучения изменился исходный набор приёмов')
        cb=c['callback'];battle=c['battle'];evo=c['evo'];summary=c['summary'];phase=a['phase']
        if step['action']=='replace' and actual==step['after'] and cb==parent:
            self.complete_choice(mon);return
        if cb not in SUMMARY|TRANSITIONS|PARENTS:raise PlanMismatch('Неизвестный экран во время обучения: '+cb)
        if cb in SUMMARY:
            if step['action']!='replace':raise PlanMismatch('При пропуске приёма неожиданно открылось меню удаления')
            if cb=='CB2_RunPokemonSummaryScreen' and summary and summary['stage']==2:
                expected_return='ReshowBattleScreenAfterMenu' if source=='battle' else 'CB2_EvolutionSceneLoadGraphics'
                if summary['mode']!=2 or not summary['party'] or summary['uid']!=self.plan['uid'] or summary['slot']!=mon['slot'] or summary['moves']!=step['before']+[step['move']] or summary['return_callback']!=expected_return:raise PlanMismatch('Экран удаления не совпадает с подтверждённым планом')
                desired=step['before'].index(step['forget']);cursor=summary['cursor']
                if not 0<=cursor<=4:raise PlanMismatch('Неизвестное положение курсора удаления')
                self.mask=self.pulse('A' if cursor==desired else 'DOWN' if cursor<desired else 'UP',frame)
                if self.mask and cursor==desired:a['phase']='selected'
            return
        if cb!=parent:return
        if source=='battle':
            if not battle or battle['slot']!=mon['slot']:raise PlanMismatch('Запрос обучения относится к другому слоту')
            if step['action']=='skip' and phase=='confirmed_skip' and battle['op']!=0x5b:
                self.complete_choice(mon);return
            prompt=battle['state']==1 and battle['op'] in (0x5a,0x5b)
            if prompt:
                if c['move_id']!=step['move']:raise PlanMismatch('Игра предложила другой приём')
                if step['action']=='replace':
                    if battle['op']!=0x5a:raise PlanMismatch('Неожиданный отказ от замены')
                    if phase in ('prompt','opening'):self.mask=self.pulse('A' if c['cursor']==0 else 'UP',frame)
                    if self.mask==BUTTONS['A']:a['phase']='opening'
                elif battle['op']==0x5a:
                    self.mask=self.pulse('B',frame)
                    if self.mask:a['phase']='declining'
                else:
                    if phase not in ('declining','confirmed_skip'):raise PlanMismatch('Неожиданное подтверждение отказа')
                    self.mask=self.pulse('A' if c['cursor']==0 else 'UP',frame)
                    if self.mask==BUTTONS['A']:a['phase']='confirmed_skip'
            elif step['action']=='skip' and phase=='declining':self.mask=self.pulse('A',frame)
        else:
            if not evo or evo['state']!=22: 
                if step['action']=='skip' and phase=='confirmed_skip':self.complete_choice(mon);return
                return
            if step['action']=='skip' and evo['learn_state']==11 and phase=='confirmed_skip':self.complete_choice(mon);return
            if evo['learn_state']==4:
                if c['move_id']!=step['move']:raise PlanMismatch('Эволюция предложила другой приём')
                if step['action']=='replace':
                    if evo['yes']!=5 or evo['no']!=10:raise PlanMismatch('Неожиданное меню эволюции')
                    self.mask=self.pulse('A' if c['cursor']==0 else 'UP',frame)
                    if self.mask==BUTTONS['A']:a['phase']='opening'
                elif evo['yes']==5:
                    self.mask=self.pulse('B',frame)
                    if self.mask:a['phase']='declining'
                elif evo['yes']==11 and phase in ('declining','confirmed_skip'):
                    self.mask=self.pulse('A' if c['cursor']==0 else 'UP',frame)
                    if self.mask==BUTTONS['A']:a['phase']='confirmed_skip'
                else:raise PlanMismatch('Неожиданное подтверждение при эволюции')
            elif step['action']=='skip' and phase=='declining':self.mask=self.pulse('A',frame)
    def poll(self,game,choice=None):
        frame=game.frame
        if frame==self.last_frame:return
        self.last_frame=frame;self.mask=0;c=read_learning_control(game)
        relevant=bool(choice or self.active or self.evo or c['evo'] or self.invalid_since is not None or frame>=self.next_observe)
        if not relevant:return
        mon=read_learning_mon(game,self.plan['uid'])
        if mon is None:
            if self.seen_party or choice or c['evo']:raise PlanMismatch('Покемон цели отсутствует в команде')
            return
        self.seen_party=True
        if not mon.get('checksum_valid'):
            if self.invalid_since is None:self.invalid_since=frame;self.suspend()
            self.owns_input=True
            if frame-self.invalid_since>120:raise PlanMismatch('Данные Pokémon не восстановились после временной записи')
            return
        if self.invalid_since is not None:
            self.invalid_since=None;self.owns_input=bool(self.active or self.evo)
        if c['evo']:
            e=c['evo']
            if e['slot']!=mon['slot']:raise PlanMismatch('Началась незапланированная эволюция другого Pokémon')
            if self.evo is None:
                self.observed(mon);step=self.tracker.next_step();resume=bool(self.pending and self.pending.get('source')=='evolution' and e['post']==mon['species_id'] and e['state']==22)
                if not resume:
                    decision=next((d for d in self.plan.get('decisions',[]) if d['kind']=='evolve' and d['level']==mon['level'] and d['species']==e['pre'] and d['target_species']==e['post']),None)
                    expected='evolve' if allows_evolution(self.plan['mode'],e['pre']) else 'cancel'
                    if not decision or decision['action']!=expected:raise PlanMismatch('Эволюция не подтверждена для этого уровня и вида')
                    if allows_evolution(self.plan['mode'],e['pre']):
                        if not step or step['kind']!='evolve' or e['pre']!=step['species'] or e['post']!=step['target_species'] or mon['level']!=step['level']:raise PlanMismatch('Вид или уровень эволюции не совпадает с планом')
                    elif e['pre']!=mon['species_id'] or level_evolution(mon,mon['species_id'],mon['level'],game.root)!=e['post']:raise PlanMismatch('Неожиданная ветка эволюции')
                self.evo=dict(pre=e['pre'],post=e['post'],level=mon['level'],started=frame,cancel=not allows_evolution(self.plan['mode'],e['pre']));self.suspend();self.checkpoint('Перед эволюцией по плану')
                self.event('move_plan_evolution','Эволюция по плану' if not self.evo['cancel'] else 'Сохраняем текущий вид',dict(plan_id=self.plan['id'],pokemon_uid=mon['uid'],evolution=self.evo))
            if frame-self.evo['started']>7200:raise PlanMismatch('Эволюция не завершилась за отведённое время')
            self.owns_input=True
        elif self.evo and c['callback'] not in SUMMARY|TRANSITIONS:
            self.observed(mon);self.evo=None;self.owns_input=self.active is not None
        if self.active:
            self.choice_tick(c,mon);return
        self.observed(mon,stable=c['stable']);self.next_observe=frame+6
        if choice:
            if choice['party_slot']!=mon['slot']:raise PlanMismatch('Новый приём предложен другому Pokémon')
            step=self.tracker.authorize(mon,choice);self.suspend();self.checkpoint('Перед обучением · '+move(step['move'],game.root)['name'])
            self.active=dict(step=step,phase='prompt',started=frame,slot=mon['slot']);self.owns_input=True;self.pending=None;self.last_pulse=frame
            self.event('move_plan_choice','Обучение по согласованному плану',dict(plan_id=self.plan['id'],pokemon_uid=mon['uid'],step=step));self.choice_tick(c,mon);return
        if self.evo and c['evo']:
            e=c['evo']
            if not 0<=e['state']<=22:raise PlanMismatch('Неизвестный этап эволюции')
            if self.evo['cancel'] and e['state']==8:
                if not e['bits']&1:raise PlanMismatch('Эту эволюцию нельзя отменить обычной кнопкой')
                self.mask=self.pulse('B',frame)
            elif e['state']!=22:self.mask=self.pulse('A',frame)
            elif e['learn_state'] in (0,1,2,3):self.mask=self.pulse('A',frame)
            elif e['learn_state']!=4:raise PlanMismatch('Неожиданный этап обучения при эволюции')
