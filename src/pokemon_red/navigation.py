"""Safe map-portal graph and clinic/grass planning, independent of grind strategy."""
import heapq
import itertools
from .training import path_to,trainer_zones,TrainingProblem,walk_neighbors
from .zones import zone_spec


def _nearest_grass_pair(grid,start,bounds=None,terrain='grass'):
    """One Dijkstra sweep, not one full path search per grass tile."""
    blocked=set(map(tuple,grid.get('obstacles',[])))|trainer_zones(grid)|set(map(tuple,grid.get('script_triggers',[])))
    blocked|={(w['x'],w['y']) for w in grid.get('warps',[])}
    start=tuple(start);blocked.discard(start);queue=[(0,0,start)];cost={start:(0,0)};previous={start:None}
    def walkable(x,y):
        if not(0<=x<grid['width'] and 0<=y<grid['height']) or (x,y) in blocked:return False
        collision,behavior,_,_=grid['tiles'][y][x]
        return not collision and not(0x10<=behavior<=0x1c or 0x30<=behavior<=0x5f or 0x60<=behavior<=0x71)
    while queue:
        grass,steps,point=heapq.heappop(queue)
        if cost[point]!=(grass,steps):continue
        x,y=point;allowed=bounds is None or bounds[0]<=x<=bounds[2] and bounds[1]<=y<=bounds[3]
        def encounter(x,y):return grid['tiles'][y][x][1] in grid.get('land_encounter_behaviors',[8 if terrain=='cave' else 2]) and bool(grid['tiles'][y][x][3])
        if allowed and encounter(x,y):
            neighbors=[(x+dx,y+dy) for dx,dy in ((1,0),(-1,0),(0,1),(0,-1)) if walkable(x+dx,y+dy) and encounter(x+dx,y+dy) and (bounds is None or bounds[0]<=x+dx<=bounds[2] and bounds[1]<=y+dy<=bounds[3])]
            neighbors=[p for p in neighbors if p in walk_neighbors(grid,point,blocked) and point in walk_neighbors(grid,p,blocked)]
            if neighbors:
                path=[];p=point
                while previous[p] is not None:path.append(p);p=previous[p]
                return dict(pair=[point,neighbors[0]],path=path[::-1],grass=grass,steps=steps)
        for nx,ny in walk_neighbors(grid,point,blocked):
            new=(grass+int(bool(grid['tiles'][ny][nx][3])),steps+1)
            if new<cost.get((nx,ny),(float('inf'),float('inf'))):cost[nx,ny]=new;previous[nx,ny]=point;heapq.heappush(queue,(*new,(nx,ny)))
    raise TrainingProblem('no_safe_grass','Нет доступной травы без обзора тренеров и активных сюжетных событий')

