"""Verified, cancellable field Teleport. Ordinary buttons; no game RAM writes."""
from functools import lru_cache
import json,re
from .engine import BUTTONS
from .field_tools import knows
from .field_actions import FieldMismatch
from .telemetry import maps,symbols,read_controls,read_walk_state,read_learning_mon,read_field_teleport
from .zones import zone_spec
from .editions import reference_path,edition
from .game_layout import hoenn

OUTDOOR_TYPES={1,2,3,6}
TELEPORT_ACTION=25  # CURSOR_OPTION_FIELD_MOVES (18) + FIELD_MOVE_TELEPORT (7)
REASONS=dict(unknown_clinic='Для этого Center нет проверенной точки Teleport',unavailable_state='Teleport сейчас недоступен',map_forbidden='Из этой локации Teleport недоступен',wrong_destination='Teleport ведёт в другой Center',no_provider='В команде нет Pokémon с Teleport',already_there='Мы уже у нужного Center',destination_changed='Точка Teleport изменилась',provider_changed='Pokémon с Teleport изменился',action_missing='В меню нет Teleport',game_denied='Игра не разрешила Teleport')

@lru_cache(maxsize=8)
def destinations(root):
    constants={'MAP_'+re.sub(r'(?<=[a-z])(?=[A-Z])','_',name).upper():name for name in maps(root).values()}
    rows=json.loads(reference_path(root,'heal_locations.json').read_text())['heal_locations'];result={}
    for key,hub in zone_spec(root)['hubs'].items():
        if edition(root).family=='hoenn':
            town=hub['map'].split('_')[0];record=next((r for r in rows if constants.get(r['map'])==town),None)
            if record:result[key]=dict(map=town,point=[record['x'],record['y']],warp_id=-1)
            continue
        record=next((r for r in rows if constants.get(r['respawn_map'])==hub['map']),None)
        if record:result[key]=dict(map=constants[record['map']],point=[record['x'],record['y']],warp_id=-1)
    return result

def offer(state,clinic,root):
    """Pure preflight; outside battle PP are not consumed/required by FireRed."""
    destination=destinations(root).get(clinic)
    def denied(reason):return dict(teleported=False,reason=reason,clinic=clinic,destination=destination)
    if not destination:return denied('unknown_clinic')
    control=state.get('controls',{})
    if not state.get('ready') or state.get('in_battle') or control.get('callback')!='CB2_Overworld' or control.get('field_locked') or control.get('moving'):return denied('unavailable_state')
    if (state.get('field_teleport') or {}).get('map_type') not in OUTDOOR_TYPES:return denied('map_forbidden')
    if state['field_teleport'].get('landing')!=destination:return denied('wrong_destination')
    position=state.get('position') or {}
    if state.get('map',{}).get('name')==destination['map'] and [position.get('x'),position.get('y')]==destination['point']:return denied('already_there')
    provider=next((m for m in state.get('party',[]) if knows(m,100)),None)
    if not provider:return denied('no_provider')
    return dict(teleported=True,clinic=clinic,destination=destination,pokemon_uid=provider['uid'])

def control(game):
    s=symbols(game.root);c=read_controls(game);w=read_walk_state(game)
    if hoenn(game):
        task=next((t for t in c['tasks'] if (game.read32(s['gTasks']+40*t['id'])&~1)==s['sub_808AB34']),None)
        return dict(c,walk=w,fading=bool(game.read8(s['gPaletteFade']+7)&0x80),teleport=read_field_teleport(game),post_callback=game.read32(s['gPostMenuFieldCallback'])&~1,field_callback=game.read32(s['gFieldCallback'])&~1,field_move=task['data'][11] if task else None,field_selected=game.read8(s['gLastFieldPokeMenuOpened']))
    ptr=game.read32(s['sPartyMenuInternal'])
    return dict(c,walk=w,fading=bool(game.read8(s['gPaletteFade']+7)&0x80),teleport=read_field_teleport(game),post_callback=game.read32(s['gPostMenuFieldCallback'])&~1,field_callback=game.read32(s['gFieldCallback2'])&~1,field_move=game.read16(ptr+0x218) if 0x02000000<=ptr<0x02040000-0x238 else None)

