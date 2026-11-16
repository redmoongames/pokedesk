"""Shore-based fishing and bounded Surf strips, separate from foot navigation."""
from collections import deque
import heapq
from .acquisition_play import AcquisitionAttention
from .training import walk_neighbors,trainer_zones
from .movement import npc_envelope
from .telemetry import read_map,symbols,read_walk_state
from .engine import BUTTONS

RODS={'old_rod':262,'good_rod':263,'super_rod':264}
# Still water only: no waterfalls, rapids or forced currents.
WATER={0x10,0x12,0x15}
DIRECTIONS={(0,-1):('UP',2),(-1,0):('LEFT',3),(1,0):('RIGHT',4),(0,1):('DOWN',1)}

def blocked_cells(grid):
    return (set(map(tuple,grid.get('obstacles',[])))|npc_envelope(grid)|trainer_zones(grid)|set(map(tuple,grid.get('script_triggers',[])))|{(w['x'],w['y']) for w in grid.get('warps',[])})

def is_water(grid,point):
    x,y=point
    return 0<=x<grid['width'] and 0<=y<grid['height'] and grid['tiles'][y][x][0]==0 and grid['tiles'][y][x][1] in WATER

def water_path(grid,start,goal):
    start=tuple(start);goal=tuple(goal);blocked=blocked_cells(grid);blocked.discard(start);prev={start:None};queue=deque([start])
    while queue:
        point=queue.popleft()
        if point==goal:
            result=[]
            while prev[point] is not None:result.append(point);point=prev[point]
            return result[::-1]
        for dx,dy in DIRECTIONS:
            other=(point[0]+dx,point[1]+dy)
            if other not in prev and other not in blocked and is_water(grid,other):prev[other]=point;queue.append(other)
    raise AcquisitionAttention('Нет безопасного водного пути к берегу / участку встреч')

def shore_paths(grid,start,goals):
    """Foot approaches respect elevation; Surf is a separate movement owner."""
    start=tuple(start);goals=set(map(tuple,goals));blocked=blocked_cells(grid);blocked.discard(start)
    queue=[((0,0),start)];cost={start:(0,0)};prev={start:None};found={}
    while queue:
        value,point=heapq.heappop(queue)
        if cost[point]!=value:continue
        if point in goals:
            path=[];cursor=point
            while prev[cursor] is not None:path.append(cursor);cursor=prev[cursor]
            found[point]=path[::-1]
            if len(found)==len(goals):break
        for other in walk_neighbors(grid,point,blocked):
            old=grid['tiles'][point[1]][point[0]][2];new=grid['tiles'][other[1]][other[0]][2]
            if abs(other[0]-point[0])+abs(other[1]-point[1])==1 and old and new and old!=new:continue
            candidate=(value[0]+bool(grid['tiles'][other[1]][other[0]][3]),value[1]+1)
            if candidate<cost.get(other,(float('inf'),float('inf'))):cost[other]=candidate;prev[other]=point;heapq.heappush(queue,(candidate,other))
    return found

def approach_shore(p,farm):
    state=p.state();point=(state['position']['x'],state['position']['y']);goal=tuple(farm['shore'])
    if point==goal:return True
    path=shore_paths(read_map(p.g),point,[goal]).get(goal)
    if path is None:raise AcquisitionAttention('Путь к берегу больше не доступен')
    for step in path:
        p.go(step,encounters='local')
        if p.state()['in_battle'] or read_walk_state(p.g).get('battle_pending'):return False
    return True

def water_spot(grid,start,method):
    start=tuple(start);blocked=blocked_cells(grid);shores=[]
    for y,row in enumerate(grid['tiles']):
        for x,t in enumerate(row):
            p=(x,y)
            if t[0] or p in blocked or 0x10<=t[1]<=0x1c or 0x30<=t[1]<=0x71:continue
            for dx,dy in DIRECTIONS:
                entry=(x+dx,y+dy)
                if is_water(grid,entry) and entry not in blocked:shores.append((p,entry))
    afloat=is_water(grid,start);land_paths={} if afloat else shore_paths(grid,start,[p for p,_ in shores])
    choices=[]
    for shore,entry in shores:
        if afloat:
            try:approach=water_path(grid,start,entry)
            except RuntimeError:continue
        else:
            if shore not in land_paths:continue
            approach=land_paths[shore]
        if method in RODS:
            choices.append(dict(shore=shore,entry=entry,pair=[shore,shore],path=approach,start_water=afloat,terrain='fishing',length=1))
        else:
            for dx,dy in DIRECTIONS:
                other=(entry[0]+dx,entry[1]+dy)
                if other in blocked or not is_water(grid,other):continue
                if not grid['tiles'][entry[1]][entry[0]][3] or not grid['tiles'][other[1]][other[0]][3]:continue
                choices.append(dict(shore=shore,entry=entry,pair=[entry,other],path=approach,start_water=afloat,terrain='water',length=2))
    if not choices:raise AcquisitionAttention('Нет доступного безопасного берега / водного участка без NPC, событий и препятствий')
    return min(choices,key=lambda r:(sum(bool(grid['tiles'][y][x][3]) for x,y in r['path']) if not afloat else 0,len(r['path']),r['shore'],r['entry']))

def surfing(game):return bool(game.read8(symbols(game.root)['gPlayerAvatar'])&8)

