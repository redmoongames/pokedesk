"""Conservative straight corridors and frame-driven movement ownership.

No OS input, timers or RAM writes. Coordinates are read from live ObjectEvents;
input is released as soon as the destination tile is entered, before settling.
"""
from .engine import BUTTONS

MAX_SEGMENT=16
RUN_MIN_TILES=4

def movement_mode(state,tiles):
    """Run only on a proved straight corridor; precision steps always walk."""
    return 'run' if tiles>=RUN_MIN_TILES and state.get('can_run') else 'walk'

def safe_step(grid,start,goal):
    """One ordinary step or directed ledge; portals/scripts have other owners."""
    from .training import walk_neighbors,trainer_zones
    blocked=set(map(tuple,grid.get('obstacles',[])))|trainer_zones(grid)|set(map(tuple,grid.get('script_triggers',[])))
    blocked|={(w['x'],w['y']) for w in grid.get('warps',[])}
    return tuple(goal) in walk_neighbors(grid,tuple(start),blocked)


def near(points,radius=1):
    return {(x+dx,y+dy) for x,y in points for dx in range(-radius,radius+1) for dy in range(-radius,radius+1) if abs(dx)+abs(dy)<=radius}

def npc_envelope(grid):
    points=set()
    for obj in grid.get('objects',[]):
        movement=obj.get('movement',0)
        rx,ry=(obj.get('range_x',0),obj.get('range_y',0)) if movement in (2,3,4,5,6,0x50) or 0x19<=movement<=0x3e else (0,0)
        if 0x19<=movement<=0x34:rx=max(1,rx);ry=max(1,ry)
        if movement in (0x35,0x36,0x37,0x38,0x3b,0x3c,0x3d,0x3e):rx=max(2,rx);ry=max(2,ry)
        ox=obj.get('anchor_x',obj['x']) if rx or ry else obj['x'];oy=obj.get('anchor_y',obj['y']) if rx or ry else obj['y']
        for x in range(ox-rx,ox+rx+1):
            for y in range(oy-ry,oy+ry+1):points.add((x,y))
    return points

def corridor_hazards(grid):
    from .training import trainer_zones
    # A one-tile clearance keeps continuous movement away from interaction,
    # border transitions, signs, NPC wander envelopes and script activation.
    objects=npc_envelope(grid)|set(map(tuple,grid.get('obstacles',[])))
    events=set(map(tuple,grid.get('script_triggers',[])))|set(map(tuple,grid.get('portal_points',[])))
    events|={(w['x'],w['y']) for w in grid.get('warps',[])}
    events|=set(map(tuple,grid.get('signs',[])))|set(map(tuple,grid.get('sign_approaches',[])))
    return near(objects|events)|trainer_zones(grid)

def straight_path(start,goal):
    x,y=start;gx,gy=goal
    if (x==gx)==(y==gy):return []
    dx=(gx>x)-(gx<x);dy=(gy>y)-(gy<y);count=abs(gx-x)+abs(gy-y)
    return [(x+dx*i,y+dy*i) for i in range(1,count+1)]