def safe_grass_pair(grid,start,bounds=None,terrain='grass'):
    """Prefer an accessible long straight strip; keep a safe two-cell fallback.

    Cost penalizes short strips without sending the player across an entire
    map just to gain one extra tile. Endpoints remain the historical `pair` API.
    """
    from .movement import corridor_hazards,MAX_SEGMENT
    blocked=set(map(tuple,grid.get('obstacles',[])))|trainer_zones(grid)|set(map(tuple,grid.get('script_triggers',[])))
    blocked|={(w['x'],w['y']) for w in grid.get('warps',[])}
    start=tuple(start);blocked.discard(start);cost={start:(0,0)};previous={start:None};queue=[(0,0,start)]
    while queue:
        grass,steps,p=heapq.heappop(queue)
        if cost[p]!=(grass,steps):continue
        for x,y in walk_neighbors(grid,p,blocked):
            value=(grass+int(bool(grid['tiles'][y][x][3])),steps+1)
            if value<cost.get((x,y),(float('inf'),float('inf'))):cost[x,y]=value;previous[x,y]=p;heapq.heappush(queue,(*value,(x,y)))
    hazards=corridor_hazards(grid);allowed=set()
    for y in range(1,grid['height']-1):
        for x in range(1,grid['width']-1):
            p=(x,y);collision,behavior,_,encounter=grid['tiles'][y][x]
            if p in cost and p not in hazards and not collision and behavior in grid.get('land_encounter_behaviors',[8 if terrain=='cave' else 2]) and encounter and (bounds is None or bounds[0]<=x<=bounds[2] and bounds[1]<=y<=bounds[3]):allowed.add(p)
    best=None
    for dx,dy in ((1,0),(0,1)):
        for p in sorted(allowed):
            before=(p[0]-dx,p[1]-dy)
            if before in allowed and grid['tiles'][before[1]][before[0]][2]==grid['tiles'][p[1]][p[0]][2] and p in walk_neighbors(grid,before,blocked) and before in walk_neighbors(grid,p,blocked):continue
            line=[];q=p
            while q in allowed:
                if line and (grid['tiles'][q[1]][q[0]][2]!=grid['tiles'][line[-1][1]][line[-1][0]][2] or q not in walk_neighbors(grid,line[-1],blocked) or line[-1] not in walk_neighbors(grid,q,blocked)):break
                line.append(q);q=q[0]+dx,q[1]+dy
            if len(line)<3:continue
            for offset in range(max(1,len(line)-MAX_SEGMENT)):
                strip=line[offset:offset+MAX_SEGMENT+1]
                for oriented in (strip,strip[::-1]):
                    endpoint=oriented[0];grass,steps=cost[endpoint]
                    score=(max(0,9-len(strip))*12+steps+grass,-len(strip),endpoint)
                    if best is None or score<best[0]:best=(score,oriented)
    if best is None:
        result=_nearest_grass_pair(grid,start,bounds,terrain);return dict(result,strip=result['pair'],length=2,continuous=False)
    strip=best[1];entry=strip[0];path=[];p=entry
    while previous[p] is not None:path.append(p);p=previous[p]
    return dict(pair=[strip[0],strip[-1]],strip=strip,length=len(strip),continuous=True,path=path[::-1],grass=cost[entry][0],steps=cost[entry][1])

def path_block_reason(grid,start,goal):
    """Diagnose only a proven blocked local connection; never unlock the game."""
    from .locations import location_name
    label=location_name(grid.get('name',''))
    cuts={(o['x'],o['y']) for o in grid.get('objects',[]) if o.get('graphics_id')==grid.get('cut_graphics',95)}
    tests=[]
    if cuts:tests.append((dict(grid,obstacles=[p for p in grid.get('obstacles',[]) if tuple(p) not in cuts]),'Дерево Cut · '+label+' — нужны значок для Cut и Pokémon с Cut в текущей команде или доступная подготовка в PC'))
    if grid.get('script_triggers'):
        message='Активное сюжетное событие · '+label+' — пройди его вручную'
        if grid.get('name') in ('Route5_SouthEntrance','Route6_NorthEntrance','Route7_EastEntrance','Route8_WestEntrance'):message='Охрана Saffron: сначала отдай чай охраннику вручную'
        tests.append((dict(grid,script_triggers=[]),message))
    if any(not t.get('defeated') for t in grid.get('trainers',[])):tests.append((dict(grid,trainers=[dict(t,defeated=True) for t in grid.get('trainers',[])]),'Обзор непобеждённого тренера · '+label+' — сначала пройди бой вручную'))
    for altered,reason in tests:
        try:path_to(altered,start,goal);return reason
        except RuntimeError:pass
    from .movement import npc_envelope
    envelope=npc_envelope(grid);anchors={(o['x'],o['y']) for o in grid.get('objects',[])}
    if envelope-anchors:
        altered=dict(grid,obstacles=[p for p in grid.get('obstacles',[]) if tuple(p) not in envelope-anchors])
        try:
            path_to(altered,start,goal)
            return 'Проход занят зоной движения NPC · '+label+' — автопуть пока не может гарантировать проход; пересеките этот участок вручную'
        except RuntimeError:pass
    scripted=[o.get('block_reason') for o in grid.get('objects',[]) if o.get('block_reason')]
    if scripted:return scripted[0]
    return 'Нет безопасного прохода · '+label+' (препятствие, уступ или несколько ограничений)'


