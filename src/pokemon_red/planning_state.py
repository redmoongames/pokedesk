"""Semantic navigation snapshots and bounded caches for independent planning stages.

Preview uses anchored NPC envelopes. Execution still reads live positions before
walking; a moving NPC cannot invalidate the entire world's team preview.
"""
from collections import OrderedDict
from .game_layout import save_block,flags_offset,vars_offset,hoenn
from copy import deepcopy
import hashlib

from .run_context import digest, team_fingerprint


def planning_grid(grid):
    from .movement import npc_envelope
    objects=[];occupied=set()
    for original in grid.get('objects',[]):
        occupied.add((original['x'],original['y']))
        obj=dict(original,x=original.get('anchor_x',original['x']),y=original.get('anchor_y',original['y']))
        obj.pop('facing',None);objects.append(obj)
    trainers=[]
    for original in grid.get('trainers',[]):
        # Synthetic/older readers may expose trainers without object templates.
        occupied.add((original['x'],original['y']))
        trainer=dict(original,x=original.get('anchor_x',original['x']),y=original.get('anchor_y',original['y']))
        trainer.pop('facing',None);trainers.append(trainer)
    obstacles=set(map(tuple,grid.get('obstacles',[])))-occupied
    obstacles.update(npc_envelope(dict(objects=objects)))
    obstacles.update((t['x'],t['y']) for t in trainers)
    return dict(grid,objects=objects,trainers=trainers,obstacles=[list(p) for p in sorted(obstacles)])


def maps_key(grids):
    return digest([(name,g.get('obstacles'),g.get('objects'),g.get('trainers'),g.get('script_triggers'),g.get('field_badges')) for name,g in sorted(grids.items())])


def planning_world(world):
    if world.get('canonical_navigation'):return world
    grids={name:planning_grid(g) for name,g in world.get('grids',{}).items()}
    return dict(world,grids=grids,canonical_navigation=True,map_revision=maps_key(grids))


def geometry_key(world):
    world=planning_world(world);state=world.get('state',{})
    return digest([world['map_revision'],state.get('map'),state.get('position')])


class PlanningSnapshotExpired(Exception):
    """A changed snapshot is cancellation, never evidence of a blocked edge."""


def navigation_variables(game):
    cached=getattr(game,'_navigation_variables',None)
    if cached is not None:return cached
    # Read only static event headers, no terrain grids. Ordinary step counters
    # do not affect navigation unless a reviewed coordinate event references one.
    from .telemetry import symbols,maps
    from .optimizer import map_names
    import struct
    s=symbols(game.root);ids={name:key for key,name in maps(game.root).items()};variables=set()
    for name in map_names(game.root):
        group,number=ids[name];header=game.read32(game.read32(s['gMapGroups']+4*group)+4*number)
        events=game.read32(header+4);count=min(64,game.read8(events+2));pointer=game.read32(events+12)
        raw=game.read_bytes(pointer,count*16) if count else b''
        for i in range(count):
            variable=struct.unpack_from('<H',raw,i*16+6)[0]
            if 0x4000<=variable<0x4100:variables.add(variable)
    game._navigation_variables=tuple(sorted(variables));return game._navigation_variables


def read_world_revision(game):
    """Semantic save conditions in two block reads, excluding unrelated counters."""
    from .telemetry import symbols
    sb1=save_block(game,1)
    if not 0x02000000<=sb1<0x02040000-0x3d68:return None
    data=game.read_bytes(sb1+flags_offset(game),0x320)
    variables=b''.join(data[0x120+(v-0x4000)*2:0x122+(v-0x4000)*2] for v in navigation_variables(game))
    return hashlib.sha256(game.read_bytes(sb1+4,2)+data[:0x120]+variables).hexdigest()


class PlanningCache:
    """Each entry has semantic dependencies; no elapsed-time expiry or live core."""
    def __init__(self,limit=1024):
        self.limit=limit;self.geometry=OrderedDict();self.matchups=OrderedDict();self.farms=OrderedDict();self.evidence=None;self.evidence_key=None

    def _get(self,table,key,compute):
        from .training import TrainingProblem
        if key not in table:
            try:entry=(compute(),None)
            except TrainingProblem as error:entry=(None,(error.code,str(error)))
            table[key]=entry
            while len(table)>self.limit:table.popitem(last=False)
        table.move_to_end(key);value,error=table[key]
        if error:raise TrainingProblem(*error)
        # Consumers annotate plans and forecasts; cached inputs stay immutable.
        return deepcopy(value)

    def route_geometry(self,nav,route,root,compute):
        from .field_tools import available
        inventory=nav.tool_inventory or {}
        cut=available(inventory.get('party',[]),inventory.get('field_badges',[]),inventory.get('game','firered'))['cut']
        key=(str(root),geometry_key(nav.planning_world),bool(nav.cut_enabled),bool(cut['unlocked'] and cut['providers']),route)
        return self._get(self.geometry,key,compute)

    def coverage_rows(self,mon,route,root,trainee,compute):
        return self._get(self.matchups,(str(root),team_fingerprint([mon]),route,trainee),compute)

    def route_farms(self,nav,route,root,compute):
        # Clinic↔grass round trips depend on map conditions/capabilities, not
        # the player's current tile. Access to the clinic is checked separately.
        world=planning_world(nav.planning_world)
        return self._get(self.farms,(str(root),world['map_revision'],bool(nav.cut_enabled),route),compute)
