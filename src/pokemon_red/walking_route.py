"""Retain a local polyline while revalidating it against fresh map conditions."""


def direction(a,b):return ((b[0]>a[0])-(b[0]<a[0]),(b[1]>a[1])-(b[1]<a[1]))


def waypoints(start,path):
    points=[];previous=tuple(start);heading=None
    for point in path:
        point=tuple(point);new=direction(previous,point)
        if heading is not None and new!=heading:points.append(previous)
        previous=point;heading=new
    if path:points.append(tuple(path[-1]))
    return points


class WalkingRoute:
    def __init__(self,start,path,heading=None):
        self.points=[tuple(start),*map(tuple,path)];self.index=0;self.heading=heading
        self.waypoints=waypoints(start,path);self.revision=None

    @property
    def remaining(self):return self.points[self.index+1:]

    def advance(self,position):
        position=tuple(position)
        try:index=self.points.index(position,self.index)
        except ValueError:return False
        if index>self.index:self.heading=direction(self.points[index-1],position)
        self.index=index
        return True

    def validate(self,grid):
        from .path_cache import map_key
        from .training import trainer_zones,walk_neighbors
        revision=map_key(grid)
        if revision==self.revision:return True
        blocked=set(map(tuple,grid.get('obstacles',[])))|trainer_zones(grid)|set(map(tuple,grid.get('script_triggers',[])))
        blocked|={(w['x'],w['y']) for w in grid.get('warps',[])}
        current=self.points[self.index];blocked.discard(current)
        for point in self.remaining:
            if point not in walk_neighbors(grid,current,blocked):return False
            current=point
        self.revision=revision
        return True
