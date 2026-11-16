"""Read shiny identity from the enemy party, never transient battler positions.

At battle startup gBattlerPositions/gBattleMons can still describe an earlier
battle. A party record owns personality, trainer ID and checksum together.
"""
from .game_layout import main_flags
import struct

from .models import ORDERS
from .telemetry import symbols

TRAINER_OR_LINK = (1 << 3) | (1 << 1)
PARTY_SIZE = 6
PARTY_MON_BYTES = 100


def shiny_opponents(state):
    battle = state.get('battle') or {}
    if not state.get('in_battle') or battle.get('flags', 0) & TRAINER_OR_LINK:
        return []
    owned = {mon['uid'] for mon in state.get('party', []) if mon.get('uid')}
    return [mon for mon in battle.get('enemy_party', [])
            if mon.get('checksum_valid') and mon.get('shiny')
            and mon.get('uid') not in owned and mon.get('species_id')
            and not mon.get('is_egg')]


def read_shiny_opponent(game):
    """Small per-frame guard; decrypt records only on a possible shiny hit.

    Never writes memory. Reject invalid/egg/owned records, trainer/link battles
    and stale fainted enemies before allowing the UI to latch a pause.
    """
    addresses = symbols(game.root)
    in_battle = main_flags(game,addresses) & 2
    if not in_battle or game.read32(addresses['gBattleTypeFlags']) & TRAINER_OR_LINK:
        return None
    party = game.read_bytes(addresses['gEnemyParty'], PARTY_SIZE * PARTY_MON_BYTES)
    for index in range(PARTY_SIZE):
        data = party[index * PARTY_MON_BYTES:(index + 1) * PARTY_MON_BYTES]
        personality, trainer_id = struct.unpack_from('<II', data)
        shiny_value = ((personality >> 16) ^ (personality & 65535)
                       ^ (trainer_id >> 16) ^ (trainer_id & 65535))
        if not data[19] & 2 or data[19] & 4 or shiny_value >= 8:
            continue
        key = personality ^ trainer_id
        plain = b''.join(struct.pack('<I', value ^ key)
                         for value in struct.unpack_from('<12I', data, 32))
        checksum = sum(struct.unpack('<24H', plain)) & 65535
        if checksum != struct.unpack_from('<H', data, 28)[0]:
            continue
        growth_offset = ORDERS[personality % 24].index('G') * 12
        number = struct.unpack_from('<H', plain, growth_offset)[0]
        # The encrypted egg flag also belongs to the Misc substructure.
        misc_offset = ORDERS[personality % 24].index('M') * 12
        is_egg = struct.unpack_from('<I', plain, misc_offset + 4)[0] & (1 << 30)
        hp, maximum = struct.unpack_from('<HH', data, 86)
        if is_egg or not 1 <= number <= 411 or not 1 <= data[84] <= 100 or not 0 < hp <= maximum:
            continue
        identity = data[:8]
        if any(game.read_bytes(addresses['gPlayerParty'] + slot * PARTY_MON_BYTES, 8) == identity
               for slot in range(PARTY_SIZE)):
            continue
        from .catalog import species
        info = species(number, game.root)
        if info:
            return dict(uid=f'{trainer_id:08x}:{personality:08x}', species_id=number,
                        species=info['name'], level=data[84], slot=index + 1,
                        shiny=True, checksum_valid=True)
    return None
