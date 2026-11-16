"""Declarative supported navigation; encounter data may exist for more maps."""
import json
from functools import lru_cache
from .engine import ROOT

@lru_cache
def source_spec(root=ROOT):
    from .editions import reference_path
    return json.loads(reference_path(root,'grind_zones.json').read_text())

def zone_spec(root=ROOT):
    from .catalog import catalog
    return catalog(root)['navigation']

def zone_label(key,root=ROOT):return zone_spec(root)['zones'][key]['label']

def __getattr__(name):
    # Compatibility for scripts importing SUPPORTED. Importing the module must
    # not read game resources before the first-run compiler has prepared them.
    if name == 'SUPPORTED':
        return tuple(source_spec()['zones'])
    raise AttributeError(name)
