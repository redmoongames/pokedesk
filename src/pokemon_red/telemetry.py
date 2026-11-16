"""Read-only FireRed Rev 1 structures. Addresses never inferred from screen pixels."""
from __future__ import annotations

from .paths import resource
from .game_layout import main_flags

from functools import lru_cache
import itertools
import json
from pathlib import Path
import struct

from .engine import Game, ROOT
from .editions import edition,reference_path
from .game_layout import hoenn,save_block,flags_offset,vars_offset,flag as game_flag,battle_struct
from .game_adapters import adapter
from .catalog import species as species_info, move as move_info


def status_name(value: int, hp: int) -> str:
    if hp == 0:
        return "Без сознания"
    for mask, name in ((7, "Сон"), (0x88, "Отравление"), (0x10, "Ожог"),
                       (0x20, "Заморозка"), (0x40, "Паралич")):
        if value & mask:
            return name
    return "В норме"


def decode_text(data: bytes) -> str:
    table = {0x00: " ", 0xAB: "!", 0xAC: "?", 0xAD: ".", 0xAE: "-",
             0xB0: "…", 0xB1: '“', 0xB2: '”', 0xB3: "‘", 0xB4: "’",
             0xB5: "♂", 0xB6: "♀", 0xB8: ",", 0xBA: "/", 0xEF: ":",
             0x1B:'é',0x2D:'&',0x2E:'+',0x35:'=',0x36:';',0xFE:'\n'}
    table.update({0xA1 + i: str(i) for i in range(10)})
    table.update({0xBB + i: chr(65 + i) for i in range(26)})
    table.update({0xD5 + i: chr(97 + i) for i in range(26)})
    result = []
    for value in data:
        if value == 0xFF:
            break
        result.append(table.get(value, "?"))
    return "".join(result).strip()


def parse_symbols(text):
    entries = {}
    for line in text.splitlines():
        fields = line.split()
        if len(fields) == 4:
            try:
                entries[fields[3]] = int(fields[0], 16)
            except ValueError:
                pass
    return entries


@lru_cache
def symbols(root: Path = ROOT) -> dict[str, int]:
    entries=parse_symbols((resource(root,"vendor/reference")/edition(root).symbols).read_text())
    if edition(root).family=='hoenn':
        for new,old in {'gTrainerBattleOpponent_A':'gTrainerBattleOpponent','sGlobalScriptContext':'sScriptContext1','sLockFieldControls':'sScriptContext2Enabled','sMessageBoxType':'sMessageBoxMode'}.items():entries[new]=entries[old]
        entries['CB2_PokeStorage']=entries['sub_8096B38']
        entries['gLocalLinkPlayerId']=entries['gUnknown_03004860']
        for new,old in {'EventScript_FieldPoison':'gUnknown_081A14B8','EventScript_FieldWhiteOut':'EventScript_1A14CA','Task_TryFieldPoisonWhiteOut':'Task_WhiteOut'}.items():entries[new]=entries[old]
    return entries


@lru_cache
def maps(root: Path = ROOT) -> dict[tuple[int, int], str]:
    groups = json.loads(reference_path(root,"map_groups.json").read_text())
    return {(group, number): name for group, key in enumerate(groups["group_order"])
            for number, name in enumerate(groups[key])}


@lru_cache
def address_names(root=ROOT):
    # Static functions may have the same name in several translation units.
    result={}
    for line in (resource(root,'vendor/reference')/edition(root).symbols).read_text().splitlines():
        fields=line.split()
        if len(fields)==4 and not fields[3].startswith(('.', '$')):
            address=int(fields[0],16)
            if address not in result or fields[1]=='g':result[address]=fields[3]
    if edition(root).family=='hoenn':
        from .hoenn import canonical_name
        result={address:canonical_name(name) for address,name in result.items()}
    return result