def face(p,start,target):
    dx,dy=target[0]-start[0],target[1]-start[1];key,direction=DIRECTIONS[dx,dy];sy=symbols(p.g.root)
    for _ in range(30):
        s=p.state();pos=s['position']
        if s['in_battle'] or read_walk_state(p.g).get('battle_pending'):return False
        if (pos['x'],pos['y'])!=tuple(start):raise AcquisitionAttention('Изменилась точка на берегу')
        obj=sy['gObjectEvents']+36*p.g.read8(sy['gPlayerAvatar']+5)
        if p.g.read8(obj+24)&15==direction and not s['controls']['moving']:return True
        p.tap(key,frames=1,wait=12)
    raise AcquisitionAttention('Не удалось повернуться к воде')

def swim_step(p,target,*,landing=False):
    g=p.g;s=p.state();name=s['map']['name'];start=(s['position']['x'],s['position']['y']);target=tuple(target)
    if s['in_battle'] or read_walk_state(g).get('battle_pending'):return False
    if start==target:return True
    if not surfing(g):raise AcquisitionAttention('Для движения по воде нужен активный Surf')
    if abs(target[0]-start[0])+abs(target[1]-start[1])!=1:raise AcquisitionAttention('Водный шаг должен вести на соседнюю клетку')
    grid=read_map(g)
    if target in blocked_cells(grid) or not landing and not is_water(grid,target):raise AcquisitionAttention('Водный путь перекрыт')
    key,_=DIRECTIONS[target[0]-start[0],target[1]-start[1]];arrived=False
    try:
        for _ in range(150):
            c=read_walk_state(g)
            if c.get('in_battle') or c.get('battle_pending'):return False
            if c.get('map')!=name:raise AcquisitionAttention('Изменилась карта во время плавания')
            point=tuple(c.get('position') or ())
            if point==target:arrived=True
            elif point!=start:raise AcquisitionAttention('Игрок отклонился от водного пути')
            if arrived and not c.get('moving'):return True
            if not c.get('open'):p.advance(1);continue
            p.advance(1,0 if arrived else BUTTONS[key])
    finally:g.advance(0,0)
    raise AcquisitionAttention('Не завершился водный шаг')

def leave_water(p,farm):
    s=p.state();here=(s['position']['x'],s['position']['y'])
    if not surfing(p.g):return True
    for point in water_path(read_map(p.g),here,farm['entry']):
        if not swim_step(p,point):return False
    if not swim_step(p,farm['shore'],landing=True):return False
    if surfing(p.g) and not p.state()['in_battle']:raise AcquisitionAttention('Не подтверждён выход из воды')
    return True

def board(p,farm):
    if surfing(p.g):return
    grid=read_map(p.g);name=grid['name']
    if tuple(farm['entry']) in blocked_cells(grid) or not is_water(grid,tuple(farm['entry'])):raise AcquisitionAttention('Вход в воду больше не безопасен')
    if not face(p,tuple(farm['shore']),tuple(farm['entry'])):return
    began=False
    for _ in range(350):
        s=p.state()
        if s['in_battle'] or read_walk_state(p.g).get('battle_pending'):return
        position=(s['position']['x'],s['position']['y'])
        if s['map']['name']!=name or position not in (tuple(farm['shore']),tuple(farm['entry'])):raise AcquisitionAttention('Место входа в воду изменилось')
        if surfing(p.g):
            p.advance(30)
            after=p.state()['controls']
            if after['callback']=='CB2_Overworld' and not after['field_locked'] and not after['moving']:return
            p.advance(1);continue
        c=s['controls'];tasks=p.tasks(s)
        if c['callback']!='CB2_Overworld':raise AcquisitionAttention('При Surf открылось другое меню')
        if c['field_locked']:began=True
        elif began and not surfing(p.g):raise AcquisitionAttention('Игра не разрешила Surf: '+p.text())
        if 'Task_YesNoMenu_HandleInput' in tasks and c['menu_cursor']!=0:p.tap('UP',frames=1,wait=10)
        else:p.tap('A',frames=1,wait=10)
    raise AcquisitionAttention('Surf не начался за отведённое время')

def open_bag_item(p,item):
    from .field_item_menu import use_field_item
    return use_field_item(p,item,started=lambda:'Task_Fishing' in p.tasks())


def cast(p,method):
    open_bag_item(p,RODS[method]);seen=False
    for _ in range(3600):
        s=p.state();task=next((t for t in s['controls']['tasks'] if t['name']=='Task_Fishing'),None)
        if s['in_battle']:p.g.advance(0,0);return True
        if task:
            seen=True
            if task['data'][15]!=list(RODS).index(method):raise AcquisitionAttention('Игра выбрала другую удочку')
            # Press only while the verified fishing task owns the field. In
            # FRLG a bite reels automatically; A also closes a failed cast.
            p.advance(1,BUTTONS['A'] if p.g.frame%4==0 else 0)
        elif seen:
            for _ in range(240):
                state=p.state();c=state['controls']
                if state['in_battle']:return True
                if c['callback']=='CB2_Overworld' and not c['field_locked']:return False
                p.advance(1)
            raise AcquisitionAttention('Не завершился переход от удочки к бою')
        else:p.advance(1)
    raise AcquisitionAttention('Рыбалка не завершилась за отведённое время')
