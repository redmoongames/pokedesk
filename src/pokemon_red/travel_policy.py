"""Explicit, session-scoped consent for identifiable ordinary trainer encounters."""
from .game_layout import main_flags
from .game_layout import save_block,flags_offset,vars_offset,hoenn
import struct
from .telemetry import symbols,maps,address_names

UNSUPPORTED=1|2|0x40|0x80|0x200

def eligible_trainers(grid):
    return [t for t in grid.get('trainers',[]) if t.get('trainer_type')==1 and t.get('trainer_id') is not None and t.get('script_kind',0)==0]

def trainer_grid(grid,allowed):
    ids=set(allowed)
    return dict(grid,trainers=[dict(t,defeated=True) if t in eligible_trainers(grid) and t['trainer_id'] in ids else t for t in grid.get('trainers',[])])


def guard(game,policy):
    if not policy or not policy['ids']:return dict(scene=False,battle=False)
    s=symbols(game.root);sb=save_block(game,1)
    if not 0x02000000<=sb<0x02040000-0x3d68:return dict(scene=False,battle=False)
    if maps(game.root).get(tuple(game.read_bytes(sb+4,2)))!=policy['map']:return dict(scene=False,battle=False)
    opponent=game.read16(s['gTrainerBattleOpponent_A']);allowed=opponent in policy['ids']
    flags=game.read32(s['gBattleTypeFlags']);battle=bool(main_flags(game)&2)
    if battle:return dict(scene=False,battle=allowed and bool(flags&8) and not bool(flags&UNSUPPORTED),trainer_id=opponent)
    if not game.read8(s['sLockFieldControls']):return dict(scene=False,battle=False)
    ctx=s['sGlobalScriptContext'];depth=min(20,game.read8(ctx));pointers=[game.read32(ctx+8)]+[game.read32(ctx+12+4*i) for i in range(depth)]
    # Match an actual permitted object's script range/return stack, not stale
    # opponent RAM left over after a previous fight.
    matched=any(lo<=p<hi for lo,hi in policy['ranges'] for p in pointers)
    tasks=game.read_bytes(s['gTasks'],16*40);names=address_names(game.root)
    approach=any(tasks[i*40+4] and names.get(struct.unpack_from('<I',tasks,i*40)[0]&~1) in ('Task_RunTrainerSeeFuncList','Task_DestroyTrainerApproachTask') for i in range(16))
    local=game.read16(s.get('gSpecialVar_LastTalked',s.get('gSpecialVar_0x800F')))
    matched |= any(lo<=p<hi for lo,hi in policy.get('common_ranges',[]) for p in pointers) and local in policy['locals']
    return dict(scene=bool(allowed and (matched or approach and local in policy['locals'])),battle=False,trainer_id=opponent)


def make_policy(game,grid,ids):
    if not isinstance(ids,list) or len(ids)>64 or any(type(i) is not int for i in ids):raise ValueError('Некорректный список тренеров')
    objects=[t for t in eligible_trainers(grid) if t['trainer_id'] in ids]
    if set(ids)!={t['trainer_id'] for t in objects}:raise ValueError('Разрешены только проверенные одиночные NPC текущей карты')
    addresses=sorted(set(symbols(game.root).values()));ranges=[]
    for t in objects:
        start=t['script'];end=next((a for a in addresses if a>start),start+1);ranges.append([start,min(end,start+4096)])
    names=symbols(game.root);common=[]
    for label in ('EventScript_StartTrainerBattle','EventScript_DoTrainerBattleFromApproach','EventScript_TryDoNormalTrainerBattle','EventScript_EndTrainerBattle','EventScript_EndTrainerBattleContinueScript'):
        if label not in names:continue
        lo=names[label];common.append([lo,next((a for a in addresses if a>lo),lo+1)])
    if 'EventScript_DoTrainerBattle' in names and 'EventScript_EndTrainerBattleContinueScript' in names:common.append([names['EventScript_DoTrainerBattle'],names['EventScript_EndTrainerBattleContinueScript']])
    elif hoenn(game) and 'EventScript_DoTrainerBattle' in names and 'EventScript_EndTrainerBattle' in names:common.append([names['EventScript_DoTrainerBattle'],names['EventScript_EndTrainerBattle']])
    return dict(common_ranges=common,map=grid['name'],ids=sorted(set(ids)),locals=[t['local_id'] for t in objects],ranges=ranges)