def read_controls(game):
    if hoenn(game):
        from .hoenn import read_controls as read_rs
        return read_rs(game)
    from .field_recovery import poison_notification
    s, names = symbols(game.root), address_names(game.root)
    def name(pointer): return names.get(pointer & ~1, hex(pointer & ~1))
    tasks = []
    task_data=game.read_bytes(s['gTasks'],16*40)
    for i in range(16):
        a=i*40
        if task_data[a+4]:
            tasks.append(dict(id=i, name=name(struct.unpack_from('<I',task_data,a)[0]),
                              data=list(struct.unpack_from('<16h',task_data,a+8))))
    internal = game.read32(s['sPartyMenuInternal'])
    actions = []
    if 0x02000000 <= internal < 0x02040000-1024:
        actions = list(game.read_bytes(internal+15, min(8, game.read8(internal+23))))
    storage=game.read32(s['gStorage']);choose=game.read32(s['sChooseBoxMenu'])
    storage_info=dict(state=game.read8(storage),mode=game.read8(storage+1),area=game.read8(s['sCursorArea']),cursor=game.read8(s['sCursorPosition']),choose_box=game.read8(choose+0x244) if 0x02000000<=choose<0x02040000-0x248 else None) if 0x02000000<=storage<0x02040000-4096 else None
    callback=name(game.read32(s['gMain']+4));summary_mode=None
    if callback in ('CB2_SetUpPSS','CB2_RunPokemonSummaryScreen'):
        pointer=game.read32(s['sMonSummaryScreen'])
        if 0x02000000<=pointer<0x02040000-0x3308:summary_mode=game.read8(pointer+0x3208)
    return dict(callback=callback, tasks=tasks,storage=storage_info,summary_mode=summary_mode,
        yes_no_state=game.read8(s['gBattleCommunication']),yes_no_cursor=game.read8(s['gBattleCommunication']+1),
        player_fainted=bool(game.read32(s['gHitMarker'])&(1<<22)),player_party_slot=game.read16(s['gBattlerPartyIndexes'])+1,
        field_locked=bool(game.read8(s['sLockFieldControls'])),
        field_recovery=poison_notification(game),
        message_box=game.read8(s['sMessageBoxType']),
        field_script_native=name(game.read32(s['sGlobalScriptContext']+4)) if game.read8(s['sGlobalScriptContext']+1)==2 else None,
        moving=game.read8(s['gPlayerAvatar']+3),
        controllers=[name(game.read32(s['gBattlerControllerFuncs']+4*i)) for i in range(4)],
        action_cursor=list(game.read_bytes(s['gActionSelectionCursor'],4)),
        move_cursor=list(game.read_bytes(s['gMoveSelectionCursor'],4)),
        battle_script_opcode=game.read8(game.read32(s['gBattlescriptCurrInstr'])) if 0x08000000<=game.read32(s['gBattlescriptCurrInstr'])<0x0a000000 else -1,
        learn_move_state=game.read8(s['gBattleScripting']+31),
        move_to_learn=game.read16(s['gMoveToLearn']),
        party_cursor=game.read8(s['gPartyMenu']+9), party_cursor2=game.read8(s['gPartyMenu']+10),
        party_action=game.read8(s['gPartyMenu']+11), party_actions=actions,
        menu_cursor=game.read8(0x0203ade4+2),
        start_cursor=game.read8(s['sStartMenuCursorPos']),
        start_order=list(game.read_bytes(s['sStartMenuOrder'],min(9,game.read8(s['sNumStartMenuItems'])))))


def read_decision(game):
    if hoenn(game):
        from .hoenn import read_decision as read_rs
        return read_rs(game)
    """Small per-frame guard: stop before a fresh A press can answer a move prompt."""
    s=symbols(game.root); callback=game.read32(s['gMain']+4)&~1
    slot=None
    if callback==s['BattleMainCB2']:
        instr=game.read32(s['gBattlescriptCurrInstr'])
        if 0x08000000<=instr<0x0a000000 and game.read8(instr) in (0x5a,0x5b) and game.read8(s['gBattleScripting']+31)==1:
            pointer=game.read32(s['gBattleStruct'])
            if 0x02000000<=pointer<0x02040000-32:slot=game.read8(pointer+16)
    elif callback==s.get('CB2_EvolutionSceneUpdate'):
        for i in range(16):
            a=s['gTasks']+40*i
            if game.read8(a+4) and (game.read32(a)&~1)==s.get('Task_EvolutionScene'):
                if game.read16(a+8)==22 and game.read16(a+8+12)==4:slot=game.read16(a+8+20)
    if slot is None:return None
    return dict(code='move_choice_required',party_slot=slot+1,move_id=game.read16(s['gMoveToLearn']),source='battle' if callback==s['BattleMainCB2'] else 'evolution')

