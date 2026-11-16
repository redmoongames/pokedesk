"""Route 1/2 switch training. All changes use ordinary GBA input."""
from collections import deque
import heapq
import json
from .catalog import species, move, effectiveness

ROUTE2_TRANSIT={'Route2','ViridianForest','Route2_ViridianForest_SouthEntrance','Route2_ViridianForest_NorthEntrance'}
ALLOWED = {'Route1','ViridianCity','ViridianCity_PokemonCenter_1F'} | ROUTE2_TRANSIT

def select_route(map_name):
    if map_name in ROUTE2_TRANSIT:return 'Route2'
    if map_name in ALLOWED:return 'Route1'
    raise ValueError('Начни на Route 1/2, в Viridian City, Pokémon Center или Viridian Forest')

def trainer_zones(grid):
    """Conservative sight envelope, including every possible facing and wander origin.

    Never route through somebody's sight while hoping to pass between rotations.
    Only the game's defeated flag disables sight; walls don't shrink the envelope.
    """
    blocked=set()
    fixed={7:((0,-1),),8:((0,1),),9:((-1,0),),10:((1,0),),13:((0,-1),(0,1)),14:((-1,0),(1,0))}
    for t in grid.get('trainers',[]):
        movement=t['movement'];wander=movement in range(2,7) or movement>=25
        rx,ry=(t.get('range_x',0),t.get('range_y',0)) if wander else (0,0)
        directions=fixed.get(movement,((0,1),(0,-1),(1,0),(-1,0))) if t.get('trainer_type',1)==1 else ((0,1),(0,-1),(1,0),(-1,0))
        # Live x/y is an occupied cell, never the origin of another patrol.
        # A defeated trainer has no sight; slow walking uses actual occupancy,
        # while continuous movement separately avoids the anchored NPC envelope.
        blocked.add((t['x'],t['y']))
        if t.get('defeated'):continue
        ox=t.get('anchor_x',t['x']);oy=t.get('anchor_y',t['y'])
        origins={(x,y) for x in range(ox-rx,ox+rx+1) for y in range(oy-ry,oy+ry+1)}
        origins.add((t['x'],t['y']))
        for x,y in origins:
            blocked.add((x,y))
            for dx,dy in directions:
                blocked.update((x+dx*d,y+dy*d) for d in range(1,t['sight']+1))
    return blocked

class TrainingProblem(RuntimeError):
    def __init__(self,code,message):super().__init__(message);self.code=code

def validate(state, config):
    if not state.get('ready'): raise ValueError('Дождись загрузки игры')
    if state['in_battle']: raise ValueError('Сначала закончи текущий бой')
    select_route(state['map']['name'])
    if state['controls']['callback'] != 'CB2_Overworld' or state['controls']['field_locked']:
        raise ValueError('Закрой меню и диалоги, дождись окончания перехода')
    party={m['uid']:m for m in state['party'] if m['checksum_valid'] and not m['is_egg']}
    trainee=config.get('trainee'); fighters=config.get('fighters',[])
    if trainee not in party: raise ValueError('Выбери ученика из текущей команды')
    if not 2 <= len(set(fighters)) <= 4 or len(fighters)!=len(set(fighters)):
        raise ValueError('Выбери от 2 до 4 разных бойцов')
    if trainee in fighters or any(uid not in party for uid in fighters):
        raise ValueError('Ученик и бойцы должны быть разными покемонами текущей команды')
    if not 2<=int(config.get('target',15))<=100: raise ValueError('Целевой уровень: от 2 до 100')
    if party[trainee]['level'] >= int(config.get('target',15)): raise ValueError('Целевой уровень уже достигнут')
    if any(not any(m['power']>0 for m in party[uid]['moves']) for uid in fighters):
        raise ValueError('У каждого бойца должен быть хотя бы один атакующий приём')
    if sum(m['hp']>0 for m in party.values())==0: raise ValueError('В команде нет живых покемонов')

def walk_neighbors(grid,point,blocked):
    """Ordinary walking plus verified directional ledge jumps; never Surf/Cut."""
    def clear(x,y):
        if not(0<=x<grid['width'] and 0<=y<grid['height']) or (x,y) in blocked:return False
        collision,behavior,_,_=grid['tiles'][y][x]
        return not collision and not (0x10<=behavior<=0x1c or 0x30<=behavior<=0x5f or 0x60<=behavior<=0x71)
    jumps={(1,0):0x38,(-1,0):0x39,(0,-1):0x3a,(0,1):0x3b}
    def faces_sign(x,y,dx,dy):
        a,b=x+dx,y+dy
        if not(0<=a<grid['width'] and 0<=b<grid['height']):return False
        behavior=grid['tiles'][b][a][1]
        return behavior in (0x84,0x91,0x92) or (behavior in (0x87,0x88) and dy==-1)
    for dx,dy in ((0,-1),(-1,0),(1,0),(0,1)):
        x,y=point[0]+dx,point[1]+dy
        if clear(x,y) and not faces_sign(x,y,dx,dy):yield x,y
        elif 0<=x<grid['width'] and 0<=y<grid['height'] and (x,y) not in blocked and grid['tiles'][y][x][1]==jumps[dx,dy] and clear(x+dx,y+dy) and not faces_sign(x+dx,y+dy,dx,dy):yield x+dx,y+dy