class TeleportRuntime:
    action='teleport'
    def __init__(self,game,proposal,state):
        self.provider=proposal['pokemon_uid'];self.clinic=proposal['clinic'];self.destination=proposal['destination'];self.map=state['map']['name'];self.start=[state['position']['x'],state['position']['y']]
        self.phase='open';self.mask=0;self.frame=game.frame;self.last_frame=-1;self.last_pulse=game.frame-12;self.invalid_since=None;self.reason=None;self.confirmed=False;self.cancelled=False
    def cancel(self):self.mask=0;self.cancelled=True
    def result(self):return dict(teleported=self.confirmed,clinic=self.clinic,destination=self.destination,pokemon_uid=self.provider,reason=self.reason)
    def pulse(self,key,frame):
        if frame-self.last_pulse<12:return 0
        self.last_pulse=frame;return BUTTONS[key]
    def fallback(self,reason):self.reason=reason;self.phase='closing';self.mask=0
    def poll(self,game):
        if self.cancelled:self.mask=0;return False
        if self.last_frame==game.frame:return False
        self.last_frame=game.frame;self.mask=0;c=control(game);w=c['walk'];tasks={t['name'] for t in c['tasks']}
        if game.frame-self.frame>3600:raise FieldMismatch('Teleport не подтвердил завершение за отведённое время')
        if w['in_battle'] or w['battle_pending']:
            if self.confirmed:raise FieldMismatch('Начался бой после подтверждения Teleport')
            self.reason='unavailable_state';return True
        if self.phase=='direct':
            s=symbols(game.root)
            if c['post_callback']==s['FieldCallback_Teleport'] and c['field_callback']==s['FieldCallback_PrepareFadeInFromMenu'] and c.get('field_move')==8:
                mon=read_learning_mon(game,self.provider)
                if not mon or c.get('field_selected')!=mon['slot']-1:raise FieldMismatch('Для Teleport выбран другой Pokémon')
                self.phase='warping';self.confirmed=True
            else:return False
        if c['fading']:return False
        if self.phase=='warping':
            if w['open'] and not w['moving']:
                if w['map']==self.destination['map'] and list(w['position'] or [])==self.destination['point']:return True
                if w['map']!=self.map or list(w['position'] or [])!=self.start:raise FieldMismatch('Teleport прибыл не в подтверждённую точку')
            return False
        if self.phase=='closing':
            if w['open'] and not w['moving']:
                if w['map']!=self.map or list(w['position'] or [])!=self.start:raise FieldMismatch('Во время отмены Teleport изменилась позиция')
                return True
            if c['callback']=='CB2_UpdatePartyMenu' or 'Task_StartMenuHandleInput' in tasks:self.mask=self.pulse('B',game.frame)
            elif c['callback']=='CB2_Overworld' and c['field_locked']:raise FieldMismatch('Открылся посторонний диалог во время отмены Teleport')
            return False
        meta=c['teleport'] or {}
        if meta.get('landing')!=self.destination or meta.get('map_type') not in OUTDOOR_TYPES:self.fallback('destination_changed');return False
        if w['ready'] and (w['map']!=self.map or list(w['position'] or [])!=self.start):raise FieldMismatch('Игра переместилась до применения Teleport')
        mon=read_learning_mon(game,self.provider)
        if not mon or not mon.get('checksum_valid',True):
            if self.invalid_since is None:self.invalid_since=game.frame
            if game.frame-self.invalid_since>120:raise FieldMismatch('Не восстановились данные Pokémon для Teleport')
            return False
        self.invalid_since=None
        if not knows(mon,100):self.fallback('provider_changed');return False
        if self.phase=='open':
            if w['open'] and not w['moving']:
                self.mask=self.pulse('START',game.frame)
                if self.mask:self.phase='start_menu'
        elif self.phase=='start_menu':
            if 'Task_StartMenuHandleInput' in tasks:
                if next(t for t in c['tasks'] if t['name']=='Task_StartMenuHandleInput')['data'][0]!=1:return False
                if 1 not in c['start_order']:self.fallback('action_missing');return False
                target=c['start_order'].index(1);cursor=c['start_cursor']
                self.mask=self.pulse('A' if cursor==target else 'DOWN' if cursor<target else 'UP',game.frame)
                if self.mask==BUTTONS['A']:self.phase='party'
        elif self.phase=='party':
            # A can be ignored while the party UI finishes opening. Advance only
            # after the engine acknowledges it with the selection-menu task.
            if 'Task_HandleSelectionMenuInput' in tasks:
                self.phase='options'
            elif 'Task_HandleChooseMonInput' in tasks:
                if c['party_action']!=0:raise FieldMismatch('Открыт другой режим команды вместо полевого Teleport')
                target=mon['slot']-1;cursor=c['party_cursor']
                self.mask=self.pulse('A' if cursor==target else 'RIGHT' if cursor==0 else 'LEFT' if target==0 else 'DOWN' if cursor<target else 'UP',game.frame)
        elif self.phase=='options':
            if 'Task_HandleSelectionMenuInput' in tasks:
                if c['party_action']!=0 or c['party_cursor']!=mon['slot']-1:raise FieldMismatch('Для Teleport выбран другой Pokémon или режим команды')
                if TELEPORT_ACTION not in c['party_actions']:self.fallback('action_missing');return False
                target=c['party_actions'].index(TELEPORT_ACTION);cursor=c['menu_cursor']
                if not 0<=cursor<len(c['party_actions']):raise FieldMismatch('Некорректный курсор полевого приёма')
                self.mask=self.pulse('A' if cursor==target else 'DOWN' if cursor<target else 'UP',game.frame)
                if self.mask==BUTTONS['A']:self.phase='direct' if hoenn(game) else 'prompt'
        elif self.phase=='prompt':
            if 'Task_CancelAfterAorBPress' in tasks:self.fallback('game_denied');return False
            if 'Task_HandleFieldMoveExitAreaYesNoInput' in tasks:
                s=symbols(game.root)
                if c['post_callback']!=s['FieldCallback_Teleport'] or c['field_callback']!=s['FieldCallback_PrepareFadeInFromMenu'] or c['field_move']!=7 or c['party_cursor']!=mon['slot']-1:raise FieldMismatch('Подтверждение относится к другому полевому действию')
                if c['menu_cursor'] not in (0,1):raise FieldMismatch('Неизвестный курсор подтверждения Teleport')
                self.mask=self.pulse('A' if c['menu_cursor']==0 else 'UP',game.frame)
                if self.mask==BUTTONS['A']:self.phase='warping';self.confirmed=True
        if c['callback'] in ('CB2_SetUpPSS','CB2_RunPokemonSummaryScreen'):raise FieldMismatch('Вместо Teleport открылся Summary')
        return False