def read_learning_control(game):
    if hoenn(game):
        from .hoenn import read_learning_control as read_rs
        return read_rs(game)
    """Exact Rev 1 menu states. Read only; selection never inferred from pixels."""
    s=symbols(game.root);names=address_names(game.root);cb=names.get(game.read32(s['gMain']+4)&~1,'unknown');evo=None;summary=None
    if cb in ('CB2_EvolutionSceneUpdate','CB2_BeginEvolutionScene'):
        tasks=game.read_bytes(s['gTasks'],16*40)
        for i in range(16):
            a=i*40
            if tasks[a+4] and names.get(struct.unpack_from('<I',tasks,a)[0]&~1) in ('Task_EvolutionScene','Task_BeginEvolutionScene'):
                d=struct.unpack_from('<16h',tasks,a+8);evo=dict(state=d[0],pre=d[1],post=d[2],bits=d[3],learn_state=d[6],yes=d[7],no=d[8],cancelled=d[9],slot=d[10]+1)
    if cb in ('CB2_SetUpPSS','CB2_RunPokemonSummaryScreen'):
        pointer=game.read32(s['sMonSummaryScreen'])
        if 0x02000000<=pointer<0x02040000-0x3308:
            raw=game.read_bytes(pointer+0x3290,100);pid,ot=struct.unpack_from('<II',raw)
            # The decomp's comment says 0x325A; the Rev 1 compiled layout starts
            # this u16 array at 0x3258 (the preceding s16 leaves halfword room).
            summary=dict(mode=game.read8(pointer+0x3208),stage=game.read8(pointer+0x3288),cursor=game.read8(s['sMoveSelectionCursorPos']),moves=list(struct.unpack('<5H',game.read_bytes(pointer+0x3258,10))),uid=f'{ot:08x}:{pid:08x}',party=game.read32(pointer+0x32f4)==s['gPlayerParty'],slot=game.read8(s['sLastViewedMonIndex'])+1,return_callback=names.get(game.read32(pointer+0x32f8)&~1))
    battle=None
    if cb=='BattleMainCB2':
        pointer=game.read32(s['gBattleStruct']);instr=game.read32(s['gBattlescriptCurrInstr'])
        battle=dict(op=game.read8(instr) if 0x08000000<=instr<0x0a000000 else -1,state=game.read8(s['gBattleScripting']+31),slot=game.read8(pointer+16)+1 if 0x02000000<=pointer<0x02040000-32 else None)
    return dict(frame=game.frame,callback=cb,evo=evo,summary=summary,battle=battle,cursor=game.read8(s['gBattleCommunication']+1),move_id=game.read16(s['gMoveToLearn']),stable=cb=='CB2_Overworld' and not game.read8(s['sScriptContext2Enabled'] if hoenn(game) else s['sLockFieldControls']))

def read_learning_mon(game,uid):
    from .models import decode_mon
    s=symbols(game.root);count=min(6,game.read8(s['gPlayerPartyCount']));data=game.read_bytes(s['gPlayerParty'],count*100)
    for i in range(count):
        raw=data[i*100:(i+1)*100];pid,ot=struct.unpack_from('<II',raw)
        if f'{ot:08x}:{pid:08x}'==uid:return decode_mon(raw,game.root,i)
    return None


def read_training_alert(game,interaction='travel',trainer_policy=None):
    """Cheap per-frame guard: revoke bot input before another A can skip a dialog."""
    s=symbols(game.root)
    from .travel_policy import guard
    allowed=guard(game,trainer_policy)
    if allowed['battle'] or allowed['scene']:return None
    if main_flags(game)&2:
        flags=game.read32(s['gBattleTypeFlags'])
        if flags & (8|1|2|0x40|0x80|0x200):return dict(code='unexpected_battle',message='Начался бой с тренером или другой неподдерживаемый бой. Управление у тебя.',flags=flags)
        return None
    if interaction in ('healing','storage'):return None
    if (game.read32(s['gMain']+4)&~1)!=s['CB2_Overworld'] or not game.read8(s['sScriptContext2Enabled'] if hoenn(game) else s['sLockFieldControls']):return None
    from .field_recovery import poison_notification
    if poison_notification(game):return None
    if game.read8(s['sMessageBoxType']):return dict(code='unexpected_dialog',message='Неожиданный диалог по пути. Пройди его вручную и заново запусти прокачку.')
    ctx=s['sGlobalScriptContext']
    if game.read8(ctx+1)==2 and (game.read32(ctx+4)&~1)==s.get('WaitForMovementFinish'):
        return dict(code='unexpected_scene',message='Началась сюжетная сцена с перемещением персонажей. Управление у тебя; после сцены запусти прокачку заново.')
    return None


def read_field_badges(game):
    s=symbols(game.root);sb=save_block(game,1)
    if not 0x02000000<=sb<0x02040000-0x3d68:return []
    return [i+1 for i in range(8) if game_flag(game,(0x807 if hoenn(game) else 0x820)+i)]

def read_field_teleport(game):
    """SaveBlock1.lastHealLocation and current map type, never a guessed town."""
    s=symbols(game.root);sb=save_block(game,1)
    if not 0x02000000<=sb<0x02040000-0x3d68:return None
    group,number,warp=struct.unpack('<bbb',game.read_bytes(sb+0x1c,3))
    x,y=struct.unpack('<hh',game.read_bytes(sb+0x20,4))
    return dict(map_type=game.read8(s['gMapHeader']+0x17),landing=dict(map=maps(game.root).get((group,number)),point=[x,y],warp_id=warp))


