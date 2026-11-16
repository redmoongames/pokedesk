"""Verified Cut interaction; input belongs to the game thread and is cancellable."""
import struct
from .engine import BUTTONS
from .telemetry import symbols,read_walk_state,read_learning_mon,read_field_badges
from .field_tools import knows

class FieldMismatch(RuntimeError):pass

def control(game,local_id):
    s=symbols(game.root);c=read_walk_state(game);tree=None
    for i in range(16):
        a=s['gObjectEvents']+i*36
        if game.read8(a)&1 and game.read8(a+8)==local_id and i!=game.read8(s['gPlayerAvatar']+5):
            tree=dict(x=game.read16(a+16)-7,y=game.read16(a+18)-7,graphics=game.read8(a+5))
    ctx=s['sGlobalScriptContext'];depth=game.read8(ctx)
    pointers=[game.read32(ctx+8)]+[game.read32(ctx+12+4*i) for i in range(min(depth,20))]
    from .game_layout import hoenn
    if hoenn(game):
        valid=any(s['S_CuttableTree']<=p<s['CannotUseCut'] for p in pointers)
        denied=any(s['CannotUseCut']<=p<s['UseCutPromptText'] for p in pointers)
    else:
        valid=any(s['EventScript_CutTree']<=p<s['EventScript_FldEffCut'] or s['EventScript_CutTreeDown']<=p<s['EventScript_CantCutTree'] for p in pointers)
        denied=any(s['EventScript_CantCutTree']<=p<s['Text_CutTreeDown'] for p in pointers)
    last=s.get('gSpecialVar_LastTalked',s.get('gSpecialVar_0x800F'))
    if last is None:raise FieldMismatch('Не найден адрес выбранного объекта')
    tasks=game.read_bytes(s['gTasks'],16*40)
    player=s['gObjectEvents']+game.read8(s['gPlayerAvatar']+5)*36
    yesno=s['Task_HandleYesNoInput'] if hoenn(game) else s['Task_YesNoMenu_HandleInput']
    menu=s['gMenu'] if hoenn(game) else 0x0203ade4
    return dict(c,tree=tree,cut_script=valid and not denied,last_talked=game.read16(last),facing=game.read8(player+24)&15,native=any(tasks[i*40+4] and (struct.unpack_from('<I',tasks,i*40)[0]&~1)==yesno for i in range(16)),cursor=game.read8(menu+2))

class CutRuntime:
    def __init__(self,game,args,party):
        name=args.get('map');point=args.get('point');local=args.get('local_id')
        if type(local) is not int or not isinstance(point,list) or len(point)!=2 or any(type(v) is not int for v in point):raise ValueError('Некорректное дерево')
        from .telemetry import read_map
        grid=read_map(game);self.graphics=grid.get('cut_graphics',95);self.badge=grid.get('cut_badge',2);tree=next((o for o in grid['objects'] if o.get('graphics_id')==self.graphics and o['local_id']==local and [o['x'],o['y']]==point),None)
        self.map=name;self.point=tuple(point);self.local_id=local;self.mask=0;self.phase='facing';self.frame=game.frame;self.last_frame=-1;self.last_pulse=game.frame;self.start=tuple(read_walk_state(game)['position']);self.provider=next((m['uid'] for m in party if knows(m,15)),None)
        if name!=grid['name'] or not tree or not self.provider or self.badge not in read_field_badges(game):raise ValueError('Нужны дерево на текущей карте, Cut в команде и соответствующий значок')
        dx,dy=point[0]-self.start[0],point[1]-self.start[1]
        if abs(dx)+abs(dy)!=1:raise ValueError('Для Cut нужно стоять рядом с деревом')
        self.button,self.direction={(0,1):('DOWN',1),(0,-1):('UP',2),(-1,0):('LEFT',3),(1,0):('RIGHT',4)}[dx,dy]
    def cancel(self):self.mask=0
    def pulse(self,key,frame):
        if frame-self.last_pulse<12:return 0
        self.last_pulse=frame;return BUTTONS[key]
    def poll(self,game):
        if self.last_frame==game.frame:return False
        self.last_frame=game.frame;self.mask=0;c=control(game,self.local_id)
        if c['map']!=self.map or tuple(c['position'] or ())!=self.start or c['in_battle'] or c['battle_pending']:raise FieldMismatch('Игра изменилась во время Cut')
        if game.frame-self.frame>2400:raise FieldMismatch('Дерево не подтвердило срубание за отведённое время')
        if self.badge not in read_field_badges(game):raise FieldMismatch('Нет значка для Cut')
        if self.phase=='facing':
            mon=read_learning_mon(game,self.provider)
            if not mon or not knows(mon,15):raise FieldMismatch('Pokémon с Cut больше нет в команде')
            if not c['open'] or not c['tree'] or c['tree']['graphics']!=self.graphics or (c['tree']['x'],c['tree']['y'])!=self.point:raise FieldMismatch('Объект или экран изменился перед Cut')
            if c['facing']!=self.direction:self.mask=self.pulse(self.button,game.frame)
            elif not c['moving']:
                self.mask=self.pulse('A',game.frame)
                if self.mask:self.phase='awaiting'
            return False
        if c['open'] and not c['moving'] and not c['tree']:
            return True
        if not c['open']:
            if not c['cut_script'] or c['last_talked']!=self.local_id:raise FieldMismatch('Открылся другой диалог вместо подтверждённого дерева Cut')
            self.phase='cutting'
            if c['native'] and c['cursor'] not in (0,1):raise FieldMismatch('Неизвестный курсор подтверждения Cut')
            self.mask=self.pulse('UP' if c['native'] and c['cursor']==1 else 'A',game.frame)
        elif self.phase=='cutting' and c['tree']:raise FieldMismatch('Cut завершился, но дерево осталось')
        return False
