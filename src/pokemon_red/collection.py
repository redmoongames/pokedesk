from .i18n import search_matches,render
from .entity_names import entity_aliases
"""Pure owned-Pokémon list model; party and PC instances keep distinct UIDs."""
def owned_pokemon(inventory):
    if not inventory or not inventory.get('ready'):return []
    rows=[];seen=set()
    for location in ('party','boxes','daycare'):
        for raw in inventory.get(location,[]):
            uid=raw.get('uid')
            if not uid or uid in seen or not raw.get('checksum_valid',True):continue
            seen.add(uid);rows.append(dict(raw,location={'party':'party','boxes':'box','daycare':'daycare'}[location]))
    return sorted(rows,key=lambda m:({'party':0,'box':1,'daycare':2}[m['location']],m.get('box',-1),m.get('box_slot',m.get('slot',0))))

def location_label(mon):
    if mon.get('location')=='daycare':return 'Day Care · '+mon.get('daycare_name','')+' · '+str(mon.get('slot',1))
    if mon.get('location')!='box':return 'Отряд · место '+str(mon.get('slot','—'))
    return 'PC · '+mon.get('box_name','BOX'+str(mon.get('box',0)+1))+' · '+str(mon.get('box_slot',0)+1)

def filter_pokemon(rows,query='',scope='all'):
    query=query.strip().casefold()
    return [m for m in rows if (scope!='party' or m['location']=='party') and (scope!='box' or m['location']=='box') and (scope!='shiny' or m.get('shiny')) and search_matches(query,m.get('nickname',''),entity_aliases('species',m.get('species_id'),m.get('species','')),location_label(m),render(location_label(m),locale='en'), 'shiny шайни' if m.get('shiny') else '')]

def read_daycare(game):
    """Owned deposits in both FRLG day cares; levels are those at deposit time."""
    from .telemetry import symbols
    from .models import decode_mon
    from .catalog import species
    from .game_layout import save_block,hoenn
    sy=symbols(game.root);sb=save_block(game,1);sb2=save_block(game,2)
    if not 0x02000000<=sb<0x02040000-0x3d68 or not 0x02000000<=sb2<0x02040000-0xf24:return []
    trainer=game.read32(sb2+10);rows=[]
    # global.h: DaycareMon = BoxPokemon(80) + mail(56) + steps(4).
    from .game_adapters import adapter
    entries=adapter(game.root).memory.daycare
    for offset,place,slot in entries:
        address=sb+offset
        if not game.read8(address+19)&2:continue
        mon=decode_mon(game.read_bytes(address,80),game.root,slot-1,trainer)
        if mon['checksum_valid'] and species(mon['species_id'],game.root):
            steps=sb+0x30ac+4*(slot-1) if hoenn(game) else address+136
            mon.update(location='daycare',daycare_name=place,daycare_steps=game.read32(steps));rows.append(mon)
    return rows
