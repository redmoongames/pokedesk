"""Prepare local game content from a verified, user-supplied cartridge.

The distributable contains identifiers, factual navigation metadata and authored
articles, not game graphics, ROM tables or prepared saves. This explicit setup
compiler runs before an installation is frozen; runtime readers stay read-only.
"""
from collections import deque
from pathlib import Path
import hashlib
import json
import re
import shutil
import struct
import zlib

from .editions import FIRERED, validate_rom
from .telemetry import decode_text, parse_symbols

SEED = Path(__file__).with_name('release_data')
RESOURCE_SCHEMA = 1
STATS = ('hp', 'attack', 'defense', 'speed', 'special_attack', 'special_defense')
FIELDS = [
    dict(type='land_mons', encounter_rates=[20,20,10,10,10,10,5,5,4,4,1,1]),
    dict(type='water_mons', encounter_rates=[60,30,5,4,1]),
    dict(type='rock_smash_mons', encounter_rates=[60,30,5,4,1]),
    dict(type='fishing_mons', encounter_rates=[70,30,60,20,20,40,40,15,4,1],
         groups=dict(old_rod=[0,1], good_rod=[2,3,4], super_rod=[5,6,7,8,9])),
]


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, separators=(',', ':')) + '\n')


class Cartridge:
    def __init__(self, payload):
        validate_rom(payload, 'firered')
        self.data = payload
        self.symbols = parse_symbols((SEED / FIRERED.symbols).read_text())

    def raw(self, address, size):
        offset = address - 0x08000000
        if size < 0 or offset < 0 or offset + size > len(self.data):
            raise ValueError('Cartridge table points outside the verified ROM')
        return self.data[offset:offset + size]

    def unpack(self, fmt, address):
        return struct.unpack(fmt, self.raw(address, struct.calcsize(fmt)))

    def u16(self, address):
        return self.unpack('<H', address)[0]

    def u32(self, address):
        return self.unpack('<I', address)[0]

    def text(self, address, size=600):
        raw = self.raw(address, min(size, 0x08000000 + len(self.data) - address))
        return decode_text(raw.split(b'\xff')[0].replace(b'\xfe', b'\x00')
                           .replace(b'\xfa', b'\x00').replace(b'\xfb', b'\x00'))

    def name(self, table, index, size):
        return self.text(self.symbols[table] + index * size, size)

    def catalog(self):
        sy = self.symbols
        types = [self.name('gTypeNames', i, 7) for i in range(18)]
        abilities = {i: dict(id=i, name=self.name('gAbilityNames', i, 13),
                     description=self.text(self.u32(sy['gAbilityDescriptionPointers'] + i*4)))
                     for i in range(78)}
        moves = {}
        for i in range(1, 355):
            effect, power, typ, accuracy, pp, chance, target, priority, flags, *_ = self.raw(sy['gBattleMoves'] + i*12, 12)
            moves[i] = dict(id=i, name=self.name('gMoveNames', i, 13), type=types[typ],
                type_id=typ, power=power, accuracy=accuracy, pp=pp, effect_chance=chance,
                effect_id=effect, target=target, priority=priority if priority < 128 else priority-256,
                flags=flags, category='Status' if power == 0 else 'Special' if typ >= 10 else 'Physical',
                description=self.text(self.u32(sy['gMoveDescriptionPointers'] + (i-1)*4)))
        growth = [list(self.unpack('<101I', sy['gExperienceTables'] + i*404)) for i in range(6)]
        species = {}
        for i in range(1, 412):
            national = self.u16(sy['sSpeciesToNationalPokedexNum'] + (i-1)*2)
            if not 1 <= national <= 386 or 252 <= i <= 276:
                continue
            data = self.raw(sy['gSpeciesInfo'] + i*28, 28)
            learnset = []
            pointer = self.u32(sy['gLevelUpLearnsets'] + i*4)
            for j in range(100):
                packed = self.u16(pointer + j*2)
                if packed == 65535:
                    break
                learnset.append(dict(level=packed >> 9, move=packed & 511))
            evolutions = []
            for j in range(5):
                method, param, target = self.unpack('<HHH', sy['gEvolutionTable'] + i*40 + j*8)
                if method:
                    evolutions.append(dict(method=method, parameter=param, target=target))
            species[i] = dict(id=i, national_id=national, name=self.name('gSpeciesNames', i, 11),
                types=list(dict.fromkeys(types[t] for t in data[6:8])), type_ids=list(dict.fromkeys(data[6:8])),
                base_stats=dict(zip(STATS, data[:6])), base_xp=data[9], catch_rate=data[8],
                friendship=data[18], growth=data[19], abilities=list(dict.fromkeys(a for a in data[22:24] if a)),
                learnset=learnset, evolutions=evolutions)
        effectiveness = []
        for j in range(112):
            a, b, multiplier = self.raw(sy['gTypeEffectiveness'] + j*3, 3)
            if a == 255:
                break
            if a < 18:
                effectiveness.append([a, b, multiplier/10])
        return dict(format=1, game=FIRERED.label, rom_sha1=FIRERED.sha1,
            sources=['User-supplied FireRed Rev 1 cartridge',
                     'https://github.com/pret/pokefirered'], species=species,
            moves=moves, abilities=abilities, growth=growth, types=types,
            effectiveness=effectiveness, items={i: self.text(sy['gItems'] + 44*i, 14) for i in range(375)})

    def encounters(self, groups, metadata):
        names = {(g, n): name for g, key in enumerate(groups['group_order'])
                 for n, name in enumerate(groups[key])}
        entries = []
        occurrences = {}
        address = self.symbols['gWildMonHeaders']
        for i in range(1024):
            group, number = self.raw(address + 20*i, 2)
            if group == 255:
                break
            name = names[(group, number)]
            occurrences[name] = occurrences.get(name, 0) + 1
            # The cartridge contains eight extra Mystery Gift Altering Cave
            # tables. They are not ordinary encounters available to a player.
            # Treating every header as an independently reachable population
            # would offer Mareep/Aipom/etc. as catchable in a normal save.
            if name == 'SixIsland_AlteringCave' and occurrences[name] > 1:
                continue
            if occurrences[name] > 1:
                raise ValueError('Ambiguous ordinary encounter table: ' + name)
            row = dict(map=metadata['maps'][name]['id'], base_label='g' + name + '_FireRed')
            for j, field in enumerate(FIELDS):
                pointer = self.u32(address + 20*i + 4 + 4*j)
                if not pointer:
                    continue
                rate = self.raw(pointer, 1)[0]
                table = self.u32(pointer + 4)
                mons = []
                for slot in range(len(field['encounter_rates'])):
                    lo, hi, species = self.unpack('<BBH', table + 4*slot)
                    mons.append(dict(min_level=lo, max_level=hi, species=f'SPECIES_{species}'))
                row[field['type']] = dict(encounter_rate=rate, mons=mons)
            entries.append(row)
        else:
            raise ValueError('Unterminated wild encounter table')
        return dict(wild_encounter_groups=[dict(for_maps=True, fields=FIELDS, encounters=entries)])


