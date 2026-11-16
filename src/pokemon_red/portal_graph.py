"""Directed portal nodes with exact, save-conditioned intra-map corridors.

One heading-aware sweep connects an arrival node to all exits/Center anchors.
Only reviewed transitions are used; no coarse world edge grants permission.
"""
from collections import defaultdict
from .training import paths_to

class PortalGraph:
    def __init__(self,spec):
        self.nodes=defaultdict(set)
        for edge in spec['links']:
            self.nodes[edge['source']].add(tuple(edge['point']))
            self.nodes[edge['destination']].add(tuple(edge['arrival']))
        for hub in spec.get('hubs',{}).values():
            for key in ('nurse','pc'):
                if key in hub:self.nodes[hub['map']].add(tuple(hub[key]))

    def connect(self,name,start,goal,grid,geometry,cache):
        start=tuple(start);goal=tuple(goal)
        # Arbitrary starts/goals still use the exact same search and cost policy.
        targets=self.nodes[name]|{goal} if start in self.nodes[name] else {goal}
        missing=[p for p in sorted(targets) if cache.get('path',geometry,name,start,p) is None]
        if missing:
            found=paths_to(grid,start,missing)
            for point in missing:
                value=dict(ok=True,value=found[point]) if point in found else dict(ok=False)
                cache.put('path',geometry,[name,start,point],value)
        return cache.get('path',geometry,name,start,goal)
