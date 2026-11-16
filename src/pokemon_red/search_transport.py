"""Transport decisions for a proved local encounter corridor, not world travel."""
from .telemetry import read_walk_state,symbols
from .game_layout import hoenn
from .player_inventory import read_player_inventory
from .acquisition_play import AcquisitionAttention
from .i18n import t

BICYCLE=360
MODES=('auto','walk','run','bike')
BIKE_MIN_ENCOUNTERS_PER_LANE=128

def capabilities(game):
    walk=read_walk_state(game)
    return dict(run=walk['can_run'],bike=not hoenn(game) and bool(game.read8(symbols(game.root)['gMapHeader']+0x18)) and any(r['id']==BICYCLE and r['pocket']=='key' for r in read_player_inventory(game)['items']),on_bike=walk.get('on_bike',False))

def choose_transport(available,tiles,requested='auto',*,expected_encounters=None,workers=1):
    if requested not in MODES:raise ValueError(t('capture.invalid_transport'))
    if requested=='walk':return 'walk'
    if requested=='bike':return 'bike' if available['bike'] and tiles>=4 else 'run' if available['run'] and tiles>=4 else 'walk'
    if requested=='run':return 'run' if available['run'] and tiles>=4 else 'walk'
    # Avoid a paid Bag/menu detour for an obviously short hunt. This conservative
    # amortization floor is a heuristic, not a host-independent speed forecast.
    if expected_encounters is not None and expected_encounters<BIKE_MIN_ENCOUNTERS_PER_LANE*workers:
        return 'run' if available['run'] and tiles>=4 else 'walk'
    # Cycling is reserved for longer, bidirectional, event-free encounter strips.
    # No mounts near NPCs, doors or turns; no automatic world-route bike travel.
    if available['bike'] and tiles>=4:return 'bike'
    return 'run' if available['run'] and tiles>=4 else 'walk'

def set_bicycle(player,enabled):
    before=read_walk_state(player.g)
    if bool(before.get('on_bike'))==bool(enabled):return
    if not before['open'] or before['moving'] or before['in_battle'] or before['battle_pending']:raise AcquisitionAttention(t('capture.transport_interrupted'))
    if not capabilities(player.g)['bike']:raise AcquisitionAttention(t('capture.bike_unavailable'))
    # A coordinate can settle just before the field accepts START. Release the
    # previous movement input for ordinary frames, then revalidate ownership.
    player.advance(20)
    settled=read_walk_state(player.g)
    if not settled['open'] or settled['moving'] or settled['position']!=before['position'] or settled['map']!=before['map'] or settled['battle_pending']:raise AcquisitionAttention(t('capture.transport_interrupted'))
    from .field_item_menu import use_field_item
    use_field_item(player,BICYCLE,started=lambda:bool(read_walk_state(player.g).get('on_bike'))==bool(enabled))
    for _ in range(180):
        player.w.safe_point();state=read_walk_state(player.g)
        if state['map']!=before['map'] or state['position']!=before['position'] or state['in_battle'] or state['battle_pending']:raise AcquisitionAttention(t('capture.transport_interrupted'))
        if state['open'] and not state['moving'] and bool(state.get('on_bike'))==bool(enabled):
            player.advance(18);return
        player.advance(1)
    raise AcquisitionAttention(t('capture.transport_interrupted'))
