"""Reuse geometry candidates; revalidate live hazards once, not on every frame."""
from .capture_target import hunt_atlas
from .path_cache import map_key,shared_cache
from .walking_route import WalkingRoute
from .navigation import safe_grass_pair


def hunting_spot(root,grid,start):
    atlas=hunt_atlas(root);name=grid['name'];geometry=map_key(grid)+':'+atlas['version_key'];cache=shared_cache(root);key=[name,tuple(start),'autocatch']
    saved=cache.get('farm',geometry,*key)
    if saved and saved['ok']:return saved['value']
    terrain=atlas['maps'].get(name,{}).get('terrain',{})
    choices=[]
    for kind,record in terrain.items():
        # Precomputed entry paths are proposals. Every cell, hazard clearance
        # and both encounter-strip directions are checked against this save.
        for proposal in record['entry_paths']:
            if tuple(proposal['entry'])!=tuple(start):continue
            approach=WalkingRoute(start,proposal['path']);pair=list(map(tuple,proposal['pair']))
            from .movement import safe_segment,straight_path
            line=straight_path(*pair)
            if not approach.validate(grid) or safe_segment(grid,pair[0],line,search=True)!=line or safe_segment(grid,pair[1],line[::-1][1:]+[pair[0]],search=True)!=line[::-1][1:]+[pair[0]]:continue
            choices.append(dict(pair=proposal['pair'],strip=proposal['strip'],path=proposal['path'],length=len(proposal['strip']),continuous=True,grass=sum(bool(grid['tiles'][y][x][3]) for x,y in proposal['path']),steps=len(proposal['path']),terrain=kind))
    if not choices:
        for kind in terrain:
            try:choices.append(dict(safe_grass_pair(grid,start,terrain=kind),terrain=kind))
            except RuntimeError:pass
    if not choices:raise RuntimeError('Нет доступного участка встреч без NPC, активных событий и препятствий')
    best=min(choices,key=lambda a:(a['grass'],a['steps']+12*max(0,9-a['length']),-a['length']))
    cache.put('farm',geometry,key,dict(ok=True,value=best));return best
