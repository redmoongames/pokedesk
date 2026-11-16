"""Detached result ownership and immutable, revisioned collection publication."""
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DetachedResult:
    """A producer relinquishes this value; owner must not deep-copy it again."""
    value: object


@dataclass(frozen=True)
class PreparedHistoryExport:
    path: Path
    payload: bytes


def readonly(*_, **__):
    raise TypeError('Published collection data is read-only; copy before editing')


class FrozenDict(dict):
    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = __ior__ = readonly

    def __deepcopy__(self, memo):
        result = {};memo[id(self)] = result
        result.update((deepcopy(k, memo), deepcopy(v, memo)) for k, v in self.items())
        return result


class FrozenList(list):
    __setitem__ = __delitem__ = append = extend = insert = pop = remove = clear = reverse = sort = __iadd__ = __imul__ = readonly

    def __deepcopy__(self, memo):
        result = [];memo[id(self)] = result
        result.extend(deepcopy(value, memo) for value in self)
        return result


def freeze(value, memo=None):
    if isinstance(value, (FrozenDict, FrozenList)):return value
    memo = {} if memo is None else memo
    if id(value) in memo:return memo[id(value)]
    if isinstance(value, dict):
        result = FrozenDict();memo[id(value)] = result
        dict.update(result, ((key, freeze(item, memo)) for key, item in value.items()))
        return result
    if isinstance(value, list):
        result = FrozenList();memo[id(value)] = result
        list.extend(result, (freeze(item, memo) for item in value))
        return result
    if isinstance(value, tuple):return tuple(freeze(item, memo) for item in value)
    return value


class InventoryPublisher:
    """Freeze box details once per raw storage revision, not once per UI tick.

    Party state remains fresh. A generation or trainer/edition change invalidates
    storage even at an identical frame; a missing revision disables reuse.
    """
    def __init__(self):
        self.key = None;self.boxes = None;self.rebuilds = 0

    def publish(self, inventory, generation, daycare=()):
        revision = inventory.get('storage_revision')
        key = (generation, inventory.get('game'), revision)
        if revision is None or key != self.key or self.boxes is None:
            self.boxes = freeze(inventory.get('boxes', []));self.key = key;self.rebuilds += 1
        result = {key:value for key, value in inventory.items() if key not in ('boxes','daycare')}
        result['boxes'] = self.boxes;result['daycare'] = list(daycare)
        return freeze(result)
