"""Ruby/Sapphire engine adapter producing the shell's canonical menu model.

Offsets and phases follow the pinned pokeruby source and verified Rev 2 ROMs.
Shared controllers consume these phases without depending on the game's UI.
"""
from functools import lru_cache
import json
from .editions import reference_path

@lru_cache(maxsize=128)
def map_names(root):
    groups=json.loads(reference_path(root,'map_groups.json').read_text())
    return {(g,n):name for g,key in enumerate(groups['group_order']) for n,name in enumerate(groups[key])}

def capture_summary(game):
    from .telemetry import symbols,decode_text
    sy=symbols(game.root);sb1=sy['gSaveBlock1'];sb2=sy['gSaveBlock2']
    info=dict(ready=False,player=None,money=None,map=None,position=None,pokedex=dict(caught=0,seen=0,total=386),play_time=None)
    first=game.read_bytes(sb1,6);second=game.read_bytes(sb2,0x90)
    money=game.read32(sb1+0x490);name=decode_text(second[:8]);key=tuple(first[4:6]);place=map_names(game.root).get(key)
    if not name or money>999999 or place is None or not 0x08000000<=game.read32(sy['gMapHeader'])<0x0a000000:return info
    mask=(1<<386)-1
    info.update(ready=True,player=name,money=money,map=dict(group=key[0],number=key[1],name=place),
        position=dict(x=int.from_bytes(first[:2],'little',signed=True),y=int.from_bytes(first[2:4],'little',signed=True),source='save_block'),
        pokedex=dict(caught=(int.from_bytes(second[0x28:0x5c],'little')&mask).bit_count(),seen=(int.from_bytes(second[0x5c:0x90],'little')&mask).bit_count(),total=386),
        play_time=dict(hours=int.from_bytes(second[0xe:0x10],'little'),minutes=second[0x10],seconds=second[0x11]))
    return info

# Canonical UI phases describe verified RS states, never guessed FR offsets.
NAMES={'sub_80712B4':'Task_StartMenuHandleInput','sub_809DE44':'CB2_SetUpPSS','sub_809D844':'CB2_RunPokemonSummaryScreen','Task_PokemonStorageSystem':'Task_PCMainMenu','sub_802C098':'HandleInputChooseAction','sub_802C2EC':'HandleInputChooseTarget','HandleAction_ChooseMove':'HandleInputChooseMove','sub_802CA60':'HandleMoveSwitching','CB2_PartyMenuMain':'CB2_UpdatePartyMenu','HandleBattlePartyMenu':'Task_HandleChooseMonInput','CB2_SummaryScreen':'CB2_RunPokemonSummaryScreen','CB2_ShowPokemonSummaryScreen':'CB2_SetUpPSS','StartMenuHandleInput':'Task_StartMenuHandleInput','Task_HandleYesNoInput':'Task_YesNoMenu_HandleInput','sub_80A3118':'CB2_BagMenuRun','sub_80A50C8':'Task_BagMenu_HandleInput','sub_80A5888':'Task_FieldItemContextMenuHandleInput','sub_80A6EB8':'Task_FieldItemContextMenuHandleInput','sub_80A6D98':'CB2_BagMenu','sub_8096B38':'CB2_PokeStorage','sub_8096884':'CB2_PokeStorage'}
def canonical_name(name):return NAMES.get(name,name)

NAMES.update({'HandleDefaultPartyMenu':'Task_HandleChooseMonInput',
    'HandlePartyMenuSwitchPokemonInput':'Task_HandleChooseMonInput',
    'sub_8089D94':'Task_HandleSelectionMenuInput',
    'Task_HandlePopupMenuInput':'Task_HandleSelectionMenuInput'})
NAMES['sub_8048AB4']='CB2_TradeMenu'
NAMES['CB2_SetUpReshowBattleScreenAfterMenu']='ReshowBattleScreenAfterMenu'
NAMES['RunTrainerSeeFuncList']='Task_RunTrainerSeeFuncList'

