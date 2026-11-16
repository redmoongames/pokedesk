from .editions import edition
"""The same decoded Pokémon model for party, PC, planning and inspectors."""
import bisect
import itertools
import struct
import hashlib
from .catalog import catalog,species,move

ORDERS=tuple(itertools.permutations('GAEM'))
STAT_KEYS=('hp','attack','defense','speed','special_attack','special_defense')

def calculate_stats(info,level,ivs=None,evs=None,nature=0):
    ivs=ivs or [15]*6;evs=evs or [0]*6;result={}
    for i,key in enumerate(STAT_KEYS):
        raw=(2*info['base_stats'][key]+ivs[i]+evs[i]//4)*level//100
        if i==0:value=1 if info['national_id']==292 else raw+level+10
        else:
            value=raw+5;up,down=divmod(nature,5)
            if up!=down:value=value*(110 if i-1==up else 90 if i-1==down else 100)//100
        result[key]=value
    return result

def decode_mon(data,root,slot=0,trainer_id=None):
    from .telemetry import decode_text,status_name,read_move
    personality,ot_id=struct.unpack_from('<II',data);key=personality^ot_id
    plain=b''.join(struct.pack('<I',v^key) for v in struct.unpack_from('<12I',data,32))
    order=ORDERS[personality%24];g=order.index('G')*12;a=order.index('A')*12;m=order.index('M')*12;e=order.index('E')*12
    number=struct.unpack_from('<H',plain,g)[0];info=species(number,root)
    xp=struct.unpack_from('<I',plain,g+4)[0];packed_ivs=struct.unpack_from('<I',plain,m+4)[0]
    ivs=[(packed_ivs>>(5*i))&31 for i in range(6)];evs=list(plain[e:e+6]);nature=personality%25
    curve=catalog(root)['growth'][info['growth']] if info else [0]*101
    boxed=len(data)<100;level=max(1,min(100,bisect.bisect_right(curve[1:],xp))) if boxed else data[84]
    predicted=calculate_stats(info,level,ivs,evs,nature) if info else dict.fromkeys(STAT_KEYS,0)
    hp,maximum=(predicted['hp'],predicted['hp']) if boxed else struct.unpack_from('<HH',data,86)
    status=0 if boxed else struct.unpack_from('<I',data,80)[0]
    stats={k:predicted[k] for k in STAT_KEYS[1:]} if boxed else dict(zip(STAT_KEYS[1:],struct.unpack_from('<5H',data,90)))
    moves=[]
    for i,number_move in enumerate(struct.unpack_from('<4H',plain,a)):
        if not number_move:continue
        entry=read_move(number_move,plain[a+8+i],root);bonus=plain[g+8]>>(2*i)&3
        entry['max_pp']=entry['pp']+entry['pp']*bonus//5;moves.append(entry)
    result=dict(slot=slot+1,nickname=decode_text(data[8:18]),uid=f'{ot_id:08x}:{personality:08x}',traded=trainer_id is not None and ot_id!=trainer_id,
        personality=personality,nature=nature,ivs=dict(zip(STAT_KEYS,ivs)),evs=dict(zip(STAT_KEYS,evs)),
        held_item=struct.unpack_from('<H',plain,g+2)[0],friendship=plain[g+9],is_egg=bool(packed_ivs>>30&1 or data[19]&4),
        ability_id=(info.get('abilities') or [0])[-1 if packed_ivs>>31 else 0],moves=moves,stats=stats,
        species=info.get('name','?'),species_id=number,level=level,hp=hp,max_hp=maximum,status=status_name(status,hp),status_code=status,
        experience=xp,exp_to_next_level=max(0,(curve[level+1] if 0<=level<100 else xp)-xp),hp_source='box_calculated' if boxed else 'party',
        checksum_valid=(sum(struct.unpack('<24H',plain))&65535)==struct.unpack_from('<H',data,28)[0],
        shiny=(personality>>16 ^ personality&65535 ^ ot_id>>16 ^ ot_id&65535)<8)
    return result

def read_inventory(game):
    from .telemetry import symbols,read_state,decode_text
    state=read_state(game);result=dict(game=edition(game.root).id,frame=game.frame,party=state.get('party',[]),boxes=[],ready=state.get('ready',False) and state.get('telemetry_valid',True))
    if not result['ready']:return result
    from .game_layout import storage as storage_pointer,save_block
    syms=symbols(game.root);pointer=storage_pointer(game);sb2=save_block(game,2)
    if not 0x02000000<=pointer<=0x02040000-0x83d0:return dict(result,ready=False)
    trainer_id=int.from_bytes(game.read_bytes(sb2+10,4),'little')
    for mon in result['party']:mon['location']='party'
    storage=game.read_bytes(pointer,0x83d0)
    # All box bytes/names plus OT-dependent display state. Stable across party HP
    # changes and frame progress; changes even for same-frame PC edits/restores.
    # The selected-box cursor is separate metadata; scrolling the PC must not
    # rebuild every Pokémon record when no contents or box names changed.
    result['storage_revision']=hashlib.sha256(storage[4:]+trainer_id.to_bytes(4,'little')).hexdigest()
    for box in range(14):
        name=decode_text(storage[0x8344+box*9:0x8344+(box+1)*9])
        for slot in range(30):
            address=4+(box*30+slot)*80
            if not storage[address+19]&2:continue
            mon=decode_mon(storage[address:address+80],game.root,slot,trainer_id)
            if mon['checksum_valid'] and species(mon['species_id'],game.root):
                mon.update(location='box',box=box,box_slot=slot,box_name=name);result['boxes'].append(mon)
    result['current_box']=storage[0]
    return result


def read_roster_uids(game):
    """Canonical ownership independent of transient battle/UI telemetry.

    Battle initialization can invalidate gBattleMons for several frames while
    party and PC remain intact. Adoption validates these canonical structures.
    """
    from .telemetry import symbols
    from .game_layout import storage as storage_pointer
    syms=symbols(game.root);count=game.read8(syms['gPlayerPartyCount']);pointer=storage_pointer(game)
    if not 1<=count<=6 or not 0x02000000<=pointer<=0x02040000-0x83d0:raise ValueError('Canonical roster is unavailable')
    party=game.read_bytes(syms['gPlayerParty'],count*100);storage=game.read_bytes(pointer,0x83d0)
    rows=[party[i*100:(i+1)*100] for i in range(count)]
    rows.extend(storage[4+i*80:4+(i+1)*80] for i in range(420) if storage[4+i*80+19]&2)
    result=set()
    for raw in rows:
        personality,ot=struct.unpack_from('<II',raw);key=personality^ot
        plain=[v^key for v in struct.unpack_from('<12I',raw,32)]
        checksum=sum((v&65535)+(v>>16) for v in plain)&65535
        if checksum!=struct.unpack_from('<H',raw,28)[0]:raise ValueError('Canonical roster checksum failed')
        result.add(f'{ot:08x}:{personality:08x}')
    return result