def grass_block_reason(grid,start,bounds,terrain):
    """Counterfactual diagnostic on detached grids; no game flags are changed."""
    from itertools import combinations
    from .locations import location_name
    cuts={(o['x'],o['y']) for o in grid.get('objects',[]) if o.get('graphics_id')==grid.get('cut_graphics',95)}
    kinds=(['Cut'] if cuts else [])+(['тренер'] if any(not t.get('defeated') for t in grid.get('trainers',[])) else [])+(['сюжет'] if grid.get('script_triggers') else [])
    for count in range(1,len(kinds)+1):
        for removed in combinations(kinds,count):
            altered=dict(grid)
            if 'Cut' in removed:altered.update(objects=[o for o in grid.get('objects',[]) if (o['x'],o['y']) not in cuts],obstacles=[p for p in grid.get('obstacles',[]) if tuple(p) not in cuts])
            if 'тренер' in removed:altered['trainers']=[dict(t,defeated=True) for t in grid.get('trainers',[])]
            if 'сюжет' in removed:altered['script_triggers']=[]
            try:_nearest_grass_pair(altered,start,bounds,terrain)
            except RuntimeError:continue
            return 'Доступ к траве · '+location_name(grid.get('name',''))+': '+', '.join(removed)+' — сначала пройди препятствие вручную'
    return 'Не найден безопасный участок травы и путь обратно; пройди местных тренеров вручную'