def party_controls(game,tasks):
    from .telemetry import symbols
    s=symbols(game.root);raw=game.read_bytes(s['gTasks'],640)
    def sprite_cursor(sprite):
        return game.read16(s['gSprites']+68*sprite+0x2e) if sprite<64 else 255
    switching=any((game.read32(s['gTasks']+40*t['id'])&~1)==s['HandlePartyMenuSwitchPokemonInput'] for t in tasks if t['id']>=0)
    task_id=game.read8(0x02001000) if switching else next((t['id'] for t in tasks if t['name'] in ('Task_HandleChooseMonInput','Task_HandleSelectionMenuInput')),255)
    cursor=sprite_cursor(raw[40*task_id+15]) if task_id<16 else 255
    actions=[]
    context=next((t for t in tasks if t['name']=='Task_HandleSelectionMenuInput'),None)
    if context:
        fn=game.read32(s['gTasks']+40*context['id'])&~1
        if fn==s['Task_HandlePopupMenuInput']:
            actions=([10,0,3],[11,0,3],[0,3])[min(2,context['data'][4])]
        else:
            # Canonical field actions: Cut=19, Teleport=25, etc.
            mapping={10:19,11:18,12:23,13:21,14:22,15:20,16:30,17:24,18:25,19:26,20:31,21:27,22:28,23:29}
            actions=[mapping.get(n,n) for n in game.read_bytes(s['sPokeMenuOptionsOrder'],min(8,game.read8(s['sPokeMenuOptionsNo'])))]
    return dict(party_cursor=cursor,party_cursor2=cursor,party_action=8 if switching else 0,party_actions=list(actions))

def read_controls(game):
    import struct
    from .telemetry import symbols,address_names
    s=symbols(game.root);names=address_names(game.root)
    def name(p):return names.get(p&~1,hex(p&~1))
    tasks=[];raw=game.read_bytes(s['gTasks'],640)
    for i in range(16):
        a=i*40
        if raw[a+4]:tasks.append(dict(id=i,name=name(struct.unpack_from('<I',raw,a)[0]),data=list(struct.unpack_from('<16h',raw,a+8))))
    cb=name(game.read32(s['gMain']+4));ptr=0x02000000
    storage=None
    if cb=='CB2_PokeStorage':
        phase=name(game.read32(ptr));state=game.read8(ptr+4)
        phases={'sub_8096C84':'Task_PokeStorageMain','sub_8097078':'Task_OnSelectedMon','sub_809746C':'Task_DepositMenu','sub_8097CC0':'Task_OnBPressed','sub_8097BA0':'Task_OnBPressed'}
        canonical=phases.get(phase)
        if canonical:tasks.append(dict(id=-1,name=canonical,data=[]))
        choose=game.read32(s['gUnknown_02038478'])
        storage=dict(state=2 if canonical=='Task_OnSelectedMon' and state==1 else state,mode=game.read8(ptr+5),area=game.read8(s['sBoxCursorArea']),cursor=game.read8(s['sBoxCursorPosition']),choose_box=game.read8(choose+0x23c) if 0x02000000<=choose<0x0203fd00 else None,exit_key='A' if phase=='sub_8097BA0' else 'B',phase=phase)
    script=s['sScriptContext1'];instr=game.read32(s['gBattlescriptCurrInstr'])
    from .field_recovery import poison_notification
    return dict(callback=cb,tasks=tasks,storage=storage,summary_mode=game.read8(0x02018008) if 'Summary' in cb else None,
        field_locked=bool(game.read8(s['sScriptContext2Enabled'])),field_recovery=poison_notification(game),message_box=game.read8(s['sMessageBoxMode']),
        field_script_native=name(game.read32(script+4)) if game.read8(script+1)==2 else None,moving=game.read8(s['gPlayerAvatar']+3),
        controllers=[name(game.read32(s['gBattlerControllerFuncs']+4*i)) for i in range(4)],
        action_cursor=list(game.read_bytes(s['gActionSelectionCursor'],4)),move_cursor=list(game.read_bytes(s['gMoveSelectionCursor'],4)),
        battle_script_opcode=game.read8(instr) if 0x08000000<=instr<0x0a000000 else -1,
        learn_move_state=game.read8(0x0201601a),move_to_learn=game.read16(s['gMoveToLearn']),
        **party_controls(game,tasks),
        menu_cursor=game.read8(s['gMenu']+2),yes_no_state=game.read8(s['gBattleCommunication']),yes_no_cursor=game.read8(s['gBattleCommunication']+1),
        player_fainted=bool(game.read32(s['gHitMarker'])&(1<<22)),player_party_slot=game.read16(s['gBattlerPartyIndexes'])+1,
        start_cursor=game.read8(s['sStartMenuCursorPos']),start_order=[{0:0,1:1,2:2,3:7,4:3,5:4,6:5,7:6}.get(n,n) for n in game.read_bytes(s['sCurrentStartMenuActions'],min(10,game.read8(s['sNumStartMenuActions'])))])