def safe_segment(grid,start,path,*,search=False,allow_encounters=False,limit=MAX_SEGMENT):
    """Longest prefix, at least two steps; leave the turn itself to a pulse."""
    from .training import walk_neighbors
    start=tuple(start);path=[tuple(p) for p in path]
    if not path:return []
    if not(0<=start[0]<grid['width'] and 0<=start[1]<grid['height']):return []
    allowed=(0,2,8) if search else (0,8) if allow_encounters else (0,)
    def encounter_ok(tile):return not tile[3] or search or allow_encounters and tile[1]==8
    tile=grid['tiles'][start[1]][start[0]]
    if tile[0] or tile[1] not in allowed or not encounter_ok(tile):return []
    dx,dy=path[0][0]-start[0],path[0][1]-start[1]
    if abs(dx)+abs(dy)!=1:return []
    hazards=corridor_hazards(grid);blocked=set(map(tuple,grid.get('obstacles',[])))
    result=[];previous=start;elevation=grid['tiles'][start[1]][start[0]][2]
    # Standing next to an NPC/portal must use the existing exact single step.
    if start in hazards:return []
    for i,p in enumerate(path[:limit]):
        x,y=p
        if (x-previous[0],y-previous[1])!=(dx,dy):break
        if not(1<=x<grid['width']-1 and 1<=y<grid['height']-1) or p in hazards:break
        collision,behavior,height,encounter=grid['tiles'][y][x]
        if collision or height!=elevation or behavior not in allowed:break
        if not encounter_ok(grid['tiles'][y][x]):break
        if p not in walk_neighbors(grid,previous,blocked) or previous not in walk_neighbors(grid,p,blocked):break
        # A corner is approached with a single-cell pulse, even on plain floor.
        if i+1<len(path) and (path[i+1][0]-x,path[i+1][1]-y)!=(dx,dy):break
        result.append(p);previous=p
    return result if len(result)>=2 else []

class WalkSegment:
    def __init__(self,name,start,goal,frame,*,mode='walk',precision=False):
        self.name=name;self.start=tuple(start);self.goal=tuple(goal);self.path=straight_path(self.start,self.goal)
        self.dx=(goal[0]>start[0])-(goal[0]<start[0]);self.dy=(goal[1]>start[1])-(goal[1]<start[1])
        self.button={(1,0):'RIGHT',(-1,0):'LEFT',(0,1):'DOWN',(0,-1):'UP'}[self.dx,self.dy]
        self.mode=mode;self.precision=precision
        self.frame=frame;self.last_frame=frame;self.progress=0;self.arriving=False;self.closed_since=None
    def next(self,state):
        frame=state['frame'];position=state.get('position');reason=None
        if state.get('in_battle') or state.get('battle_pending'):reason='battle'
        elif not state.get('ready'):reason='interrupted'
        elif self.mode=='bike' and not (state.get('on_bike') and state.get('bike_allowed')):reason='unsupported_transport'
        elif self.mode!='bike' and state.get('on_foot') is False:reason='unsupported_transport'
        elif not state.get('open'):
            # Field control locks one frame before a wild-battle task exists.
            # Release input immediately, allow only a bounded identification gap.
            if self.closed_since is None:self.closed_since=frame
            if frame-self.closed_since<12:return 0,None
            reason='interrupted'
        elif state.get('map')!=self.name:reason='map_changed'
        elif position is None:reason='invalid_position'
        else:
            self.closed_since=None
            p=tuple(position);along=(p[0]-self.start[0])*self.dx+(p[1]-self.start[1])*self.dy
            if p!=(self.start[0]+along*self.dx,self.start[1]+along*self.dy) or not self.progress<=along<=len(self.path):reason='off_corridor'
            else:
                if along>self.progress:self.progress=along;self.last_frame=frame
                if p==self.goal:self.arriving=True
                remaining=self.path[self.progress:]
                risk=set(remaining) if self.precision else near(remaining+[p])
                if any(tuple(a) in risk for a in state.get('actors',[])):reason='obstacle'
                elif self.arriving and not state.get('moving'):reason='reached'
                elif frame-self.last_frame>90 or frame-self.frame>len(self.path)*40+120:reason='stalled'
        if reason:return 0,dict(reason=reason,start_frame=self.frame,end_frame=frame,position=position,goal=list(self.goal),tiles=self.progress,mode=self.mode)
        # Running permission and field ownership are sampled every game frame.
        # Never carry B into a menu, script, battle or a different avatar mode.
        if self.mode=='run' and not state.get('can_run'):self.mode='walk'
        mask=BUTTONS[self.button] | (BUTTONS['B'] if self.mode=='run' else 0)
        return (0 if self.arriving else mask),None
