"""Reachable level-up moves and explicit chronological replacement contracts.

ROM-specific order: old-form level moves, then one level evolution after battle,
then new-form moves at that same level. Unmodelled evolution conditions stop
runtime rather than silently choosing a branch or consuming an item.
"""
from functools import lru_cache
from .catalog import species,move,catalog
from .run_context import digest

VERSION='moves-v2'
HMS={15,19,57,70,148,249,127,291}

class PlanMismatch(RuntimeError):pass

def ids(mon):return [a['id'] for a in mon.get('moves',[]) if a.get('id')]

def level_evolution(mon,number,level,root):
    if catalog(root)['items'].get(str(mon.get('held_item',0)))=='EVERSTONE':return None
    result=None
    for e in species(number,root).get('evolutions',[]):
        method=e['method']
        if method==4 and level>=e['parameter']:result=e['target']
        elif method in (11,12) and level>=e['parameter']:
            silk=(mon.get('personality',0)>>16)%10<=4
            if silk==(method==11):result=e['target']
    return result

def allows_evolution(mode,number):
    return mode=='natural' or mode.startswith('stop_at:') and int(mode.split(':')[1])!=number

def needs_approval(plan):return bool(plan.get('decisions'))
def decision_order(step):return (step['level'],1 if step['kind']=='evolve' else 2 if step.get('source')=='evolution' else 0)
def require_approval(plan,approved_id):
    if needs_approval(plan) and approved_id!=plan['id']:raise ValueError('Прими решения по уровням: замены, пропуски и эволюции требуют подтверждения')


def curriculum(mon,goal,root,mode='natural',pending=None):
    if mode not in ('natural','stay') and not(mode.startswith('stop_at:') and mode.split(':')[1].isdigit()):raise ValueError('Неизвестный режим эволюции')
    if not mon.get('checksum_valid',True) or mon.get('is_egg'):raise ValueError('Нужен проверенный Pokémon')
    if not mon['level']<=goal<=100:raise ValueError('Целевой уровень ниже текущего')
    number=mon['species_id'];events=[];forms=[number];warnings=[];evolution_decisions=[]
    if pending:
        if pending.get('uid')!=mon['uid']:raise ValueError('Запрос обучения относится к другому Pokémon')
        rows=species(number,root)['learnset'];start=next((i for i,r in enumerate(rows) if r['level']==mon['level'] and r['move']==pending['move_id']),None)
        if start is None:raise ValueError('Новый приём не соответствует уровневому списку')
        events.extend(dict(kind='learn',species=number,level=mon['level'],move=r['move'],source=pending.get('source','battle')) for r in rows[start:] if r['level']==mon['level'])
        evolution=level_evolution(mon,number,mon['level'],root) if pending.get('source','battle')=='battle' else None
        if evolution:
            evolution_decisions.append(dict(kind='evolve',species=number,target_species=evolution,level=mon['level'],action='evolve' if allows_evolution(mode,number) else 'cancel'))
            if allows_evolution(mode,number):
                events.append(dict(kind='evolve',species=number,target_species=evolution,level=mon['level']));number=evolution;forms.append(number)
                events.extend(dict(kind='learn',species=number,level=mon['level'],move=r['move'],source='evolution') for r in species(number,root)['learnset'] if r['level']==mon['level'])
    for level in range(mon['level']+1,goal+1):
        events.extend(dict(kind='learn',species=number,level=level,move=r['move'],source='battle') for r in species(number,root)['learnset'] if r['level']==level)
        evolution=level_evolution(mon,number,level,root)
        if evolution:evolution_decisions.append(dict(kind='evolve',species=number,target_species=evolution,level=level,action='evolve' if allows_evolution(mode,number) else 'cancel'))
        if evolution and allows_evolution(mode,number):
            events.append(dict(kind='evolve',species=number,target_species=evolution,level=level));number=evolution;forms.append(number)
            events.extend(dict(kind='learn',species=number,level=level,move=r['move'],source='evolution') for r in species(number,root)['learnset'] if r['level']==level)
    if mode.startswith('stop_at:') and number!=int(mode.split(':')[1]):raise ValueError('Выбранная ступень эволюции недостижима до цели')
    for form in forms:
        for e in species(form,root).get('evolutions',[]):
            if e['method'] not in (4,11,12):warnings.append('Особые условия эволюции: '+species(form,root)['name']+'. Камни, обмены и условные ветки автоматически не выполняются.')
    available={n:dict(id=n,name=move(n,root)['name'],source='Сейчас',level=mon['level'],species=mon['species_id']) for n in ids(mon)}
    for e in events:
        if e['kind']=='learn' and e['move'] not in available:available[e['move']]=dict(id=e['move'],name=move(e['move'],root)['name'],source=species(e['species'],root)['name'],level=e['level'],species=e['species'])
    return dict(evolution_decisions=evolution_decisions,events=events,forms=forms,final_species=number,available=list(available.values()),warnings=sorted(set(warnings)))