def paths_to(grid, start, goals, blocked=(), *, avoid_grass=True, heading=None):
    """Minimize encounters, then steps, turns and proximity to corridor hazards.

    Heading is part of the search state: one best cost per cell would discard
    an equally short approach that makes the remaining path straighter.
    """
    from itertools import count
    from .movement import corridor_hazards
    from .walking_route import direction
    blocked=set(map(tuple,blocked)) | set(map(tuple,grid['obstacles'])) | trainer_zones(grid) | set(map(tuple,grid.get('script_triggers',[])))
    blocked|={(w['x'],w['y']) for w in grid.get('warps',[])}
    start=tuple(start);goals=set(map(tuple,goals));found={};blocked.discard(start)
    hazards=corridor_hazards(grid);serial=count();initial=(start,heading);zero=(0,0,0,0)
    queue=[(zero,next(serial),initial)];previous={initial:None};cost={initial:zero};neighbors={};infinity=(float('inf'),)*4
    while queue:
        value,_,node=heapq.heappop(queue)
        if cost[node]!=value:continue
        point,facing=node
        if point in goals and point not in found:
            path=[];cursor=node
            while previous[cursor] is not None:path.append(cursor[0]);cursor=previous[cursor]
            found[point]=path[::-1]
            if len(found)==len(goals):break
        if point not in neighbors:
            neighbors[point]=[]
            for x,y in walk_neighbors(grid,point,blocked):
                next_point=(x,y);new_heading=direction(point,next_point)
                encounter=int(avoid_grass and bool(grid['tiles'][y][x][3]))
                exposure=int(next_point in hazards or not (1<=x<grid['width']-1 and 1<=y<grid['height']-1))
                neighbors[point].append((next_point,new_heading,encounter,exposure))
        for next_point,new_heading,encounter,exposure in neighbors[point]:
            turns=int(facing is not None and facing!=new_heading)
            next_cost=(value[0]+encounter,value[1]+1,value[2]+turns,value[3]+exposure)
            other=(next_point,new_heading)
            if next_cost<cost.get(other,infinity):
                cost[other]=next_cost;previous[other]=node;heapq.heappush(queue,(next_cost,next(serial),other))
    return found

def path_to(grid,start,goal,blocked=(),*,avoid_grass=True,heading=None):
    goal=tuple(goal)
    paths=paths_to(grid,start,[goal],blocked,avoid_grass=avoid_grass,heading=heading)
    if goal not in paths:raise RuntimeError(f'Нет проходимого пути {start} → {goal}')
    return paths[goal]


def best_move(mon, enemy, root):
    """Rank usable attacks by power, accuracy, STAB and Gen III type matchup."""
    if mon.get('level') and enemy.get('stats'):
        from .mechanics import ranked_attacks
        ranked=ranked_attacks(mon,enemy,root)
        return ranked[0][0] if ranked else None
    own=species(mon['species_id'],root)
    def score(pair):
        i,m=pair
        from .battle_conditions import move_blockers
        if move_blockers(mon,m) or not m['power']: return -1
        stat='special_attack' if m['category']=='Special' else 'attack'
        return m['power']*(m['accuracy'] or 100)/100 * (1.5 if m['type_id'] in own.get('type_ids',[]) else 1) * effectiveness(m['type_id'],enemy['types'],root) * mon.get('stats',{}).get(stat,1)
    pairs=list(enumerate(mon['moves']))
    if not pairs: return None
    pair=max(pairs,key=score)
    return pair[0] if score(pair)>0 else None

