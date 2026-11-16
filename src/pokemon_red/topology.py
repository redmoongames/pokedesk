"""Cheap directed map corridors; terrain and story permissions are never assumed.

A coarse path is only a candidate. Failed cell validation widens the corridor,
including long detours and exits/re-entry into disconnected parts of one map.
"""
from collections import deque

class WorldTopology:
    def __init__(self,links):
        self.forward={};self.reverse={};self.names=set()
        for edge in links:
            a,b=edge['source'],edge['destination'];self.names.update((a,b))
            self.forward.setdefault(a,set()).add(b);self.reverse.setdefault(b,set()).add(a)
    @staticmethod
    def distances(edges,start):
        found={start:0};pending=deque([start])
        while pending:
            a=pending.popleft()
            for b in edges.get(a,()):
                if b not in found:found[b]=found[a]+1;pending.append(b)
        return found
    def corridors(self,start,goal):
        outward=self.distances(self.forward,start);back=self.distances(self.reverse,goal)
        if goal not in outward:
            yield {start,goal};return
        shortest=outward[goal];previous=None
        for slack in (0,2,6,len(self.names)*2):
            names={n for n in outward if n in back and outward[n]+back[n]<=shortest+slack}
            if names!=previous:yield names;previous=names