def populations(table, weights):
    result = {}
    for mon, weight in zip(table['mons'], weights):
        sid = int(mon['species'].removeprefix('SPECIES_'))
        row = result.setdefault(sid, dict(species_id=sid, probability=0,
                       min_level=100, max_level=0, levels={}))
        row['probability'] += weight
        row['min_level'] = min(row['min_level'], mon['min_level'])
        row['max_level'] = max(row['max_level'], mon['max_level'])
        for level in range(mon['min_level'], mon['max_level'] + 1):
            key = str(level)
            row['levels'][key] = row['levels'].get(key, 0) + weight/(mon['max_level'] - mon['min_level'] + 1)
    return sorted(result.values(), key=lambda r: (-r['probability'], r['species_id']))


def build_tables(root, cartridge):
    reference = root / 'vendor/reference'
    reference.mkdir(parents=True)
    for name in ('grind_zones.json', 'heal_locations.json', 'map_groups.json',
                 'dex_availability.json', 'world_topology.json', 'region_map.json', FIRERED.symbols):
        shutil.copyfile(SEED / name, reference / name)
    (reference / 'species.h').write_text('\n'.join(f'#define SPECIES_{i} {i}' for i in range(412)) + '\n')
    effects = json.loads((SEED / 'effect_names.json').read_text())
    (reference / 'battle_move_effects.h').write_text('\n'.join(f'#define {name} {key}' for key, name in effects.items()) + '\n')
    data = cartridge.catalog()
    write_json(root / 'vendor/catalog/firered.json', data)
    shutil.copyfile(SEED / 'move_articles.json', root / 'vendor/catalog/moves_ru.json')
    shutil.copyfile(SEED / 'item_articles.json', root / 'vendor/catalog/item-reference-ru.json')
    metadata = json.loads((SEED / 'location_reference.json').read_text())
    groups = json.loads((SEED / 'map_groups.json').read_text())
    wild = cartridge.encounters(groups, metadata)
    write_json(reference / 'wild_encounters.json', wild)
    by_symbol = {v['id']: k for k, v in metadata['maps'].items()}
    routes = {}
    for row in wild['wild_encounter_groups'][0]['encounters']:
        name = by_symbol[row['map']]
        for field in FIELDS:
            key = field['type']
            if key not in row:
                continue
            table = row[key]
            for method, slots in (field.get('groups') or {key: range(len(table['mons']))}).items():
                pop = populations(dict(mons=[table['mons'][i] for i in slots]),
                                  [field['encounter_rates'][i] for i in slots])
                metadata['maps'][name]['encounters'].append(dict(method=method,
                    encounter_rate=table['encounter_rate'], population=pop))
            if key == 'land_mons' and (re.match(r'^Route\d', name) or name in
                    ('ViridianForest', 'MtMoon_1F', 'MtMoon_B1F', 'MtMoon_B2F', 'DiglettsCave_B1F')):
                mons = [dict(species_id=int(m['species'].removeprefix('SPECIES_')),
                        min_level=m['min_level'], max_level=m['max_level'], weight=w)
                        for m, w in zip(table['mons'], field['encounter_rates'])]
                routes[name] = dict(map=name, game='FireRed', table=row['base_label'],
                    terrain='cave' if name.startswith(('MtMoon_', 'DiglettsCave_')) else 'grass',
                    encounter_rate=table['encounter_rate'], mons=mons,
                    population=populations(table, field['encounter_rates']),
                    grass_scope='One ordinary land table per exact map; floors remain separate')
    # Text and party contents are local ROM data, not part of the distributed seed.
    for record in metadata['maps'].values():
        for obj in record['objects']:
            for trainer in obj.get('trainers', []):
                number = trainer.get('id')
                if number is None:
                    trainer.update(name='', party=[])
                    continue
                pointer = cartridge.symbols['gTrainers'] + number*40
                raw = cartridge.raw(pointer, 40)
                trainer['name'] = cartridge.text(pointer + 4, 12)
                party = cartridge.u32(pointer + 36)
                size = 16 if raw[0] & 1 else 8
                trainer['party'] = [dict(level=cartridge.u16(party + size*i + 2),
                    species_id=cartridge.u16(party + size*i + 4)) for i in range(raw[32])]
    write_json(reference / 'location_reference.json', metadata)
    write_json(reference / 'grind_routes.json', dict(source='User-supplied cartridge',
        source_sha256=hashlib.sha256(cartridge.data).hexdigest(),
        mechanics='Gen III ordinary encounter slots',
        probability_note='Conditional on an encounter, not a per-step chance', routes=routes))
    records = []
    for i, name in data['items'].items():
        raw = cartridge.raw(cartridge.symbols['gItems'] + 44*i, 44)
        records.append(dict(id=i, name=name, icon=f'icons/{i}.png', importance=raw[24],
                            pocket_id=raw[26], holdable=not raw[24] and bool(i)))
    write_json(root / 'vendor/catalog/item-catalog.json', dict(source='User-supplied cartridge',
               rom_sha1=FIRERED.sha1, icons='Local ROM extraction', items=records))
    return data