class Navigator:
    def __init__(self,trainer):
        self.t=trainer;self.bot=trainer.bot;self.spec=zone_spec(trainer.root);self.grids={};self.serial=itertools.count();self.path_cache={};self.path_failures={};self.tool_inventory=None;self.tool_mode='owned';self.cut_enabled=False
        from .portal_graph import PortalGraph
        self.portals=PortalGraph(self.spec)
        from .path_cache import shared_cache
        self.shared_paths=shared_cache(trainer.root);self.grid_keys={};self.local_costs={};self._adjacency=None;self.plan_cache={};self.clinic_cache={}
    def configure_tools(self,inventory,mode='owned'):
        from .field_tools import available
        self._initial_nav=None;self.tool_inventory=inventory;self.tool_mode=mode
        owned=inventory.get('party',[])+(inventory.get('boxes',[]) if mode=='owned' else [])
        tools=available(owned,inventory.get('field_badges',[]),inventory.get('game','firered'));self.cut_enabled=bool(tools['cut']['unlocked'] and tools['cut']['providers']);self.grids.clear();self.grid_keys.clear();self.path_cache.clear();self.path_failures.clear();self.local_costs.clear();self.plan_cache.clear();self.clinic_cache.clear()
        return self
    def initial_tools(self):
        if not self.tool_inventory or self.tool_mode=='party':return self
        if self._initial_nav is None:self._initial_nav=type(self)(self.t).configure_tools(self.tool_inventory,'party')
        return self._initial_nav
    def adjacency(self):
        token=id(self.spec['links'])
        if self._adjacency is None or self._adjacency[0]!=token:
            forward={};reverse={}
            for e in self.spec['links']:
                forward.setdefault(e['source'],[]).append(e)
                reverse.setdefault(e['destination'],set()).add(e['source'])
            self._adjacency=(token,forward,reverse)
        return self._adjacency[1:]
    def local_cost(self,name,start,goal,path):
        key=(name,tuple(start),tuple(goal))
        if key not in self.local_costs:
            grid=self.grid(name)
            self.local_costs[key]=(sum(bool(grid['tiles'][y][x][3]) for x,y in path),len(path)+24*len(self.path_actions(name,path)))
        return self.local_costs[key]
    def path_actions(self,name,path):
        points=set(map(tuple,path));return [dict(tool='cut',map=name,local_id=o['local_id'],x=o['x'],y=o['y']) for o in self.grid(name).get('objects',[]) if self.cut_enabled and o.get('graphics_id')==self.grid(name).get('cut_graphics',95) and (o['x'],o['y']) in points]
    def grid(self,name):
        if name not in self.grids:
            value=self.bot.map(name)
            if not value or value.get('name')!=name:raise TrainingProblem('navigation_update_required','Перезапусти приложение, чтобы загрузить новую навигацию')
            from .field_tools import cut_grid
            self.grids[name]=cut_grid(value,self.cut_enabled)
        return self.grids[name]
    def reset(self):self.grids.clear();self.grid_keys.clear();self.path_cache.clear();self.path_failures.clear();self.local_costs.clear();self.plan_cache.clear();self.clinic_cache.clear()
    def grid_key(self,name):
        if name not in self.grid_keys:
            from .path_cache import map_key
            self.grid_keys[name]=map_key(self.grid(name))
        return self.grid_keys[name]
    def local_path(self,name,start,goal):
        key=(name,tuple(start),tuple(goal))
        if key in self.path_failures:raise RuntimeError('Blocked local connection')
        if key not in self.path_cache:
            grid=self.grid(name);geometry=self.grid_key(name)
            cached=self.shared_paths.get('path',geometry,name,tuple(start),tuple(goal))
            if cached is None and tuple(start) in self.portals.nodes[name]:cached=self.portals.connect(name,start,goal,grid,geometry,self.shared_paths)
            if cached is not None:
                if not cached['ok']:
                    self.path_failures[key]=True;raise RuntimeError('Blocked local connection')
                self.path_cache[key]=[tuple(p) for p in cached['value']]
            else:
                try:self.path_cache[key]=path_to(grid,start,goal)
                except RuntimeError:
                    self.path_failures[key]=True
                    self.shared_paths.put('path',geometry,[name,tuple(start),tuple(goal)],dict(ok=False))
                    raise
                self.shared_paths.put('path',geometry,[name,tuple(start),tuple(goal)],dict(ok=True,value=self.path_cache[key]))
        return self.path_cache[key]
    def farm_area(self,name,entry,bounds=None,terrain='grass'):
        geometry=self.grid_key(name);points=[name,tuple(entry),bounds,terrain]
        cached=self.shared_paths.get('farm',geometry,*points)
        if cached is None:
            try:value=safe_grass_pair(self.grid(name),entry,bounds,terrain)
            except TrainingProblem as error:
                self.shared_paths.put('farm',geometry,points,dict(ok=False,code=error.code,message=str(error)));raise
            cached=dict(ok=True,value=value);self.shared_paths.put('farm',geometry,points,cached)
        if not cached['ok']:raise TrainingProblem(cached['code'],cached['message'])
        value=cached['value']
        return dict(value,**{k:[tuple(p) for p in value[k]] for k in ('pair','strip','path') if k in value})
    def plan(self,start_map,start,destination,goal=None,*,diagnose=True):
        from .topology import WorldTopology
        from copy import deepcopy
        key=(id(self.spec['links']),start_map,tuple(start),destination,tuple(goal) if goal is not None else None)
        if key in self.plan_cache:return deepcopy(self.plan_cache[key])
        topology=WorldTopology(self.spec['links'])
        for allowed in topology.corridors(start_map,destination):
            try:
                result=self._plan_cells(start_map,start,destination,goal,diagnose=False,allowed=allowed)
                self.plan_cache[key]=result;return deepcopy(result)
            except TrainingProblem:pass
        # Diagnostics are reserved for the user-facing failure, not every trial.
        return self._plan_cells(start_map,start,destination,goal,diagnose=diagnose)
    def _plan_cells(self,start_map,start,destination,goal=None,*,diagnose=True,allowed=None):
        # Coarse directed graph first: never decode a map which cannot lead to
        # the requested destination. Exact cell searches still decide all edges.
        forward,reverse=self.adjacency();relevant={destination};pending=[destination]
        while pending:
            for name in reverse.get(pending.pop(),()):
                if name not in relevant:relevant.add(name);pending.append(name)
        failures=[]
        start=(start_map,tuple(start));distance={start:(0,0)};queue=[(0,0,next(self.serial),start,[])];best=None
        while queue:
            grass,steps,_,node,links=heapq.heappop(queue)
            if distance[node]!=(grass,steps):continue
            name,point=node
            if name==destination:
                try:path=self.local_path(name,point,goal) if goal is not None else []
                except RuntimeError:path=None;failures.append((name,point,goal,name))
                if path is not None:
                    total=(grass+self.local_cost(name,point,goal,path)[0] if goal is not None else grass,steps+self.local_cost(name,point,goal,path)[1] if goal is not None else steps)
                    if best is None or total<best['cost']:best=dict(links=links,cost=total,arrival=point,goal=tuple(goal) if goal is not None else None,map=destination)
            if best is not None and (grass,steps)>best['cost']:continue
            for edge in forward.get(name,()):
                if edge['destination'] not in relevant or allowed is not None and edge['destination'] not in allowed:continue
                try:path=self.local_path(name,point,edge['point'])
                except RuntimeError:failures.append((name,point,edge['point'],edge['destination']));continue
                extra,local_steps=self.local_cost(name,point,edge['point'],path);value=(grass+extra,steps+local_steps+1);other=(edge['destination'],tuple(edge['arrival']))
                if value<distance.get(other,(float('inf'),float('inf'))):
                    distance[other]=value;heapq.heappush(queue,(*value,next(self.serial),other,[*links,edge]))
        if best is None:
            if not diagnose:
                raise TrainingProblem('no_safe_route','Нет безопасного пути при текущих препятствиях и доступных полевых действиях')
            if not self.cut_enabled:
                # A missing Cut can block a chain of local/portal connections;
                # probing one local path alone misses e.g. Route2's building.
                from .field_tools import cut_grid
                probe=type(self)(self.t);probe.spec=self.spec;probe.cut_enabled=True
                probe.grids={n:cut_grid(g,True) for n,g in self.grids.items()}
                try:opened=probe.plan(start[0],start[1],destination,goal,diagnose=False)
                except TrainingProblem:opened=None
                if opened and opened.get('field_actions'):
                    maps=list(dict.fromkeys(a['map'] for a in opened['field_actions']))
                    from .locations import location_name
                    where=' → '.join(location_name(n) for n in maps)
                    raise TrainingProblem('cut_required','Путь требует Cut · '+where+' — нужны значок для Cut и Pokémon с Cut в текущей команде; из PC его можно взять только в доступном Center.')
            # Prefer a blocked connection nearest the destination in the declared
            # topology, rather than mentioning an unrelated tree on another route.
            hops={destination:0}
            for _ in range(len(self.spec['links'])):
                changed=False
                for e in self.spec['links']:
                    if e['destination'] in hops and hops.get(e['source'],999)>hops[e['destination']]+1:hops[e['source']]=hops[e['destination']]+1;changed=True
                if not changed:break
            relevant=sorted(failures,key=lambda f:hops.get(f[3],999))
            reason=path_block_reason(self.grid(relevant[0][0]),relevant[0][1],relevant[0][2]) if relevant else 'Текущая область не связана с маршрутом проверенными переходами'
            raise TrainingProblem('no_safe_route',reason)

        actions=[];actual_steps=len(best['links']);name,point=start
        for edge in best['links']:
            local=self.local_path(name,point,edge['point']);actual_steps+=len(local);actions.extend(self.path_actions(name,local));name,point=edge['destination'],edge['arrival']
        if goal is not None:
            local=self.local_path(name,point,goal);actual_steps+=len(local);actions.extend(self.path_actions(name,local))
        best['field_actions']=actions;best['score']=best['cost'];best['cost']=(best['cost'][0],actual_steps)
        return best
    def current_plan(self,destination,goal=None,*,diagnose=True):
        state=self.t.state();p=state['position'];return self.plan(state['map']['name'],(p['x'],p['y']),destination,goal,diagnose=diagnose)
    def clinic_lower_bounds(self,initial):
        # Optimistic portal distances use coordinates only, with a factor of two
        # for ledge jumps. They prove a farther clinic cannot beat a verified
        # zero-encounter result; they never prove a blocked clinic accessible.
        state=initial.t.state();p=state['position'];start=(state['map']['name'],(p['x'],p['y']))
        distances={start:0};queue=[(0,next(self.serial),start)];bounds={};forward,_=self.adjacency()
        while queue:
            steps,_,node=heapq.heappop(queue)
            if steps!=distances[node]:continue
            name,point=node
            for key,hub in self.spec['hubs'].items():
                if hub['map']==name:
                    cost=steps+(abs(point[0]-hub['nurse'][0])+abs(point[1]-hub['nurse'][1]))//2
                    bounds[key]=min(bounds.get(key,float('inf')),cost)
            for edge in forward.get(name,()):
                cost=steps+(abs(point[0]-edge['point'][0])+abs(point[1]-edge['point'][1]))//2+1
                node2=(edge['destination'],tuple(edge['arrival']))
                if cost<distances.get(node2,float('inf')):distances[node2]=cost;heapq.heappush(queue,(cost,next(self.serial),node2))
        return bounds
    def nearest_clinic(self,onward=None,*,before_preparation=False):
        state=self.t.state();p=state['position'];key=(id(self.spec['links']),state['map']['name'],p['x'],p['y'],repr(onward),before_preparation)
        if key in self.clinic_cache:
            from copy import deepcopy
            return deepcopy(self.clinic_cache[key])
        options=[];initial=self.initial_tools() if before_preparation else self;bounds=self.clinic_lower_bounds(initial)
        for hub_id in sorted(self.spec['hubs'],key=lambda k:(bounds.get(k,float('inf')),k)):
            hub=self.spec['hubs'][hub_id]
            if hub_id not in bounds:continue
            if options:
                best=min(v[0] for v in options)
                if best[0]==0 and bounds[hub_id]>best[1]:continue
            try:
                plan=initial.current_plan(hub['map'],hub['nurse'],diagnose=False)
                if onward:self.plan(hub['map'],hub['nurse'],*onward,diagnose=False)
            except TrainingProblem:continue
            options.append((plan.get('score',plan['cost']),hub_id,plan))
        if not options and onward:
            # Distinguish an inaccessible first clinic from a blocked onward road.
            clinic,_=self.nearest_clinic(before_preparation=before_preparation)
            hub=self.spec['hubs'][clinic]
            self.plan(hub['map'],hub['nurse'],*onward)
        if not options:raise TrainingProblem('no_safe_clinic','До доступного Pokémon Center нет безопасного пути. Пройди препятствие вручную и заново запусти бота.')
        _,hub_id,plan=min(options,key=lambda p:p[0]);self.clinic_cache[key]=(hub_id,plan);return hub_id,plan
    def itinerary(self,destination,goal=None,*,pinned=(),preferred=()):
        from .travel_plan import itinerary
        return itinerary(self,destination,goal,pinned=pinned,preferred=preferred)
    def travel_prepared(self,destination,goal=None,*,pinned=(),preferred=()):
        from .travel_plan import travel_prepared
        return travel_prepared(self,destination,goal,pinned=pinned,preferred=preferred)
    def travel(self,destination,goal=None):
        self.reset();plan=self.current_plan(destination,goal)
        from .locations import location_name
        self.bot.event('navigation_plan','Путь: '+' → '.join(location_name(n) for n in [self.t.state()['map']['name'],*[e['destination'] for e in plan['links']]]),destination=destination,steps=plan['cost'][1],encounter_tiles=plan['cost'][0],transitions=[dict(source=e['source'],destination=e['destination'],point=e['point'],arrival=e['arrival']) for e in plan['links']])
        for edge in plan['links']:
            if self.t.state()['map']['name']!=edge['source']:raise TrainingProblem('navigation_map_changed','Карта изменилась при выполнении маршрута')
            self.reset();state=self.t.state();self.local_path(edge['source'],(state['position']['x'],state['position']['y']),edge['point'])
            self.t.go(tuple(edge['point']));self.t.transition(edge['direction'],edge['destination'],source=edge['source'],point=edge['point'])
            self.t.go(tuple(edge['arrival']))
            self.bot.event('navigation_transition','Переход: '+location_name(edge['destination']),source=edge['source'],destination=edge['destination'])
        if goal is not None:self.t.go(tuple(goal))
        return plan
    def choose_farm(self,zone):
        cache=getattr(self,'planning_cache',None)
        options=cache.route_farms(self,zone,self.t.root,lambda:self.farm_options(zone)) if cache else self.farm_options(zone)
        reasons=[]
        for farm in options:
            hub=self.spec['hubs'][farm['hub']]
            try:self.nearest_clinic((hub['map'],hub['nurse']),before_preparation=True)
            except TrainingProblem as error:reasons.append(str(error));continue
            return farm
        raise TrainingProblem('no_safe_grind_area',self.spec['zones'][zone]['label']+': '+(reasons[0] if reasons else 'Нет доступного Center'))
    def farm_options(self,zone):
        self.reset();record=self.spec['zones'][zone];options=[];reasons=[]
        # Every arrival portal is considered: Route 2 has disconnected parts and
        # Route 3 has both a Pewter entrance and a Mt. Moon entrance.
        entries={tuple(e['arrival']) for e in self.spec['links'] if e['destination']==record['map']}
        for hub_id in record['hubs']:
            hub=self.spec['hubs'][hub_id]
            for entry in sorted(entries):
                try:
                    plan=self.plan(hub['map'],hub['nurse'],record['map'],entry,diagnose=False);farm=self.farm_area(record['map'],entry,record.get('bounds'),record.get('terrain','grass'))
                    back=self.plan(record['map'],farm['pair'][0],hub['map'],hub['nurse'],diagnose=False)
                except RuntimeError as error:
                    reason=str(error)
                    if getattr(error,'code',None)=='no_safe_grass':reason='Нет безопасного участка гринда при текущих препятствиях; проверь тренеров, сюжет и Cut'
                    reasons.append(reason);continue
                cost=(plan['cost'][0]+farm['grass']+back['cost'][0],plan['cost'][1]+farm['steps']+back['cost'][1])
                actions=[*plan['field_actions'],*self.path_actions(record['map'],farm['path']),*back['field_actions']]
                options.append(dict(score=(cost[0],cost[1]+24*len(actions)),field_actions=actions,hub=hub_id,map=record['map'],entry=entry,pair=farm['pair'],strip=farm['strip'],length=farm['length'],continuous=farm['continuous'],cost=cost,outbound_cost=(plan['cost'][0]+farm['grass'],plan['cost'][1]+farm['steps']),return_cost=back['cost']))
        if not options:
            reasons.sort(key=lambda r:(0 if 'Cut' in r else 1 if 'Сюжет' in r or 'сюжет' in r or 'Охрана' in r else 2 if 'тренер' in r else 3))
            raise TrainingProblem('no_safe_grind_area',record['label']+': '+(reasons[0] if reasons else 'Нет проверенного пути к траве и обратно в Center'))
        return sorted(options,key=lambda p:p.get('score',p['cost']))
