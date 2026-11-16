"""Build the offline Gen III reference from the user's verified FireRed Rev 1 ROM."""
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from pokemon_red.telemetry import decode_text, symbols
from pokemon_red.engine import ROM_SHA1
import hashlib

rom = (ROOT / 'Data/FireRed.gba').read_bytes()
assert hashlib.sha1(rom).hexdigest() == ROM_SHA1
syms = symbols(ROOT)
def raw(address, size):
    return rom[address - 0x08000000:address - 0x08000000 + size]
def u16(address): return struct.unpack('<H', raw(address, 2))[0]
def u32(address): return struct.unpack('<I', raw(address, 4))[0]
def text(address, size=600):
    return decode_text(raw(address, size).split(b'\xff')[0].replace(b'\xfe', b'\x00').replace(b'\xfa', b'\x00').replace(b'\xfb', b'\x00'))
def name(table, index, size): return text(syms[table] + index * size, size)

types = [name('gTypeNames', i, 7) for i in range(18)]
abilities = {i: dict(id=i, name=name('gAbilityNames', i, 13), description=text(u32(syms['gAbilityDescriptionPointers'] + i * 4))) for i in range(78)}
moves = {}
for i in range(1, 355):
    effect, power, typ, accuracy, pp, chance, target, priority, flags, *_ = raw(syms['gBattleMoves'] + i * 12, 12)
    moves[i] = dict(id=i, name=name('gMoveNames', i, 13), type=types[typ], type_id=typ,
        power=power, accuracy=accuracy, pp=pp, effect_chance=chance, effect_id=effect,
        target=target, priority=priority if priority < 128 else priority-256, flags=flags,
        category='Status' if power == 0 else 'Special' if typ >= 10 else 'Physical',
        description=text(u32(syms['gMoveDescriptionPointers'] + (i-1)*4)))
growth = [list(struct.unpack('<101I', raw(syms['gExperienceTables'] + i*404, 404))) for i in range(6)]
species = {}
for i in range(1, 412):
    national = u16(syms['sSpeciesToNationalPokedexNum'] + (i-1)*2)
    if not 1 <= national <= 386 or 252 <= i <= 276: continue
    data = raw(syms['gSpeciesInfo'] + i*28, 28)
    learnset, pointer = [], u32(syms['gLevelUpLearnsets'] + i*4)
    for j in range(100):
        packed = u16(pointer + j*2)
        if packed == 65535: break
        learnset.append(dict(level=packed >> 9, move=packed & 511))
    evolutions = []
    for j in range(5):
        method, param, target = struct.unpack('<HHH', raw(syms['gEvolutionTable'] + i*40 + j*8, 6))
        if method: evolutions.append(dict(method=method, parameter=param, target=target))
    species[i] = dict(id=i, national_id=national, name=name('gSpeciesNames',i,11),
        types=list(dict.fromkeys(types[t] for t in data[6:8])), type_ids=list(dict.fromkeys(data[6:8])),
        base_stats=dict(zip(('hp','attack','defense','speed','special_attack','special_defense'), data[:6])),
        base_xp=data[9], catch_rate=data[8], friendship=data[18], growth=data[19],
        abilities=list(dict.fromkeys(a for a in data[22:24] if a)), learnset=learnset, evolutions=evolutions)
effectiveness=[]
for j in range(112):
    a,b,m=raw(syms['gTypeEffectiveness']+j*3,3)
    if a==255: break
    if a<18: effectiveness.append([a,b,m/10])
items={i: text(syms['gItems']+44*i,14) for i in range(375)}
output=dict(format=1, game='FireRed USA/Europe Rev 1', rom_sha1=ROM_SHA1,
    sources=['https://github.com/pret/pokefirered/tree/ce6406d8c2eaf46d543c8a2606de0c3cb1951982',
             'https://github.com/pret/pokefirered/blob/ce6406d8c2eaf46d543c8a2606de0c3cb1951982/src/battle_script_commands.c'],
    species=species, moves=moves, abilities=abilities, growth=growth, types=types,
    effectiveness=effectiveness, items=items)
(ROOT/'vendor/catalog/firered.json').write_text(json.dumps(output,ensure_ascii=False,separators=(',',':')))
print(f'{len(species)} species, {len(moves)} moves, {len(abilities)} abilities')