def decompress_lz77(cartridge, address, *, maximum=32768):
    header = cartridge.raw(address, 4)
    size = int.from_bytes(header[1:], 'little')
    if header[0] != 0x10 or not 0 < size <= maximum:
        raise ValueError('Invalid cartridge sprite header')
    result = bytearray()
    address += 4
    while len(result) < size:
        flags = cartridge.raw(address, 1)[0]
        address += 1
        for bit in range(7, -1, -1):
            if len(result) >= size:
                break
            if flags & (1 << bit):
                a, b = cartridge.raw(address, 2)
                address += 2
                length, distance = (a >> 4) + 3, ((a & 15) << 8 | b) + 1
                if distance > len(result):
                    raise ValueError('Invalid sprite back-reference')
                for _ in range(length):
                    result.append(result[-distance])
            else:
                result.extend(cartridge.raw(address, 1))
                address += 1
    return bytes(result[:size])


def sprite_png(tiles, palette, width, height, *, gray=False):
    colors = [((v & 31)*255//31, ((v >> 5) & 31)*255//31, ((v >> 10) & 31)*255//31)
              for v in struct.unpack('<16H', palette[:32])]
    scan = bytearray()
    for y in range(height):
        scan.append(0)
        for x in range(width):
            packed = tiles[(y//8*(width//8) + x//8)*32 + y%8*4 + x%8//2]
            index = packed >> (4*(x%2)) & 15
            r, g, b = colors[index]
            if gray:
                r = g = b = (299*r + 587*g + 114*b + 500)//1000
            scan.extend((r, g, b, 255 if index else 0))
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(bytes(scan), 6)) + chunk(b'IEND', b''))


def build_sprites(root, cartridge, data):
    sy = cartridge.symbols
    for number, mon in data['species'].items():
        tiles = decompress_lz77(cartridge, cartridge.u32(sy['gMonFrontPicTable'] + 8*number))
        for shiny, table in ((False, 'gMonPaletteTable'), (True, 'gMonShinyPaletteTable')):
            palette = decompress_lz77(cartridge, cartridge.u32(sy[table] + 8*number))
            for gray in (False, True):
                folder = root / 'assets/pokemon'
                if shiny:
                    folder /= 'shiny'
                if gray:
                    folder /= 'gray'
                folder.mkdir(parents=True, exist_ok=True)
                (folder / f"{mon['national_id']}.png").write_bytes(sprite_png(tiles, palette, 64, 64, gray=gray))
    for i in range(375):
        pointer = sy['sItemIconTable'] + i*8
        tiles = decompress_lz77(cartridge, cartridge.u32(pointer))
        palette = decompress_lz77(cartridge, cartridge.u32(pointer + 4))
        folder = root / 'assets/items'
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f'{i}.png').write_bytes(sprite_png(tiles, palette, 24, 24))