def read_decision(game):
    from .telemetry import symbols
    s=symbols(game.root);cb=game.read32(s['gMain']+4)&~1;instr=game.read32(s['gBattlescriptCurrInstr'])
    if cb==s['BattleMainCB2'] and 0x08000000<=instr<0x0a000000 and game.read8(instr) in (0x5a,0x5b) and game.read8(0x0201601a)==1:
        return dict(code='move_choice_required',party_slot=game.read8(0x02016018)+1,move_id=game.read16(s['gMoveToLearn']),source='battle')
    if cb in (s.get('CB2_EvolutionSceneUpdate'),s.get('CB2_TradeEvolutionSceneUpdate')):
        for i in range(16):
            a=s['gTasks']+40*i
            if game.read8(a+4) and (game.read32(a)&~1)==s.get('Task_EvolutionScene') and game.read16(a+8)==21 and game.read16(a+24)==4:
                return dict(code='move_choice_required',party_slot=game.read16(a+32)+1,move_id=game.read16(s['gMoveToLearn']),source='evolution')
    return None

def read_learning_control(game):
    from .telemetry import symbols,address_names
    s=symbols(game.root);c=read_controls(game);cb=c['callback'];evo=None;summary=None
    for task in c['tasks']:
        if task['name']=='Task_EvolutionScene':
            d=task['data'];evo=dict(state=22 if d[0]==21 else d[0],pre=d[3],post=d[4],bits=d[5],learn_state=11 if d[8]==10 else d[8],yes=11 if d[9]==10 else d[9],no=10 if d[10]==9 else d[10],cancelled=d[11],slot=d[12]+1)
    if cb in ('CB2_SetUpPSS','CB2_RunPokemonSummaryScreen'):
        from .models import decode_mon
        pointer=0x02018000;mon=decode_mon(game.read_bytes(pointer+16,100),game.root)
        moves=[m['id'] for m in mon['moves']];moves += [0]*(4-len(moves));moves.append(game.read16(pointer+0x7c))
        summary=dict(mode=game.read8(pointer+8),stage=2 if any(t['name']=='sub_809E260' for t in c['tasks']) else 0,cursor=game.read8(pointer+0x79),moves=moves,uid=mon['uid'],party=game.read32(pointer)==s['gPlayerParty'],slot=game.read8(pointer+9)+1,return_callback=address_names(game.root).get(game.read32(pointer+4)&~1))
    instr=game.read32(s['gBattlescriptCurrInstr'])
    battle=dict(op=game.read8(instr) if 0x08000000<=instr<0x0a000000 else -1,state=game.read8(0x0201601a),slot=game.read8(0x02016018)+1) if cb=='BattleMainCB2' else None
    return dict(frame=game.frame,callback=cb,evo=evo,summary=summary,battle=battle,cursor=game.read8(s['gBattleCommunication']+1),move_id=game.read16(s['gMoveToLearn']),stable=cb=='CB2_Overworld' and not c['field_locked'])

def bag_step(player,ball_id):
    from .telemetry import symbols
    from .player_inventory import read_player_inventory
    from .acquisition_play import AcquisitionAttention
    game=player.g;s=symbols(game.root);c=read_controls(game);tasks={t['name'] for t in c['tasks']};pocket=game.read8(s['sCurrentBagPocket'])
    if 'Task_BagMenu_HandleInput' in tasks:
        if pocket!=1:player.tap('RIGHT' if pocket<1 else 'LEFT',wait=32);return
        selected=next((r for r in read_player_inventory(game)['items'] if r['pocket']=='balls' and r['id']==ball_id and r['quantity']>0),None)
        if selected is None:raise AcquisitionAttention('Выбранного покебола нет в сумке')
        a=s['gBagPocketScrollStates']+pocket*4;cursor=game.read8(a)+game.read8(a+1);target=selected['slot']
        player.tap('A' if cursor==target else 'UP' if cursor>target else 'DOWN',wait=72 if cursor==target else 24)
    elif 'Task_FieldItemContextMenuHandleInput' in tasks:
        cursor=game.read8(s['sPopupMenuSelection']);player.tap('A' if cursor==0 else 'UP',wait=72 if cursor==0 else 20)
    else:player.advance(12)