class RouteTrainer:
    def __init__(self, bot, config):
        self.bot,self.config=bot,config
        self.root=bot.project_dir
        self.trainee=config['trainee']; self.fighters=set(config['fighters'])
        self.target=int(config.get('target',15)); self.threshold=int(config.get('heal_percent',40))/100
        self.want_heal=True; self.battles=0; self.battle_start=None; self.last_stage=None
        self.blocked={}; self.grass=None
        self.previous={}
        self.route=None;self.farm_pair=None
        self.interaction='travel'

    def expect_interaction(self,context='travel'):
        self.interaction=context
        if hasattr(self.bot,'expect_interaction'):self.bot.expect_interaction(context)

    def handoff(self,code,message,**details):
        self.bot.checkpoint(((self.route or 'Прокачка')+' · '+message)[:64])
        self.bot.handoff(code,message,**details)

    def check_events(self,s):
        choice=s.get('decision')
        if choice and not s.get('move_plan',{}).get('managed'):
            mon=next((m for m in s['party'] if m['slot']==choice['party_slot']),None)
            new=move(choice['move_id'],self.root)
            name=mon['nickname'] if mon else 'Покемон'
            self.handoff('move_choice_required',f"Нужен твой выбор: {name} хочет выучить {new.get('name','новый приём')}; четыре слота заняты. Выбери замену в окне игры.",
                         pokemon_uid=mon['uid'] if mon else None, pokemon=name,new_move=new.get('name'),move_id=choice['move_id'],current_moves=[m['name'] for m in mon['moves']] if mon else [])
        battle=s.get('battle')
        if battle and battle['outcome'] in (2,3,9):
            self.handoff('battle_lost','Команда проиграла бой. Прокачка остановлена, управление у тебя.',outcome=battle['outcome'])
        for mon in s['party']:
            before=self.previous.get(mon['uid'])
            if before and (before['species_id']!=mon['species_id'] or before['level']!=mon['level']):
                self.bot.event('pokemon_progress',f"{mon['nickname']}: Lv {before['level']} → {mon['level']} · {before['species']} → {mon['species']}",pokemon_uid=mon['uid'],before=before,after=dict(level=mon['level'],species=mon['species'],species_id=mon['species_id']))
            self.previous[mon['uid']]=dict(level=mon['level'],species=mon['species'],species_id=mon['species_id'])
        trainee=self.mon(s,self.trainee)
        plan=s.get('move_plan');c=s.get('controls',{});stable=c.get('callback')=='CB2_Overworld' and not c.get('field_locked') and not s.get('in_battle')
        if trainee['level']>=self.target and (not plan or stable and not plan['managed']):
            self.handoff('target_reached',f"Цель достигнута: {trainee['nickname']} Lv {trainee['level']}. Скрипт завершён, управление у тебя.",pokemon_uid=self.trainee,level=trainee['level'],target=self.target,xp=trainee['experience'])

    def stage(self,message):
        if self.last_stage!=message: self.bot.event('training_stage',message); self.last_stage=message

    def state(self):
        for attempt in range(120):
            state=self.bot.state()
            complete=all(m.get('checksum_valid',True) and all('pp' in a and 'power' in a for a in m.get('moves',[])) for m in state.get('party',[]))
            if state.get('telemetry_valid',True) and complete:
                c=state.get('controls',{})
                if c.get('field_recovery') or state.get('session',{}).get('recovery'):
                    self.bot.wait_frames(6);continue
                if self.interaction=='travel' and c.get('callback')=='CB2_Overworld' and c.get('field_locked'):
                    code='unexpected_dialog' if c.get('message_box') else 'unexpected_scene' if c.get('field_script_native')=='WaitForMovementFinish' else None
                    if code:self.handoff(code,'Неожиданный диалог или сюжетная сцена. Пройди её вручную и запусти бота заново.',map=state.get('map'),position=state.get('position'),stage=self.last_stage)
                if attempt and hasattr(self.bot,'event'):self.bot.event('telemetry_recovered','Данные команды восстановились; продолжаем без нажатий во время перехода',waited_frames=attempt*2)
                return state
            self.bot.wait_frames(2)
        raise TrainingProblem('telemetry_unavailable','Данные команды временно некорректны. Кнопки не нажимаются; проверь игру.')
    def tap(self,key,wait=10): self.bot.press(key,frames=2,release_frames=wait)
    def wait(self,n=10): self.bot.wait_frames(n)
    def mon(self,state,uid):
        mon=next((m for m in state['party'] if m['uid']==uid),None)
        if mon is None: raise TrainingProblem('party_changed','Выбранный покемон исчез из команды. Проверь состав.')
        return mon

    def wait_for(self,predicate,limit=900):
        deadline=self.state()['frame']+limit
        while True:
            state=self.state()
            if predicate(state):return state
            if state['frame']>=deadline:raise TimeoutError('Ожидаемое состояние игры не наступило')
            self.wait(min(6,deadline-state['frame']))

    def grid_choice(self,current,target):
        if current&1 != target&1: self.tap('RIGHT' if target&1 else 'LEFT')
        if current&2 != target&2: self.tap('DOWN' if target&2 else 'UP')
        self.tap('A')

    def party_select(self,uid,*,reorder=False):
        """Navigate actual party cursor and contextual action IDs, not screen pixels."""
        deadline=self.state()['frame']+1800
        selected=False;summary_recoveries=0
        while self.state()['frame']<deadline:
            s=self.state(); c=s['controls']; tasks={t['name'] for t in c['tasks']}
            if not reorder and not selected and s.get('in_battle') and not c.get('player_fainted'):
                from .battle_strategy import current_mon
                current=current_mon(s)
                if current and current.get('uid')==uid and current.get('hp',0)>0:
                    if c['callback']=='BattleMainCB2':return
                    self.tap('B',wait=6);continue
            if c['callback'] in ('CB2_SetUpPSS','CB2_RunPokemonSummaryScreen','CB2_ShowPokemonSummaryScreen'):
                summary_recoveries+=1
                if summary_recoveries>1:raise TrainingProblem('party_summary_repeated','При выборе Switch повторно открылся Summary; управление у тебя')
                self.bot.event('battle_recovery','Вместо Switch открыт Summary: закрываем и перечитываем меню',action='close_unexpected_summary',pokemon_uid=uid)
                for _ in range(180):
                    fresh=self.state()['controls']
                    if fresh['callback']=='CB2_UpdatePartyMenu':selected=False;break
                    self.tap('B',wait=6)
                else:raise TrainingProblem('party_summary_timeout','Не удалось вернуться из Summary в команду')
                continue
            if reorder and self.mon(s,uid)['slot']==1:
                self.tap('B'); self.wait(30); return
            if c['callback']=='BattleMainCB2' and selected: return
            if not reorder and s.get('in_battle') and c.get('party_action') in (2,4):
                self.bot.event('battle_recovery','Игра запретила замену: возвращаемся к текущему Pokémon',action='close_blocked_switch',pokemon_uid=uid,party_action=c['party_action'])
                for _ in range(180):
                    if self.state()['controls']['callback']=='BattleMainCB2':return
                    self.tap('B',wait=6)
                raise TrainingProblem('switch_blocked_menu','Не удалось закрыть сообщение о запрете замены')
            if 'Task_HandleChooseMonInput' in tasks:
                target=0 if reorder and c['party_action']==8 else self.mon(s,uid)['slot']-1
                current=c['party_cursor2'] if c['party_action']==8 else c['party_cursor']
                if current==target: self.tap('A'); selected=True
                elif current==0: self.tap('RIGHT')
                elif target==0: self.tap('LEFT')
                else: self.tap('DOWN' if current<target else 'UP')
            elif 'Task_HandleSelectionMenuInput' in tasks:
                options=c['party_actions']; action=1 if reorder else 10 if 10 in options else 11
                if action not in options: raise RuntimeError(f'Нет команды переключения в меню {options}')
                index=options.index(action)
                if c['menu_cursor']==index:
                    self.wait(1);fresh=self.state()['controls']
                    if not any(t['name']=='Task_HandleSelectionMenuInput' for t in fresh['tasks']):continue
                    choices=fresh['party_actions'];cursor=fresh['menu_cursor']
                    if not 0<=cursor<len(choices) or choices[cursor]!=action:continue
                    self.bot.event('party_action_confirmed','Switch' if reorder else 'Выход в бой',pokemon_uid=uid,action_id=action,actions=choices,cursor=cursor)
                    self.tap('A')
                else: self.tap('DOWN' if c['menu_cursor']<index else 'UP')
            else: self.wait()
        raise TimeoutError('Меню команды не подтвердило перестановку/переключение')

    def lead(self,uid):
        s=self.state()
        if self.mon(s,uid)['slot']==1: return
        if not any(t['name']=='Task_StartMenuHandleInput' for t in s['controls']['tasks']):self.tap('START')
        deadline=self.state()['frame']+900
        while True:
            current=self.state();c=current['controls']
            if c['callback']=='CB2_UpdatePartyMenu' and any(t['name']=='Task_HandleChooseMonInput' for t in c['tasks']):break
            if current['frame']>=deadline:raise TimeoutError('Стартовое меню не подтвердило открытие команды')
            task=next((t for t in c['tasks'] if t['name']=='Task_StartMenuHandleInput'),None)
            if task and task.get('data',[0])[0]==1:
                if 1 not in c['start_order']:raise TrainingProblem('party_menu_unavailable','В стартовом меню нет команды Pokémon')
                target=c['start_order'].index(1)
                # Retry only the verified command. A may arrive while the menu
                # finishes opening; its acceptance is a native party-menu task.
                self.tap('A' if c['start_cursor']==target else 'DOWN' if c['start_cursor']<target else 'UP')
            else:self.wait(6)
        self.party_select(uid,reorder=True)
        for _ in range(80):
            s=self.state()
            if s['controls']['callback']=='CB2_Overworld' and not s['controls']['field_locked']:
                self.bot.event('party_lead','Первый слот: '+self.mon(s,uid)['nickname'],pokemon_uid=uid,role='runner' if uid==getattr(self,'runner',None) else 'trainee' if uid==self.trainee else 'fighter')
                return
            self.tap('B')
        raise TimeoutError('Не удалось закрыть меню команды')

    def step(self,direction):
        # A short pulse starts exactly one walk. Holding a direction through the
        # next tile can read a sign while turning a corner, especially after the
        # running-shoes state has changed. Let the current movement settle first.
        s=self.state();initial=(s['map']['name'],s['position']['x'],s['position']['y'])
        for _ in range(6):
            self.bot.press(direction,frames=2,release_frames=18)
            s=self.state()
            if s['in_battle']:return True
            now=(s['map']['name'],s['position']['x'],s['position']['y'])
            if now!=initial:
                self.wait_for(lambda s:s['in_battle'] or (s['controls']['callback']=='CB2_Overworld' and not s['controls']['moving'] and not s['controls']['field_locked']),limit=1200)
                return True
        return False

    def go(self,goal,*,search=False):
        from .walking_route import WalkingRoute
        from .field_tools import party_cut
        from .movement import safe_segment
        failures=0;route=None;heading=None;single_step=False
        initial=self.state();controls=initial['controls'];goal=tuple(goal)
        expected_map=initial['map']['name'] if not initial['in_battle'] and controls['callback']=='CB2_Overworld' and not controls['field_locked'] and not controls['moving'] else None
        for _ in range(700):
            s=self.state()
            if s['in_battle']:
                self.fight(retreat=not search or self.want_heal,travel=not search and not self.want_heal)
                if search:return
                continue
            if s['controls']['callback']!='CB2_Overworld' or s['controls']['field_locked'] or s['controls']['moving']:self.wait();continue
            if expected_map is None:expected_map=s['map']['name']
            if s['map']['name']!=expected_map:raise TrainingProblem('navigation_map_changed',f"Неожиданный переход {expected_map} → {s['map']['name']}: управление возвращено игроку")
            start=(s['position']['x'],s['position']['y'])
            if start==goal:return
            name=s['map']['name'];grid=party_cut(self.bot.map(),s['party'])
            if route is not None:
                if not route.advance(start) or not route.validate(grid):
                    heading=route.heading;route=None
            if route is None:
                try:path=path_to(grid,start,goal,avoid_grass=not search,heading=heading)
                except RuntimeError as error:
                    failures+=1
                    if failures<5:self.wait(30);continue
                    if name=='ViridianForest':raise TrainingProblem('trainer_blocks_exit','Нет безопасного прохода к южному выходу из леса. Путь перекрыт обзором непобеждённого тренера или препятствием; пройди этот участок вручную.') from error
                    raise
                route=WalkingRoute(start,path,heading)
                route.validate(grid)
            path=route.remaining
            if not path:continue
            if hasattr(self.bot,'walk_segment') and not single_step:
                segment=safe_segment(grid,start,path,search=search,allow_encounters=not search)
                if segment:
                    options=dict(search=search)
                    if not search and any(grid['tiles'][y][x][1]==8 for x,y in [start,*segment]):options['allow_encounters']=True
                    result=self.bot.walk_segment(name,start,segment[-1],**options)
                    if result.get('interrupted') in ('move_plan','field_recovery') or result.get('reason')=='learning':
                        self.wait(1);continue
                    reason=result.get('reason')
                    if reason is None:raise TrainingProblem('walking_response','Нет подтверждённого результата непрерывного движения')
                    if reason in ('reached','battle'):failures=0;continue
                    if reason in ('map_changed','off_corridor','invalid_position','interrupted','unsupported_transport'):raise TrainingProblem('walking_interrupted','Непрерывное движение прервано: '+reason+'. Возьми управление.')
                    # Re-read state and hazards before a single-step fallback.
                    # Keep the remaining polyline unless its actual cells changed.
                    single_step=True;continue
            single_step=False;point=path[0]
            tree=next((o for o in grid.get('objects',[]) if o.get('graphics_id')==grid.get('cut_graphics',95) and (o['x'],o['y'])==point),None)
            if tree:
                if not grid.get('cut_enabled'):raise TrainingProblem('cut_unavailable','Для дерева нужен Cut и Cascade Badge')
                self.bot.cut_tree(name,tree['local_id'],point);continue
            dx,dy=point[0]-start[0],point[1]-start[1]
            dx=(dx>0)-(dx<0);dy=(dy>0)-(dy<0)
            direction={(1,0):'RIGHT',(-1,0):'LEFT',(0,1):'DOWN',(0,-1):'UP'}[dx,dy]
            if hasattr(self.bot,'walk_step'):
                result=self.bot.walk_step(name,start,point)
                if result.get('interrupted') or result.get('reason')=='learning':self.wait(1);continue
                reason=result.get('reason')
                if reason in ('map_changed','off_corridor','invalid_position','interrupted','unsupported_transport'):
                    raise TrainingProblem('walking_interrupted','Шаг прерван: '+str(reason)+'. Возьми управление.')
                progressed=self.step(direction) if reason=='legacy' else reason in ('reached','battle')
            else:progressed=self.step(direction)
            if not progressed:
                failures+=1;self.wait(30)
                if failures>=5:raise TrainingProblem('path_blocked',f'Путь заблокирован в {start}. Возьми управление.')
            else:failures=0
        raise TimeoutError(f'Не удалось дойти до {goal}')

    def transition(self,direction,destination,*,source=None,point=None):
        """Cross a directed portal, recovering wild encounters before retrying.

        A battle may start on the portal tile before its warp is committed.
        Re-enter from the verified approach, never keep walking from the battle's
        end position. Only actual non-battle step attempts spend the retry budget.
        """
        state=self.state()
        source=source or state['map']['name']
        approach=tuple(point) if point is not None else (state['position']['x'],state['position']['y'])
        deadline=state['frame']+90000
        attempts=encounters=0;rearm=True
        dx,dy=dict(RIGHT=(1,0),LEFT=(-1,0),DOWN=(0,1),UP=(0,-1))[direction]
        activation=(approach[0]+dx,approach[1]+dy)
        while self.state()['frame']<=deadline:
            state=self.state();name=state['map']['name'];controls=state['controls']
            if state['in_battle']:
                if name not in (source,destination):raise TrainingProblem('navigation_map_changed','Бой начался на неожиданной карте: '+name)
                encounters+=1
                if encounters>8:raise TrainingProblem('transition_encounter_limit','Слишком много встреч при переходе: возьми управление')
                self.bot.event('navigation_transition_battle','Встреча на переходе: обрабатываем бой перед продолжением',source=source,destination=destination,approach=approach,position=state['position'],encounter=encounters)
                self.fight(retreat=True,travel=not self.want_heal)
                rearm=True
                self.bot.event('navigation_transition_resumed','Бой на переходе завершён: проверяем карту и точку входа',source=source,destination=destination,position=self.state()['position'])
                continue
            if controls['callback']!='CB2_Overworld' or controls['field_locked'] or controls['moving']:
                self.wait(6);continue
            if name==destination:return
            if name!=source:raise TrainingProblem('navigation_map_changed','Вместо ожидаемого перехода открылась другая карта: '+name)
            if attempts>=12:break
            here=(state['position']['x'],state['position']['y'])
            if rearm or here not in (approach,activation):
                if here!=approach:
                    self.go(approach)
                    continue
                rearm=False
            # Cave/door tiles can need a second directional pulse after stepping
            # onto the activation tile. Re-arm only after a battle or deviation.
            self.step(direction)
            # Do not spend warp retries on a newly started wild battle. The next
            # loop invokes fight(), which retains trainer/shiny/learning guards.
            if not self.state()['in_battle']:attempts+=1
        raise TimeoutError(f'Не удалось перейти в {destination}')

    def to_city(self):
        name=self.state()['map']['name']
        if name in ROUTE2_TRANSIT:
            self.to_route2_south()
            self.go((8,79));self.transition('DOWN','ViridianCity')
        elif name=='Route1':
            self.go((12,0)); self.transition('UP','ViridianCity')

    def to_route2_south(self):
        name=self.state()['map']['name']
        if name=='Route2' and self.state()['position']['y']<42:
            self.go((5,12));self.transition('DOWN','Route2_ViridianForest_NorthEntrance')
            name=self.state()['map']['name']
        if name=='Route2_ViridianForest_NorthEntrance':
            self.go((7,9));self.transition('DOWN','ViridianForest');name='ViridianForest'
        if name=='ViridianForest':
            self.stage('Выходим из Viridian Forest: обходим обзор тренеров и лишнюю траву')
            self.go((29,61));self.transition('DOWN','Route2_ViridianForest_SouthEntrance')
            name='Route2_ViridianForest_SouthEntrance'
        if name=='Route2_ViridianForest_SouthEntrance':
            self.go((7,9));self.transition('DOWN','Route2')
        if self.state()['map']['name']!='Route2':raise TrainingProblem('location_changed','Не удалось выйти на южную Route 2')

    def heal(self):
        self.want_heal=True
        self.stage('Лечение: идём в Pokémon Center')
        s=self.state()
        reserve=max((m for m in s['party'] if m['uid'] in self.fighters and m['hp']>0),key=lambda m:m['hp']/m['max_hp'],default=None)
        if reserve and s['controls']['callback']=='CB2_Overworld' and not s['controls']['field_locked']:
            self.lead(reserve['uid'])
        self.to_city()
        if self.state()['map']['name']=='ViridianCity':
            self.go((26,27)); self.transition('UP','ViridianCity_PokemonCenter_1F')
        self.go((7,4)); self.expect_interaction('healing');self.tap('UP'); self.tap('A')
        saw_lock=False
        for _ in range(700):
            s=self.state(); c=s['controls']; saw_lock |= c['field_locked']
            full=all(m['hp']==m['max_hp'] and m['status']=='В норме' and all(a['current_pp']>=a['pp'] for a in m['moves']) for m in s['party'])
            if saw_lock and not c['field_locked'] and full: break
            self.tap('A',wait=12)
        else: raise TimeoutError('Pokémon Center не подтвердил полное лечение')
        self.want_heal=False
        self.expect_interaction('travel')
        self.stage('Команда вылечена: HP, статусы и PP восстановлены')
        self.go((7,7)); self.transition('DOWN','ViridianCity')
        self.lead(self.trainee)

    def to_grass(self):
        self.route=self.route or select_route(self.state()['map']['name'])
        if self.state()['map']['name']=='ViridianCity':
            if self.route=='Route2':self.go((20,0));self.transition('UP','Route2')
            else:self.go((24,39)); self.transition('DOWN','Route1')
        grid=self.bot.map(); start=self.state()['position']; candidates=[]
        gateway=(8,79) if self.route=='Route2' else (12,0)
        danger=trainer_zones(grid)
        for y,row in enumerate(grid['tiles']):
            for x,t in enumerate(row):
                if t[1]==2 and t[0]==0 and (x,y) not in danger:
                    neighbors=[(x+dx,y+dy) for dx,dy in ((1,0),(-1,0),(0,1),(0,-1)) if 0<=x+dx<grid['width'] and 0<=y+dy<grid['height'] and grid['tiles'][y+dy][x+dx][1]==2 and not grid['tiles'][y+dy][x+dx][0] and (x+dx,y+dy) not in danger]
                    if not neighbors:continue
                    try: path=path_to(grid,gateway,(x,y))
                    except RuntimeError: continue
                    candidates.append((sum(bool(grid['tiles'][py][px][3]) for px,py in path),len(path),y,x,neighbors[0]))
        if not candidates: raise RuntimeError('Не найдена безопасная трава '+self.route)
        _,_,y,x,neighbor=min(candidates);self.grass=(x,y);self.farm_pair=(self.grass,neighbor)
        self.bot.event('grind_area_selected',f'{self.route}: трава {self.grass}, выход к Viridian Center без обзора тренеров',route=self.route,tiles=self.farm_pair)
        self.go(self.grass,search=True)

    def healthy_fighters(self,state):
        return [m for m in state['party'] if m['uid'] in self.fighters and m['hp']>0]

    def need_heal(self,s):
        fighters=self.healthy_fighters(s)
        trainee=self.mon(s,self.trainee)
        return len(fighters)<=1 or trainee['hp']/max(1,trainee['max_hp'])<self.threshold or trainee['status']!='В норме' or not any(
            m['hp']/m['max_hp']>=self.threshold and m['status']=='В норме' and any(a['power'] and a['current_pp'] for a in m['moves']) for m in fighters)

    def choose_fighter(self,s):
        enemies=s.get('battle',{}).get('enemies',[])
        if not enemies: return None
        enemy=enemies[0]; candidates=[m for m in self.healthy_fighters(s) if best_move(m,enemy,self.root) is not None]
        return max(candidates,key=lambda m:(m['hp']/m['max_hp']>=self.threshold,m['hp']/m['max_hp'],m['level']),default=None)

    def battle_fighter(self,s,current):
        if current and current['uid'] in self.fighters and current['hp']/current['max_hp']>=self.threshold and current['status']=='В норме' and self.attack_choice(current,s['battle']['enemies'][0]) is not None:return current
        return self.choose_fighter(s)

    def attack_choice(self,mon,enemy):return best_move(mon,enemy,self.root)

    def learn_dialog(self,s):
        c=s['controls']
        self.check_events(s)
        if s.get('move_plan',{}).get('managed'):self.wait(6);return True
        if c['callback']=='BattleMainCB2' and c['battle_script_opcode'] in (0x5a,0x5b):
            self.wait(1);return True
        for task in c['tasks']:
            if task['name']=='Task_EvolutionScene':
                self.tap('A'); return True
        return False

    def fight(self,retreat=False,travel=False):
        self.stage('Бой: оцениваем противника' if not retreat else 'Отступление к Pokémon Center')
        start=self.state(); deadline=start['frame']+36000;escape_attempts=0
        while self.state()['frame']<deadline:
            s=self.state(); c=s['controls']
            if self.learn_dialog(s): continue
            if not s['in_battle']:
                if c['callback']=='CB2_Overworld' and not c['field_locked']:
                    self.battles+=1
                    trainee=next((m for m in s['party'] if m['uid']==self.trainee),None)
                    if trainee:self.bot.log(f"Бой завершён · {trainee['nickname']} Lv {trainee['level']} · XP {trainee['experience']} · до уровня {trainee['exp_to_next_level']}")
                    return
                self.wait(); continue
            trainer=getattr(self,'trainer_permission',lambda _:False)(s)
            if s['battle']['flags'] & (8|1|2|0x40|0x80|0x200) and not trainer: raise TrainingProblem('unexpected_battle','Неожиданный тип боя: бот рассчитан только на обычные одиночные дикие бои')
            if trainer:retreat=False
            else:retreat |= self.need_heal(s) if self.config.get('auto_team') else len(self.healthy_fighters(s))<=1 or self.mon(s,self.trainee)['hp']==0
            tasks={t['name'] for t in c['tasks']}
            if 'Task_HandleChooseMonInput' in tasks or 'Task_HandleSelectionMenuInput' in tasks:
                fighter=self.choose_fighter(s)
                if self.config.get('training_approach','legacy')!='legacy' and not retreat:
                    from .training_tactics import choose
                    decision=choose(s,None,self.trainee,self.root,mode=(getattr(self,'plan',None) or {}).get('tactic','careful'),mentor=(getattr(self,'plan',None) or {}).get('primary_mentor'),fighters=self.fighters,free_switch=True)
                    fighter=decision['mon'] if decision else None
                    if fighter is None:retreat=True
                if retreat:
                    runner=getattr(self,'runner',None)
                    fighter=next((m for m in s['party'] if m['uid']==runner and m['hp']>0),None) or max((m for m in s['party'] if m['hp']>0),key=lambda m:m.get('stats',{}).get('speed',0),default=None)
                if fighter is None: raise TrainingProblem('no_fighter','Нет живого бойца с доступной атакой для обязательной замены. Возьми управление.')
                self.party_select(fighter['uid']); continue
            controller=c['controllers'][0]
            from .battle_conditions import switch_blockers,escape_blockers
            blocked=switch_blockers(s)
            ally=s['battle']['allies'][0] if s['battle']['allies'] else None
            current=next((m for m in s['party'] if ally and m['slot']==ally['party_slot']),None)
            forced_combat=bool(current and blocked and (not retreat or escape_blockers(s,current)))
            if controller=='HandleInputChooseAction':
                ally=s['battle']['allies'][0] if s['battle']['allies'] else None
                current=next((m for m in s['party'] if ally and m['slot']==ally['party_slot']),None)
                if forced_combat:
                    self.bot.event('battle_recovery','Замена/побег заблокированы: продолжаем бой текущим Pokémon',action='fight_trapped',pokemon_uid=current['uid'],reasons=blocked,retreat=retreat,hp=current['hp'],status=current.get('status'))
                    self.grid_choice(c['action_cursor'][0],0);continue
                if retreat:
                    runner=getattr(self,'runner',None)
                    if current and self.config.get('training_approach','legacy')!='legacy':
                        from .training_tactics import escape_support
                        reserve=escape_support(s,current,self.root)
                        if reserve and reserve['uid']!=current['uid']:
                            self.grid_choice(c['action_cursor'][0],2);self.party_select(reserve['uid']);continue
                    elif current and not blocked and ((runner and current['uid']!=runner) or (not runner and current['uid'] not in self.fighters)):
                        reserve=next((m for m in s['party'] if m['uid']==runner and m['hp']>0),None) if runner else max(self.healthy_fighters(s),key=lambda m:m['stats']['speed'],default=None)
                        if reserve:
                            self.grid_choice(c['action_cursor'][0],2);self.party_select(reserve['uid']);continue
                    escape_attempts+=1
                    if escape_attempts>5:raise TrainingProblem('escape_failed','Пять попыток убежать не удались. Возьми управление.')
                    self.want_heal |= not travel
                    from .field_tools import teleport_slot
                    teleport=teleport_slot(current) if runner and current and current['uid']==runner else None
                    self.escape_move=teleport
                    self.bot.event('battle_escape','Побег: Teleport' if teleport is not None else 'Пытаемся убежать',pokemon_uid=current['uid'] if current else None,attempt=escape_attempts,travel=travel,method='teleport' if teleport is not None else 'run')
                    self.grid_choice(c['action_cursor'][0],0 if teleport is not None else 3);continue
                if current is None: self.wait(); continue
                fighter=self.battle_fighter(s,current)
                if fighter is None:retreat=True;continue
                if fighter['uid']!=current['uid']:
                    self.grid_choice(c['action_cursor'][0],2)
                    self.bot.event('battle_switch','Выходим бойцом: '+fighter['nickname'],pokemon_uid=fighter['uid'],reason='switch_training' if current['uid']==self.trainee else 'hp_or_pp')
                    self.party_select(fighter['uid'])
                else: self.grid_choice(c['action_cursor'][0],0)
            elif controller=='HandleInputChooseMove':
                if forced_combat:
                    choice=self.attack_choice(current,s['battle']['enemies'][0])
                    if choice is None:
                        from .battle_conditions import move_blockers
                        choice=next((i for i,a in enumerate(current['moves']) if not move_blockers(current,a)),None)
                    if choice is None:raise TrainingProblem('trapped_no_action','Замена заблокирована, а меню не предлагает доступный приём')
                    self.bot.event('battle_attack','Заблокированный Pokémon: '+current['moves'][choice]['name'],pokemon_uid=current['uid'],move_id=current['moves'][choice]['id'],reason='trapped_recovery')
                    self.grid_choice(c['move_cursor'][0],choice);continue
                if retreat:
                    if getattr(self,'escape_move',None) is not None:self.grid_choice(c['move_cursor'][0],self.escape_move);self.escape_move=None
                    else:self.tap('B')
                    continue
                ally=s['battle']['allies'][0]; mon=next(m for m in s['party'] if m['slot']==ally['party_slot'])
                if self.config.get('training_policy')=='coverage' or self.config.get('training_approach','legacy')!='legacy':
                    desired=self.battle_fighter(s,mon)
                    if desired is None or desired['uid']!=mon['uid']:self.tap('B');continue
                choice=self.attack_choice(mon,s['battle']['enemies'][0])
                if choice is None:
                    self.tap('B')
                    if not self.config.get('auto_team'):retreat=True
                else:
                    attack=mon['moves'][choice]
                    self.bot.event('battle_attack',mon['nickname']+' → '+attack['name'],pokemon_uid=mon['uid'],move_id=attack['id'],enemy=s['battle']['enemies'][0]['species'])
                    self.grid_choice(c['move_cursor'][0],choice)
            else: self.tap('A',wait=12)
        raise TimeoutError('Бой длится слишком долго. Возьми управление и проверь экран.')

    def run(self):
        validate(self.state(),self.config)
        self.route=select_route(self.state()['map']['name'])
        self.bot.event('training_route_selected',self.route+' · цель Lv '+str(self.target),route=self.route)
        self.heal(); self.to_grass()
        deadline=self.state()['frame']+60*60*60*12
        while self.state()['frame']<deadline:
            s=self.state()
            if s['map']['name'] not in ALLOWED: raise TrainingProblem('location_changed','Неожиданная локация: '+s['map']['name'])
            if s['in_battle']: self.fight(retreat=self.want_heal); continue
            self.check_events(s)
            if self.want_heal or self.need_heal(s): self.heal(); self.to_grass(); continue
            self.lead(self.trainee)
            self.stage('Ищем диких покемонов: '+self.route)
            p=self.state()['position'];here=(p['x'],p['y'])
            target=self.farm_pair[1] if here==self.farm_pair[0] else self.farm_pair[0]
            self.go(target,search=True)
        raise TimeoutError('Достигнут лимит 12 игровых часов. Проверь команду.')

def run_training(bot):
    config=json.loads((bot.project_dir/'Data/training.json').read_text())
    try:
        if config.get('auto_team'):
            from .grind import GrindTrainer
            GrindTrainer(bot,config).run()
        else:RouteTrainer(bot,config).run()
    except (TimeoutError,RuntimeError,ValueError) as error:
        from .bot import ControlLost
        if isinstance(error,ControlLost):raise
        code=getattr(error,'code','training_timeout' if isinstance(error,TimeoutError) else 'training_blocked')
        bot.handoff(code,'Прокачка остановлена: '+str(error),error_type=type(error).__name__)

# Existing scripts and saves may still refer to the original entry points.
Route1Trainer=RouteTrainer
run_route1=run_training