def build_entity_names(root, data):
    """Names are cartridge content too; prepare them locally, not in the DMG."""
    from .natures import NATURE_NAMES
    groups = json.loads((root / 'vendor/reference/map_groups.json').read_text())
    entities = {}
    for kind in ('species', 'moves', 'abilities'):
        entities[kind] = {}
        for key, record in data[kind].items():
            name = record['name'].title()
            entry = dict(en=name, ru=name, aliases=[record['name']])
            if kind == 'species':
                entry['national_id'] = record['national_id']
            entities[kind][str(key)] = entry
    entities['items'] = {str(key): dict(en=name.title(), ru=name.title(), aliases=[name])
                         for key, name in data['items'].items()}
    entities['locations'] = {}
    for group in groups['group_order']:
        for name in groups[group]:
            display = re.sub(r'(?<=[a-z])(?=[A-Z0-9])', ' ', name).replace('_', ' · ')
            entities['locations'][name] = dict(en=display, ru=display, aliases=[name])
    entities['natures'] = {str(i): dict(en=name.title(), ru=name.title(), aliases=[name])
                           for i, name in enumerate(NATURE_NAMES)}
    write_json(root / 'src/pokemon_red/locales/entities.json', entities)


def encounter_areas(grid, behavior):
    from .training import walk_neighbors
    cells = {(x, y) for y, row in enumerate(grid['tiles']) for x, tile in enumerate(row)
             if not tile[0] and tile[1] == behavior and tile[3]}
    result = []
    while cells:
        start = min(cells)
        pending = deque([start])
        cells.remove(start)
        component = {start}
        while pending:
            point = pending.popleft()
            for other in walk_neighbors(grid, point, set()):
                if other in cells and point in walk_neighbors(grid, other, set()):
                    cells.remove(other)
                    component.add(other)
                    pending.append(other)
        strips = []
        for dx, dy in ((1, 0), (0, 1)):
            for point in sorted(component):
                if (point[0] - dx, point[1] - dy) in component:
                    continue
                line, q = [], point
                while q in component:
                    if line and (q not in walk_neighbors(grid, line[-1], set()) or
                                 line[-1] not in walk_neighbors(grid, q, set())):
                        break
                    line.append(q)
                    q = (q[0] + dx, q[1] + dy)
                if len(line) >= 2:
                    strips.append(dict(start=line[0], end=line[min(len(line), 17)-1], length=min(len(line), 17)))
        result.append(dict(cells=sorted(component), strips=sorted(strips, key=lambda s: (-s['length'], s['start']))[:64]))
    return sorted(result, key=lambda a: (-len(a['cells']), a['cells'][0]))


