"""Explicit reference-pack compiler and read-only runtime loader.

Reference reads never open a profile journal or build/update a pack. Building is
an installation operation, separate from gameplay and safe for concurrent readers
because publication uses a durable atomic replacement.
"""
from functools import lru_cache
from pathlib import Path
import hashlib
import json

from .paths import installation_root, resource

SCHEMA = 1


def pack_path(root, game=None):
    from .editions import edition
    game = game or edition(root).id
    from .editions import edition_id
    return resource(root, f'vendor/catalog/packs/{edition_id(game)}.json')


def source_inputs(root, game):
    from .editions import EDITIONS, reference_for
    base = installation_root(root);spec = EDITIONS[game]
    inputs = [resource(base, f'vendor/catalog/{game}.json'),
              reference_for(base, spec, 'grind_routes.json'),
              reference_for(base, spec, 'grind_zones.json'),
              resource(base, 'vendor/catalog/moves_ru.json'),
              resource(base, 'vendor/reference/battle_move_effects.h')]
    inputs.extend(Path(__file__).with_name(name) for name in
                  ('reference_pack.py', 'editions.py', 'move_reference.py', 'rules.py', 'statuses.py', 'route_profiles.py'))
    return inputs


def source_version(root, game):
    digest = hashlib.sha256()
    for path in source_inputs(root, game):
        digest.update(path.name.encode() + b'\0' + path.read_bytes() + b'\0')
    return digest.hexdigest()


def compile_reference(root, game):
    from .editions import EDITIONS, reference_for
    from .rules import enrich_moves
    from .move_reference import enrich_reference
    from .route_profiles import enrich_routes
    root = installation_root(root);spec = EDITIONS[game]
    raw = json.loads(resource(root, f'vendor/catalog/{game}.json').read_bytes())
    moves = json.loads(resource(root, 'vendor/catalog/moves_ru.json').read_bytes())
    data = enrich_reference(enrich_moves(raw, root, game=spec), moves)
    data['navigation'] = json.loads(reference_for(root, spec, 'grind_zones.json').read_bytes())
    data['routes'] = enrich_routes(data, json.loads(reference_for(root, spec, 'grind_routes.json').read_bytes())['routes'])
    return data


def build_reference(root, game, *, check=False):
    """Only the explicit build command writes to the installation."""
    from .persistence import atomic_bytes
    version = source_version(root, game);path = pack_path(root, game)
    if check:
        record = json.loads(path.read_bytes());_validate(record, game)
        if record['source_version'] != version:raise ValueError('Reference pack is out of date: ' + game)
        return path
    data = compile_reference(root, game)
    # Detect changing source inputs during preparation instead of publishing a
    # pack compiled from a mixture of revisions.
    if source_version(root, game) != version:raise ValueError('Reference inputs changed during build')
    payload = json.dumps(dict(schema=SCHEMA, game=game, source_version=version, data=data),
                         ensure_ascii=False, separators=(',', ':')).encode()
    _validate(json.loads(payload), game)
    atomic_bytes(path, payload, durable=True);_read.cache_clear()
    return path


def _validate(record, game):
    if not isinstance(record, dict) or record.get('schema') != SCHEMA or record.get('game') != game:
        raise ValueError('Incompatible reference pack: ' + game)
    if not isinstance(record.get('source_version'), str) or len(record['source_version']) != 64:
        raise ValueError('Invalid reference version')
    data = record.get('data')
    if not isinstance(data, dict) or any(not isinstance(data.get(key), dict) for key in ('species', 'moves', 'abilities', 'routes')):
        raise ValueError('Incomplete reference pack: ' + game)


@lru_cache(maxsize=16)
def _read(path, game):
    record = json.loads(path.read_bytes());_validate(record, game)
    from .runtime_data import freeze
    return freeze(record['data'])


def load_reference(root, *, game=None):
    from .editions import edition, EDITIONS
    game = game or edition(root).id
    path = pack_path(root, game).resolve()
    try:return _read(path, game)
    except FileNotFoundError as error:
        from .i18n import t
        raise FileNotFoundError(t('reference.pack_missing', game=EDITIONS[game].name)) from error