def compile_plan(mon,goal,final_moves,root,mode='natural',pending=None):
    if not isinstance(final_moves,(list,tuple)) or not 1<=len(final_moves)<=4 or any(type(n) is not int for n in final_moves) or len(set(final_moves))!=len(final_moves):raise ValueError('Выбери от одного до четырёх разных приёмов')
    current=ids(mon);desired=frozenset(final_moves);data=curriculum(mon,goal,root,mode,pending);events=data['events']
    if not desired<={r['id'] for r in data['available']}:raise ValueError('Выбранный приём нельзя получить до этого уровня по выбранной эволюции')
    if len(desired)<len(current):raise ValueError('Нельзя просто удалить приём: выбери итоговый набор того же размера или больше')
    # Canonical sets merge slot permutations. Native slot order is reconstructed
    # below; preference keeps useful temporary attacks while a final move waits.
    future_moves=[set() for _ in range(len(events)+1)]
    for i in range(len(events)-1,-1,-1):future_moves[i]=future_moves[i+1]|({events[i]['move']} if events[i]['kind']=='learn' else set())
    utilities={n:min(100,move(n,root).get('power',0)) for n in {r['id'] for r in data['available']}}
    @lru_cache(maxsize=None)
    def solve(index,known):
        if index==len(events):return (0,()) if frozenset(known)==desired else None
        e=events[index]
        if e['kind']=='evolve':
            tail=solve(index+1,known);return (tail[0],(('evolve',None),)+tail[1]) if tail else None
        new=e['move'];have=set(known)
        if new in have:options=[('known',None,have)]
        elif len(have)<4:options=[('auto',None,have|{new})]
        else:options=[('skip',None,have)]+[('replace',old,(have-{old})|{new}) for old in known if old not in HMS]
        best=None
        for action,old,after in options:
            # A missing final move must have an opportunity later in the plan.
            future=future_moves[index+1]
            if not desired<=after|future:continue
            tail=solve(index+1,tuple(sorted(after)))
            if tail is None:continue
            utility=sum(utilities[n] for n in after)+500*bool(any(utilities[n]>0 for n in after))+20*len(after&desired)
            score=tail[0]+utility-(action=='replace')
            result=(score,((action,old),)+tail[1])
            if best is None or result[0]>best[0]:best=result
        return best
    result=solve(0,tuple(sorted(current)))
    if result is None:raise ValueError('Этот итоговый набор недостижим: проверь обязательные приёмы, HM и порядок изучения')
    known=list(current);steps=[]
    for event,(action,old) in zip(events,result[1]):
        if action=='known':continue
        step=dict(event,action=action,before=list(known))
        if action=='replace':step['forget']=old;known[known.index(old)]=event['move']
        elif action=='auto':known.append(event['move'])
        step['after']=list(known);steps.append(step)
    decisions=[s for s in steps if s['action'] in ('replace','skip')]+data['evolution_decisions']
    decisions.sort(key=decision_order)
    value=dict(decisions=decisions,version=VERSION,uid=mon['uid'],start_species=mon['species_id'],start_level=mon['level'],start_moves=current,goal=goal,mode=mode,final_moves=list(final_moves),final_species=data['final_species'],steps=steps,warnings=data['warnings'])
    value['id']=digest(value);return value

def default_moves(mon,goal,root,mode='natural',pending=None):
    data=curriculum(mon,goal,root,mode,pending);known=ids(mon)
    for e in data['events']:
        if e['kind']!='learn' or e['move'] in known:continue
        if len(known)<4:known.append(e['move'])
    return known

class PlanTracker:
    """Observe only expected automatic changes; choices require authorization."""
    def __init__(self,plan):self.plan=plan;self.index=0;self.last_species=plan['start_species'];self.last_moves=list(plan['start_moves']);self.active=None
    def next_step(self):return self.plan['steps'][self.index] if self.index<len(self.plan['steps']) else None
    def observe(self,mon,*,stable=False):
        if not mon or mon['uid']!=self.plan['uid'] or not mon.get('checksum_valid',True):raise PlanMismatch('Не совпадает Pokémon или контрольная сумма')
        actual=ids(mon);changed=[]
        possible=[]
        for step in self.plan['steps'][self.index:]:
            if step['action'] not in ('auto','evolve') or step['level']>mon['level']:break
            possible.append(step)
            if actual==step['after'] and mon['species_id']==step.get('target_species',step['species']):
                for event in possible:self.commit(event);changed.append(event)
                break
        if mon['species_id']!=self.last_species or actual!=self.last_moves:raise PlanMismatch('Вид или набор приёмов отличается от плана')
        step=self.next_step()
        if step and (mon['level']>step['level'] or stable and mon['level']>=step['level']):raise PlanMismatch('Ожидаемое обучение или эволюция не произошло на запланированном уровне')
        if stable and mon['level']>=self.plan['goal'] and (step or set(actual)!=set(self.plan['final_moves']) or mon['species_id']!=self.plan['final_species']):raise PlanMismatch('Итоговый набор или вид не соответствует выбранной цели')
        return changed
    def authorize(self,mon,choice):
        self.observe(mon);step=self.next_step()
        if not step or step['kind']!='learn' or step['action'] not in ('replace','skip') or choice['move_id']!=step['move'] or choice.get('source','battle')!=step['source'] or mon['level']!=step['level']:raise PlanMismatch('Запрос нового приёма не совпадает с планом')
        return step
    def commit(self,step):
        self.last_moves=list(step['after'])
        self.last_species=step.get('target_species',step['species']);self.index+=1