def visible_objects(templates,*,current,flag_set,rules=(),live=None):
    """Temp flags belong to a map visit; never reuse them on another map."""
    result=[]
    for template in templates:
        o=dict(template);flag=o.get('flag',0)
        if 0<flag<0x900 and (current or flag>=0x20) and flag_set(flag):continue
        for rule in rules:
            if rule['local_id']==o['local_id'] and not flag_set(rule['flag_unset']):o.update(x=rule['x'],y=rule['y'],block_reason=rule['reason'])
        o.update(anchor_x=o['x'],anchor_y=o['y'])
        if live and o['local_id'] in live:o.update(live[o['local_id']])
        result.append(o)
    return result


def read_map(game, map_name=None):
    """Current ROM layout and live obstacles, with metatile behavior/collision."""
    s = symbols(game.root)
    header=s['gMapHeader']
    if map_name:
        group,number=next((key for key,name in maps(game.root).items() if name==map_name))
        header=game.read32(game.read32(s['gMapGroups']+4*group)+4*number)
    layout = game.read32(header)
    if not 0x08000000 <= layout < 0x0a000000: return None
    w,h = game.read32(layout),game.read32(layout+4)
    if not (1<=w<=200 and 1<=h<=200): return None
    cache=getattr(game,'_map_cache',{})
    key=(layout,game.read32(header+4))
    if key not in cache:
        blocks = game.read32(layout+12)
        attributes = [game.read32(game.read32(layout+16+4*i)+(16 if hoenn(game) else 20)) for i in range(2)]
        block_data=struct.unpack('<'+str(w*h)+'H',game.read_bytes(blocks,w*h*2))
        primary=512 if hoenn(game) else 640;fmt='H' if hoenn(game) else 'I';size=2 if hoenn(game) else 4
        attribute_data=[struct.unpack('<'+str(primary)+fmt,game.read_bytes(a,primary*size)) for a in attributes]
        tiles=[]
        for y in range(h):
            row=[]
            for x in range(w):
                value=block_data[y*w+x]; tile=value&1023
                attr=attribute_data[tile>=primary][tile if tile<primary else tile-primary]
                behavior=attr&255 if hoenn(game) else attr&511
                encounters=(game.read8(s['sTileBitAttributes']+behavior)&1) if hoenn(game) and behavior<0xf0 else 0 if hoenn(game) else attr>>24&7
                row.append([value>>10&3, behavior, value>>12, encounters])
            tiles.append(row)
        events=game.read32(header+4);templates=game.read32(events+4)
        trainers=[];objects=[]
        for i in range(min(64,game.read8(events))):
            a=templates+24*i
            if game.read8(a+2)==0:objects.append(dict(local_id=game.read8(a),graphics_id=game.read8(a+1),x=_signed(game.read16(a+4)),y=_signed(game.read16(a+6)),movement=game.read8(a+9),range_x=game.read8(a+10)&15,range_y=game.read8(a+10)>>4,flag=game.read16(a+20)))
            if game.read8(a+2)==0 and game.read16(a+12):
                script=game.read32(a+16)
                trainer_id=int.from_bytes(game.read_bytes(script+2,2),'little') if game.read8(script)==0x5c else None
                trainers.append(dict(local_id=game.read8(a),x=_signed(game.read16(a+4)),y=_signed(game.read16(a+6)),anchor_x=_signed(game.read16(a+4)),anchor_y=_signed(game.read16(a+6)),trainer_id=trainer_id,
                    movement=game.read8(a+9),range_x=game.read8(a+10)&15,range_y=game.read8(a+10)>>4,script=script,script_kind=game.read8(script+1),
                    sight=game.read16(a+14),trainer_type=game.read16(a+12)))
        warps=[];pointer=game.read32(events+8)
        for i in range(min(64,game.read8(events+1))):
            a=pointer+i*8
            warps.append(dict(index=i,destination_warp=game.read8(a+5),x=_signed(game.read16(a)),y=_signed(game.read16(a+2)),
                destination=maps(game.root).get((game.read8(a+7),game.read8(a+6)))))
        coords=[];pointer=game.read32(events+12)
        for i in range(min(64,game.read8(events+2))):
            a=pointer+i*16
            if game.read32(a+12):coords.append(dict(x=_signed(game.read16(a)),y=_signed(game.read16(a+2)),var=game.read16(a+6),value=game.read16(a+8)&255))
        signs=[];pointer=game.read32(events+16)
        for i in range(min(64,game.read8(events+3))):
            a=pointer+i*12
            if game.read8(a+5)<=4:signs.append([_signed(game.read16(a)),_signed(game.read16(a+2))])
        sign_approaches=[]
        for y,row in enumerate(tiles):
            for x,tile in enumerate(row):
                behavior=tile[1]
                if behavior in (0x84,0x87,0x88,0x91,0x92):
                    # FireRed auto-reads a sign at the end of a step even after
                    # the D-pad was released. Keep its facing squares off transit.
                    sign_approaches.append([x,y+1])
                    if behavior in (0x84,0x91,0x92):sign_approaches.append([x,y-1])
        cache[key]=dict(width=w,height=h,tiles=tiles,trainers=trainers,objects=objects,warps=warps,coordinate_events=coords,signs=signs,sign_approaches=sign_approaches)
        if hoenn(game):
            attributes=game.read_bytes(s['sTileBitAttributes'],0xf0)
            cache[key]['land_encounter_behaviors']=[i for i,v in enumerate(attributes) if v&1 and not v&2]
        from .run_context import digest
        cache[key]['tiles']=tuple(tuple(tuple(t) for t in row) for row in tiles)
        cache[key]['static_geometry']=digest([w,h,tiles])
        game._map_cache=cache
    # A sign blocks the approach direction, not the entire neighboring square.
    # E.g. Route4 (18,6) must remain crossable east/west to reach Mt. Moon.
    obstacles=list(cache[key]['signs']);live_trainers={};live_objects={}
    player_id=game.read8(s['gPlayerAvatar']+5)
    is_current=(layout==game.read32(s['gMapHeader']) and key[1]==game.read32(s['gMapHeader']+4))
    for i in range(16) if is_current else ():
        a=s['gObjectEvents']+i*36
        if i!=player_id and game.read8(a)&1:
            obstacles.append([_signed(game.read16(a+16))-7,_signed(game.read16(a+18))-7])
            live_objects[game.read8(a+8)]=dict(x=obstacles[-1][0],y=obstacles[-1][1])
            if game.read8(a+7):live_trainers[game.read8(a+8)]=dict(x=obstacles[-1][0],y=obstacles[-1][1],facing=game.read8(a+24)&15)
    trainers=[];sb1=save_block(game,1)
    for t in cache[key]['trainers']:
        flag=0x500+t['trainer_id'] if t['trainer_id'] is not None else None
        defeated=bool(flag is not None and 0x02000000<=sb1<0x02040000-0x3d68 and game.read8(sb1+flags_offset(game)+flag//8)&(1<< (flag%8)))
        trainers.append(dict(t,**live_trainers.get(t['local_id'],{}),defeated=defeated))
    valid_save=0x02000000<=sb1<0x02040000-0x3d68
    active=[]
    for event in cache[key]['coordinate_events']:
        var=event['var']
        value=game.read16(sb1+vars_offset(game)+(var-0x4000)*2) if valid_save and 0x4000<=var<0x4100 and (is_current or var>=0x4010) else None
        if var==0 or value is None or value==event['value']:active.append([event['x'],event['y']])
    if map_name is None:
        map_name=maps(game.root).get((game.read8(sb1+4),game.read8(sb1+5))) if valid_save else None
    from .zones import source_spec
    objects=visible_objects(cache[key].get('objects',[]),current=is_current,flag_set=lambda flag:bool(valid_save and game.read8(sb1+flags_offset(game)+flag//8)&(1<<(flag%8))),rules=[r for r in source_spec(game.root).get('object_rules',[]) if r['map']==map_name],live=live_objects)
    from .movement import npc_envelope
    template_points={(o['x'],o['y']) for o in objects if o['local_id'] not in live_objects} if is_current else npc_envelope(dict(objects=objects))
    obstacles.extend([list(p) for p in sorted(template_points) if list(p) not in obstacles])
    portals=[e['point'] for e in source_spec(game.root)['links'] if e['source']==map_name]
    from .field_rules import rules
    return dict(cache[key],name=map_name,game=edition(game.root).id,cut_graphics=rules(edition(game.root).id)['cut_graphics'],cut_badge=rules(edition(game.root).id)['cut_badge'],map_type=game.read8(header+0x17),field_badges=read_field_badges(game),obstacles=obstacles,trainers=trainers,objects=objects,portal_points=portals,script_triggers=active)

def read_walk_state(game):
    """Small per-frame sample: no party, PC, catalog or history decoding."""
    s=symbols(game.root);avatar=game.read_bytes(s['gPlayerAvatar'],8);objects=game.read_bytes(s['gObjectEvents'],16*36)
    sb1=save_block(game,1);valid=0x02000000<=sb1<=0x02040000-0x3d68
    player=avatar[5];position=None;actors=[]
    for i in range(16):
        offset=i*36
        if objects[offset]&1:
            x,y=struct.unpack_from('<hh',objects,offset+16);p=[x-7,y-7]
            if i==player:position=p
            else:
                actors.append(p);px,py=struct.unpack_from('<hh',objects,offset+20);previous=[px-7,py-7]
                if previous!=p:actors.append(previous)
    map_id=tuple(game.read_bytes(sb1+4,2)) if valid else None
    open_field=(game.read32(s['gMain']+4)&~1)==s['CB2_Overworld'] and not game.read8(s['sScriptContext2Enabled'] if hoenn(game) else s['sLockFieldControls'])
    # BattleStart tasks are destroyed before CB2_InitBattle sets the battle
    # flag. Keep this short transition guarded as well (not an unknown dialog).
    pending=(game.read32(s['gMain']+4)&~1) in {s[key] for key in ('CB2_InitBattle','CB2_InitBattleInternal') if key in s}
    if not open_field and not pending:
        tasks=game.read_bytes(s['gTasks'],16*40);names=address_names(game.root)
        pending=any(tasks[i*40+4] and names.get(struct.unpack_from('<I',tasks,i*40)[0]&~1) in ('Task_BattleStart','Task_BattleTransition') for i in range(16))
    can_run=valid and game_flag(game,0x860 if hoenn(game) else 0x82f) and (game.read8(s['gMapHeader']+0x17) in (1,2,3,4) if hoenn(game) else bool(game.read8(s['gMapHeader']+0x19)&2)) and bool(avatar[0]&1) and not bool(avatar[0]&0x5e)
    return dict(on_bike=bool(avatar[0]&6) and not bool(avatar[0]&0x58),bike_allowed=bool(avatar[0]&6) and not hoenn(game) and bool(game.read8(s['gMapHeader']+0x18)),on_foot=bool(avatar[0]&1) and not bool(avatar[0]&0x5e),can_run=bool(can_run),avatar_flags=avatar[0],frame=game.frame,ready=valid and position is not None,map=maps(game.root).get(map_id),position=position,actors=actors,moving=bool(avatar[3]),
        in_battle=bool(main_flags(game)&2),battle_pending=pending,open=open_field)


def _signed(value: int) -> int:
    return value if value < 32768 else value - 65536


def read_party_mon(game,address,slot,trainer_id=None):
    from .models import decode_mon
    return decode_mon(game.read_bytes(address,100),game.root,slot,trainer_id)


def read_move(number,pp,root):
    info=move_info(number,root)
    return dict(info or dict(id=number,name=f'Неизвестный приём #{number}',pp=0,power=0,accuracy=0,type='—',type_id=0,category='Status',description='Ожидание корректных данных'),current_pp=pp,valid=bool(info))


def read_state(game: Game) -> dict:
    syms = symbols(game.root)
    sb1 = save_block(game,1)
    sb2 = save_block(game,2)
    callback = game.read32(syms["gMain"] + 4) & ~1
    battle = bool(main_flags(game)&2)
    result = {"ready": False, "frame": game.frame, "game": edition(game.root).label,
              "player": None, "position": None, "map": None, "money": None,
              "party": [], "in_battle": battle, "play_time": None, "badges": [], "pokedex": None}
    if not (0x02000000 <= sb1 <= 0x02040000 - 0x3D68 and
            0x02000000 <= sb2 <= 0x02040000 - 0xF24):
        result["status"] = "Ожидание загрузки игры"
        return result
    name = decode_text(game.read_bytes(sb2, 8))
    if hoenn(game) and not 0x08000000<=game.read32(syms['gMapHeader'])<0x0a000000:
        result['status']='Начало игры';return result
    money = game.read32(sb1 + 0x490) if hoenn(game) else game.read32(sb1 + 0x290) ^ game.read32(sb2 + 0xF20)
    group, number = game.read8(sb1 + 4), game.read8(sb1 + 5)
    x, y = _signed(game.read16(sb1)), _signed(game.read16(sb1 + 2))
    coordinate_source = "save_block"
    event_id = game.read8(syms["gPlayerAvatar"] + 5)
    if event_id < 16:
        event = syms["gObjectEvents"] + 0x24 * event_id
        if game.read8(event) & 1:
            # ObjectEvent.currentCoords includes the seven-tile map border.
            x = _signed(game.read16(event + 0x10)) - 7
            y = _signed(game.read16(event + 0x12)) - 7
            coordinate_source = "object_event"
    result.update(ready=bool(name) and money <= 999999,
                  player=name or None, position={"x": x, "y": y, "source": coordinate_source},
                  map={"group": group, "number": number,
                       "name": maps(game.root).get((group, number), f"Map {group}:{number}")},
                  money=money if money <= 999999 else None,
                  status="Бой" if battle else "Игра загружена")
    result["play_time"] = {"hours": game.read16(sb2 + 0xE), "minutes": game.read8(sb2 + 0x10),
                           "seconds": game.read8(sb2 + 0x11)}
    badge_bits = game.read8(sb1 + flags_offset(game) + (0x807 if hoenn(game) else 0x820) // 8)
    result["badges"] = [name for i, name in enumerate(("Stone","Knuckle","Dynamo","Heat","Balance","Feather","Mind","Rain") if hoenn(game) else ("Boulder", "Cascade", "Thunder", "Rainbow", "Soul", "Marsh", "Volcano", "Earth")) if game_flag(game,(0x807 if hoenn(game) else 0x820)+i)]
    # Dex flags use National Dex numbering. Ignore padding and unused species bits.
    def dex_count(offset):
        bits = int.from_bytes(game.read_bytes(sb2 + offset, 52), "little")
        return (bits & ((1 << 386) - 1)).bit_count()
    result["pokedex"] = {"caught": dex_count(0x28), "seen": dex_count(0x5C)}

    count = game.read8(syms["gPlayerPartyCount"])
    if count > 6:
        result.update(ready=False, status="Команда ещё не загружена")
        return result
    trainer_id=int.from_bytes(game.read_bytes(sb2+10,4),'little')
    slots=range(6) if callback==syms.get('CB2_PokeStorage') else range(count)
    result['party']=[read_party_mon(game,syms['gPlayerParty']+slot*100,slot,trainer_id) for slot in slots if callback!=syms.get('CB2_PokeStorage') or game.read8(syms['gPlayerParty']+slot*100+19)&2]
    result['telemetry_valid']=all(m['checksum_valid'] and 1<=m['level']<=100 and species_info(m['species_id'],game.root) and all(a['valid'] for a in m['moves']) for m in result['party'])

    result['controls'] = read_controls(game)
    result['field_teleport']=read_field_teleport(game)
    result['decision'] = read_decision(game)
    result['battle'] = None
    if battle:
        result['battle'] = dict(enemy_party=[], trainer_id=game.read16(syms['gTrainerBattleOpponent_A']),flags=game.read32(syms['gBattleTypeFlags']), outcome=game.read8(syms['gBattleOutcome']),turn=game.read8(syms['gBattleResults']+0x13), enemies=[], allies=[])
        # FireRed leaves gEnemyPartyCount at zero in ordinary wild battles.
        # Derive occupied slots from the encrypted party structures instead.
        result['battle']['enemy_party']=[m for slot in range(6) if (m:=read_party_mon(game,syms['gEnemyParty']+slot*100,slot))['checksum_valid'] and species_info(m['species_id'],game.root)]
        live_valid=True
        result['battle']['unverified_battlers']=[]
        for battler in range(min(game.read8(syms["gBattlersCount"]), 4)):
            position = game.read8(syms["gBattlerPositions"] + battler)
            mon = syms["gBattleMons"] + 0x58 * battler
            sp = game.read16(mon)
            moves = [read_move(game.read16(mon+12+2*j),game.read8(mon+36+j),game.root) for j in range(4) if game.read16(mon+12+2*j)]
            live = dict(battler=battler, species_id=sp, species=species_info(sp,game.root).get('name','?'),
                        level=game.read8(mon+42), hp=game.read16(mon+40),max_hp=game.read16(mon+44),
                        types=list(game.read_bytes(mon+33,2)),moves=moves,ability_id=game.read8(mon+32),
                        party_slot=game.read16(syms['gBattlerPartyIndexes']+2*battler)+1)
            live['stats']=dict(zip(('attack','defense','speed','special_attack','special_defense'),[game.read16(mon+o) for o in (2,4,6,8,10)]))
            live['stages']=dict(zip(('hp','attack','defense','speed','special_attack','special_defense','accuracy','evasion'),[v-6 for v in game.read_bytes(mon+24,8)]))
            live['status_code']=game.read32(mon+0x4c)
            live['status2']=game.read32(mon+0x50);live['status3']=game.read32(syms['gStatuses3']+battler*4)
            disable=game.read_bytes(syms['gDisableStructs']+28*battler,28)
            pointer=battle_struct(game,syms)
            live.update(held_item=game.read16(mon+46),disabled_move=struct.unpack_from('<H',disable,4)[0],
                        encored_move=struct.unpack_from('<H',disable,6)[0],encore_turns=disable[14]&15,taunt_turns=disable[19]&15,
                        last_move=game.read16(syms['gLastMoves']+2*battler),
                        choice_move=game.read16(pointer+adapter(game.root).memory.choice_move+2*battler) if 0x02000000<=pointer<0x02040000-0xd8 else 0)
            personality=game.read32(mon+0x48);ot_id=game.read32(mon+0x54)
            live['uid']=f'{ot_id:08x}:{personality:08x}'
            candidates=result['battle']['enemy_party'] if position&1 else result['party']
            identity=next((m for m in candidates if m['slot']==live['party_slot'] and m['uid']==live['uid']),None)
            live['identity_valid']=identity is not None and 0<=live['hp']<=live['max_hp'] and live['max_hp']>0
            if not live['identity_valid']:
                live_valid=False
                result['battle']['unverified_battlers'].append(dict(battler=battler,position=position,party_slot=live['party_slot'],uid=live['uid']))
                continue
            live['shiny']=identity['shiny']
            if position & 1:  # opponent
                result['battle']['enemies'].append(live)
                for enemy in result['battle']['enemy_party']:
                    if enemy['slot']==live['party_slot']:
                        enemy.update(hp=live['hp'],max_hp=live['max_hp'],active=True,ability_id=live['ability_id'],shiny=live['shiny'],stats=live['stats'],stages=live['stages'],status_code=live['status_code'],types=live['types'])
                        for j,m in enumerate(enemy['moves']):m['current_pp']=game.read8(mon+36+j)
                continue
            result['battle']['allies'].append(live)
            party_slot = game.read16(syms["gBattlerPartyIndexes"] + 2 * battler)
            if party_slot < count:
                mon = syms["gBattleMons"] + 0x58 * battler
                result["party"][party_slot].update(hp=game.read16(mon + 0x28),
                                                   max_hp=game.read16(mon + 0x2C), hp_source="battle",
                                                   status=status_name(game.read32(mon + 0x4C), game.read16(mon + 0x28)))
                result['party'][party_slot].update(stats=live['stats'],stages=live['stages'],types=live['types'],status_code=live['status_code'],ability_id=live['ability_id'])
                for j, move in enumerate(result['party'][party_slot]['moves']):
                    move['current_pp'] = game.read8(mon+36+j)
        from .battle_conditions import move_blockers
        b=result['battle']
        for side,opposite in [('allies','enemies'),('enemies','allies')]:
            for live in b[side]:
                live['imprisoned_moves']=sorted({a['id'] for foe in b[opposite] if foe.get('hp',0)>0 and foe.get('status3',0)&(1<<13) for a in foe['moves']})
                for attack in live['moves']:
                    attack['unusable_reasons']=move_blockers(live,attack);attack['usable']=not attack['unusable_reasons']
                rows=result['party'] if side=='allies' else b['enemy_party']
                matched=next((m for m in rows if m['uid']==live['uid'] and m['slot']==live['party_slot']),None)
                if matched:
                    maximums={a['id']:a.get('max_pp',a.get('pp',0)) for a in matched['moves']}
                    matched['moves']=[dict(a,max_pp=maximums.get(a['id'],a.get('pp',0))) for a in live['moves']]
                    for key in ('held_item','disabled_move','encored_move','encore_turns','taunt_turns','last_move','choice_move','status2','status3','imprisoned_moves'):matched[key]=live[key]
                    for j,attack in enumerate(matched['moves']):
                        attack['unusable_reasons']=move_blockers(matched,attack);attack['usable']=not attack['unusable_reasons']
        pointer=battle_struct(game,syms)
        if 0x02000000<=pointer<0x02040000-0xd8:
            slot=game.read8(pointer+adapter(game.root).memory.next_party+1)+1
            if any(m['slot']==slot and m.get('hp',0)>0 for m in b['enemy_party']):b['next_enemy_slot']=slot
        result['battle']['telemetry_valid']=live_valid and bool(result['battle']['enemies'])
        result['telemetry_valid'] &= battle_control_ready(result['battle'],result['controls'])
    return result


def battle_control_ready(battle, controls):
    """Party selection is valid before the active battler has been replaced.

    The engine updates party indexes while the old BattleMon is still loaded.
    Reject that live record, but let the verified party-menu task complete the
    selection. Combat actions still require fully matched active identities.
    """
    if battle['telemetry_valid']:
        return True
    tasks = {task['name'] for task in controls.get('tasks', [])}
    selecting = controls.get('callback') == 'CB2_UpdatePartyMenu' and bool(
        tasks & {'Task_HandleChooseMonInput', 'Task_HandleSelectionMenuInput'})
    return bool(battle.get('enemies')) and selecting