def build_hunt_atlas(root):
    from .engine import Game
    from .catalog import catalog
    from .telemetry import maps, read_map
    from .zones import zone_spec
    from .portal_graph import PortalGraph
    from .navigation import safe_grass_pair
    from .walking_route import waypoints
    data = catalog(root)
    wild = json.loads((root / 'vendor/reference/wild_encounters.json').read_text())
    metadata = json.loads((root / 'vendor/reference/location_reference.json').read_text())
    names = {v['id']: k for k, v in metadata['maps'].items()}
    atlas = dict(version=1, rom_sha1=FIRERED.sha1, contract='Geometry candidates; live validation required',
                 entries={}, maps={}, species={})
    for row in wild['wild_encounter_groups'][0]['encounters']:
        for field in FIELDS:
            key = field['type']
            if key not in row:
                continue
            for method, slots in (field.get('groups') or {key: range(len(row[key]['mons']))}).items():
                pop = populations(dict(mons=[row[key]['mons'][i] for i in slots]),
                                  [field['encounter_rates'][i] for i in slots])
                for mon in pop:
                    atlas['entries'].setdefault(str(mon['species_id']), []).append(dict(map=names[row['map']],
                        method=method, encounter_rate=row[key]['encounter_rate'],
                        levels=mon['levels'], probability=mon['probability']))
    portals = PortalGraph(zone_spec(root))
    with Game(root, resume=False) as game:
        from .telemetry import symbols
        table = symbols(game.root)['gSpeciesInfo']
        atlas['species'] = {key: dict(gender_ratio=game.read8(table + 28*int(key) + 16),
                           national_id=sp['national_id']) for key, sp in data['species'].items()}
        for name in maps(root).values():
            grid = read_map(game, name)
            if not grid:
                continue
            plain = dict(grid, objects=[], trainers=[], obstacles=[], script_triggers=[],
                         portal_points=[], warps=[], signs=[], sign_approaches=[])
            terrain = {}
            for label, behavior in (('grass', 2), ('cave', 8)):
                areas = encounter_areas(plain, behavior)
                if not areas:
                    continue
                paths = []
                for entry in sorted(portals.nodes.get(name, ())):
                    try:
                        farm = safe_grass_pair(plain, entry, terrain=label)
                        paths.append(dict(entry=entry, path=farm['path'], waypoints=waypoints(entry, farm['path']),
                                          pair=farm['pair'], strip=farm['strip']))
                    except RuntimeError:
                        pass
                terrain[label] = dict(areas=areas, entry_paths=paths)
            atlas['maps'][name] = dict(width=grid['width'], height=grid['height'],
                                      geometry=grid['static_geometry'], terrain=terrain)
    atlas['version_key'] = hashlib.sha256(json.dumps(wild, sort_keys=True).encode()).hexdigest()[:24]
    write_json(root / 'vendor/reference/hunt_atlas.json', atlas)


def prepare_resources(root, payload, progress=lambda stage: None):
    """Only called for a disposable setup root; never modifies a live profile."""
    root = Path(root)
    cartridge = Cartridge(payload)
    progress('setup.tables')
    data = build_tables(root, cartridge)
    build_entity_names(root, data)
    from .reference_pack import build_reference
    (root / 'vendor/catalog/packs').mkdir(parents=True, exist_ok=True)
    build_reference(root, 'firered')
    progress('setup.sprites')
    build_sprites(root, cartridge, data)
    progress('setup.routes')
    build_hunt_atlas(root)
    return dict(schema=RESOURCE_SCHEMA, rom_sha1=FIRERED.sha1,
                species=len(data['species']), moves=len(data['moves']))
