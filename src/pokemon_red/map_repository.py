"""Request-local, lazy map snapshots. Missing maps are read only on demand.

The provider belongs to the caller: game/RPC on its owner thread, or an IPC
request in the planning subprocess. These dictionaries never escape into Tk.
"""
class MapRepository(dict):
    def __init__(self,provider,initial=()):
        super().__init__(initial);self.provider=provider
    def __missing__(self,name):
        from .planning_state import planning_grid
        value=self.provider(name)
        if value is None:raise RuntimeError('Нет проверенной карты: '+name)
        value=planning_grid(value);self[name]=value;return value
    def get(self,name,default=None):return self[name]


def lazy_world(state,revision,provider,*,speed=1,initial=()):
    return dict(state=dict(map=state['map'],position=state['position']),
                grids=MapRepository(provider,initial),canonical_navigation=True,
                map_revision=revision,speed=speed)
