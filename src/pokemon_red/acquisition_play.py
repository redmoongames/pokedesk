"""Game-button actions for an isolated starter journey, owned by its worker."""
from .game_layout import save_block,flags_offset,vars_offset,hoenn
from pathlib import Path
import json
import hashlib
import os
import time
import uuid
from .engine import BUTTONS
from .telemetry import read_state, read_map, read_controls, read_decision, symbols, decode_text
from .training import path_to
from .mechanics import ranked_attacks
from .catalog import species
from .persistence import sync_directory
from .acquisition import write_json
from .capture import catch_probability, CapturePolicy

class AcquisitionAttention(RuntimeError):pass
class JobPaused(Exception):pass

class Player:
    def __init__(self,game,worker):
        self.g=game;self.w=worker;self.learning=None;self.scope='journey';self.capture_target=None

    def state(self):return read_state(self.g)
    def tasks(self,s=None):return {t['name'] for t in (s or self.state())['controls']['tasks']}
    def flag(self,n):
        sb=save_block(self.g,1)
        return bool(self.g.read8(sb+flags_offset(self.g)+n//8)&(1<<(n%8)))
    def var(self,n):
        sb=save_block(self.g,1)
        return self.g.read16(sb+vars_offset(self.g)+2*(n-0x4000))
    def text(self):return decode_text(self.g.read_bytes(symbols(self.g.root)['gStringVar4'],700))

    def advance(self,frames=12,mask=0):
        guard=getattr(self.w,'before_frame',None)
        for _ in range(frames):
            if guard:guard()
            keys=mask
            if self.learning:
                self.learning.poll(self.g,read_decision(self.g))
                if self.learning.owns_input:keys=self.learning.mask
            self.g.advance(1,keys)
            self.w.heartbeat()

    def tap(self,key,frames=2,wait=18):
        self.advance(frames,BUTTONS[key]);self.advance(wait)

    def checkpoint(self,name,*,permanent=False):
        folder=self.g.root/'checkpoints'/name
        if not permanent:
            self.g.save_to(folder)
            write_json(folder/'metadata.json',dict(name=name,created_at=time.time(),frame=self.g.frame,state=self.state()))
            return folder
        if folder.exists():
            manifest=json.loads((folder/'manifest.json').read_text())
            if any(hashlib.sha256((folder/n).read_bytes()).hexdigest()!=digest for n,digest in manifest.items()):
                raise AcquisitionAttention('Повреждён защищённый checkpoint: '+name)
            return folder
        pending=folder.with_name('.'+name+'-'+uuid.uuid4().hex)
        self.g.save_to(pending)
        write_json(pending/'metadata.json',dict(name=name,created_at=time.time(),frame=self.g.frame,state=self.state()))
        write_json(pending/'manifest.json',{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in pending.iterdir() if p.is_file()})
        for path in pending.iterdir():path.chmod(0o444)
        pending.chmod(0o555)
        os.rename(pending,folder);sync_directory(folder.parent)
        return folder

    def persist(self):self.g.save_to(self.g.root/'Data')

    def settle(self,limit=6000,button='B'):
        for _ in range(limit//18):
            s=self.state();c=s['controls']
            if s['in_battle']:return s
            if c['callback']=='CB2_Overworld' and not c['field_locked'] and not c['moving']:
                self.advance(30);fresh=self.state()
                if not fresh['controls']['field_locked']:return fresh
            self.tap(button,wait=16)
        raise AcquisitionAttention('Диалог или сцена не завершились: '+self.text())

    def cut_tree(self,name,tree):
        from .field_actions import CutRuntime
        runtime=CutRuntime(self.g,dict(map=name,point=[tree['x'],tree['y']],local_id=tree['local_id']),self.state()['party'])
        try:
            while not runtime.poll(self.g):self.advance(1,runtime.mask)
            self.w.event('field_cut_completed',dict(map=name,point=[tree['x'],tree['y']],provider=runtime.provider))
        finally:runtime.cancel();self.g.advance(0,0)

    def go(self,goal,*,allow_trigger=False,encounters='escape'):
        from .walking_route import WalkingRoute
        from .field_tools import party_cut
        from .movement import safe_segment,safe_step,movement_mode,WalkSegment
        from .telemetry import read_walk_state
        goal=tuple(goal);source=self.state()['map']['name'];failures=0;route=None
        for _ in range(1600):
            s=self.state();c=s['controls']
            if s['in_battle']:
                if encounters=='local':return
                route=None
                self.battle('catch' if encounters=='catch' and len(s['party'])<2 else 'fight' if encounters=='fight' else 'escape');continue
            if s['map']['name']!=source:raise AcquisitionAttention('Неожиданный переход во время ходьбы')
            if c['field_locked'] or c['callback']!='CB2_Overworld':
                if not c.get('message_box'):
                    self.advance(12);continue
                raise AcquisitionAttention('Неожиданный диалог по пути: '+self.text())
            here=(s['position']['x'],s['position']['y'])
            if here==goal:
                if c['moving']:self.advance(6);continue
                return
            if c['moving']:self.advance(6);continue
            grid=party_cut(read_map(self.g),s['party'])
            if allow_trigger:grid=dict(grid,script_triggers=[p for p in grid.get('script_triggers',[]) if tuple(p)!=goal])
            try:
                if route is None or not route.advance(here) or not route.validate(grid):
                    route=WalkingRoute(here,path_to(grid,here,goal));route.validate(grid)
                remaining=route.remaining;next_point=remaining[0]
            except RuntimeError as e:raise AcquisitionAttention(str(e)) from e
            tree=next((o for o in grid.get('objects',[]) if o.get('graphics_id')==95 and (o['x'],o['y'])==next_point),None)
            if tree:
                if not grid.get('cut_enabled'):raise AcquisitionAttention('Для дерева нужен Cut и Cascade Badge')
                self.cut_tree(source,tree);route=None;continue
            straight=safe_segment(grid,here,remaining)
            precise=not straight
            if straight or safe_step(grid,here,next_point):
                endpoint=straight[-1] if straight else next_point
                mode=movement_mode(read_walk_state(self.g),len(straight)) if straight else 'walk'
                segment=WalkSegment(source,here,endpoint,self.g.frame,mode=mode,precision=precise)
                try:
                    for _ in range(len(straight)*40+121):
                        mask,result=segment.next(read_walk_state(self.g))
                        if result:break
                        self.advance(1,mask)
                    else:raise AcquisitionAttention('Превышен лимит прямого участка')
                finally:self.g.advance(0,0)
                if result['reason'] in ('obstacle','stalled'):
                    failures+=1;route=None;self.advance(12)
                    if failures>8:raise AcquisitionAttention('Путь перекрыт: '+str(here))
                elif result['reason'] not in ('reached','battle'):
                    raise AcquisitionAttention('Ходьба прервана: '+result['reason'])
                else:failures=0
                continue
            if not allow_trigger:raise AcquisitionAttention('Шаг больше не разрешён: '+str(next_point))
            dx,dy=next_point[0]-here[0],next_point[1]-here[1]
            key={(1,0):'RIGHT',(-1,0):'LEFT',(0,1):'DOWN',(0,-1):'UP'}[(max(-1,min(1,dx)),max(-1,min(1,dy)))]
            self.tap(key,frames=8,wait=16)
            new=self.state();now=(new['position']['x'],new['position']['y'])
            failures=failures+1 if now==here and not new['in_battle'] else 0
            if failures>8:raise AcquisitionAttention('Путь перекрыт: '+str(here))
        raise AcquisitionAttention('Превышен лимит ходьбы')

    def transition(self,key,destination,*,encounters='escape'):
        source=self.state()['map']['name']
        for _ in range(18):
            s=self.state()
            if s['in_battle']:self.battle(encounters);continue
            if s['map']['name']==destination:
                self.advance(90)
                return self.state()
            if s['map']['name']!=source:raise AcquisitionAttention('Переход открыл другую карту')
            self.tap(key,frames=16 if hoenn(self.g) else 8,wait=24)
        raise AcquisitionAttention('Не сработал переход в '+destination)

    def save_game(self):
        """Issue the game's SAVE, then export flash plus an exact checkpoint."""
        s=self.state()
        if s['in_battle'] or s['controls']['field_locked']:raise AcquisitionAttention('Для обычного SAVE нужен свободный мир')
        counter=self.g.read32(symbols(self.g.root)['gSaveCounter'])
        self.tap('START',wait=60)
        for _ in range(40):
            s=self.state();c=s['controls']
            if 'Task_StartMenuHandleInput' not in self.tasks(s):self.advance(12);continue
            if 4 not in c['start_order']:raise AcquisitionAttention('В меню нет SAVE')
            target=c['start_order'].index(4)
            if c['start_cursor']==target:self.tap('A',wait=120);break
            self.tap('DOWN' if c['start_cursor']<target else 'UP')
        else:raise AcquisitionAttention('Не открылось меню сохранения')
        saved=False
        for _ in range(120):
            s=self.state();text=self.text()
            if 'saved the game' in text:saved=True
            if saved and self.g.read32(symbols(self.g.root)['gSaveCounter'])!=counter and not s['controls']['field_locked'] and 'Task_StartMenuHandleInput' not in self.tasks(s):
                self.persist();return
            self.tap('A',wait=24)
        raise AcquisitionAttention('Игра не подтвердила SAVE')

    def grid(self,cursor,target):
        if cursor==target:self.tap('A',wait=72);return
        if cursor%2!=target%2:self.tap('RIGHT' if target%2 else 'LEFT')
        else:self.tap('DOWN' if target//2 else 'UP')

    def ball_count(self):
        from .player_inventory import read_player_inventory
        return sum(r['quantity'] for r in read_player_inventory(self.g)['items'] if r['pocket']=='balls' and r['id']==4)

    def bag(self,ball_id=4):
        if hoenn(self.g):
            from .hoenn import bag_step
            return bag_step(self,ball_id)
        c=read_controls(self.g);tasks=self.tasks(dict(controls=c));sy=symbols(self.g.root)
        pocket=self.g.read16(sy['gBagMenuState']+6)
        if 'Task_BagMenu_HandleInput' in tasks:
            if pocket!=2:self.tap('RIGHT' if pocket<2 else 'LEFT',wait=32);return
            # Pocket 2: use the verified item slot, never an arbitrary item or
            # a guessed global cursor. Ordinary, Great and Ultra share this UI.
            sb=save_block(self.g,1)
            from .player_inventory import read_player_inventory
            selected=next((r for r in read_player_inventory(self.g)['items'] if r['pocket']=='balls' and r['id']==ball_id and r['quantity']>0),None)
            if selected is None:raise AcquisitionAttention('Выбранного покебола нет в сумке')
            cursor=self.g.read16(sy['gBagMenuState']+8+2*pocket)+self.g.read16(sy['gBagMenuState']+14+2*pocket)
            target=selected['slot'];self.tap('A' if cursor==target else 'UP' if cursor>target else 'DOWN',wait=72 if cursor==target else 24)
        elif 'Task_FieldItemContextMenuHandleInput' in tasks:
            if c['menu_cursor']!=0:self.tap('UP')
            else:self.tap('A',wait=72)
        else:self.advance(12)

    def battle(self,intent='escape',*,trainer=False):
        if intent=='catch' and getattr(self,'capture_policy',None)=='venusaur':
            from .wild_capture import CaptureBattle
            return CaptureBattle(self).run()
        start=self.g.frame;armed=False;root_checkpoint=None;retry=0;initial_balls=None;throw_pending=False;before_count=len(self.state()['party']);caught=False
        while self.g.frame-start<42000:
            s=self.state();c=s['controls'];b=s.get('battle') or {};tasks=self.tasks(s)
            if not s['in_battle']:
                if c['callback']=='CB2_Overworld' and (hoenn(self.g) or not c['field_locked']):
                    return len(s['party'])>before_count or caught
                if c['callback']=='CB2_NamingScreen':raise AcquisitionAttention('Неожиданно открылся ввод имени')
                self.tap('B',wait=18);continue
            armed |= c['callback'] in ('CB2_BagMenuRun','CB2_BagMenu') or c['controllers'][0] in ('HandleInputChooseAction','HandleInputChooseMove')
            if not armed:
                self.tap('A',wait=18);continue
            if b.get('flags',0)&8 and not trainer:raise AcquisitionAttention('Неожиданный бой с тренером')
            enemies=b.get('enemies',[]);enemy=enemies[0] if enemies else None
            if intent=='catch' and getattr(self,'capture_policy',None)=='venusaur':
                from .wild_capture import CaptureBattle
                return CaptureBattle(self).run()
            if intent=='escape' and enemy:
                from .battle_conditions import escape_blockers
                ally=next(iter(b.get('allies',[])),None)
                if escape_blockers(s,ally):intent='fight'
            if intent=='catch' and enemy and root_checkpoint is None:
                root_checkpoint=self.g.capture_save(metadata=False).state
                self.checkpoint('capture-'+uuid.uuid4().hex,permanent=True)
                initial_balls=self.ball_count()
            if intent=='catch' and root_checkpoint and b.get('outcome',0)==0 and (self.ball_count()==0 or throw_pending and self.ball_count()<initial_balls and c['controllers'][0]=='HandleInputChooseAction'):
                retry+=1
                if retry>1000:raise AcquisitionAttention('Ловля приостановлена: превышен лимит повторных попыток; встреча сохранена')
                self.g.restore_checkpoint(root_checkpoint);throw_pending=False;self.advance(1+retry*7%997);continue
            if b.get('outcome')==7:caught=True
            if b.get('outcome') in (2,9) and not trainer:raise AcquisitionAttention('Команда проиграла; прогресс и найденный Pokémon сохранены')
            if c['callback'] in ('CB2_BagMenuRun','CB2_BagMenu') or any('BagMenu' in t or 'ItemContextMenu' in t for t in tasks):
                self.bag();continue
            controller=c['controllers'][0]
            if controller=='HandleInputChooseAction':
                if intent=='catch':
                    if not enemy:self.advance();continue
                    probability=catch_probability(species(enemy['species_id'],self.g.root)['catch_rate'],enemy['hp'],enemy['max_hp'],status=enemy.get('status_code',0),level=enemy['level'])
                    decision=CapturePolicy().decide(probability['probability'],enemy['hp'])
                    self.w.event('capture_decision',dict(probability,**{k:v for k,v in decision.items() if k!='probability'},enemy_uid=enemy['uid'],ball_id=4,retry=retry))
                    self.grid(c['action_cursor'][0],1);throw_pending=True
                else:self.grid(c['action_cursor'][0],0 if intent=='fight' else 3)
            elif controller=='HandleInputChooseMove':
                if intent!='fight':self.tap('B');continue
                enemies=b.get('enemies',[]);allies=b.get('allies',[])
                mon=next((m for m in s['party'] if allies and m['slot']==allies[0]['party_slot']),None)
                rows=ranked_attacks(dict(mon or {},**(allies[0] if allies else {})),enemies[0],self.g.root) if mon and enemies else []
                if not rows:raise AcquisitionAttention('Нет доступной атаки; найденный Pokémon сохранён')
                self.grid(c['move_cursor'][0],rows[0][0])
            elif 'Task_HandleChooseMonInput' in tasks:
                living=next((m for m in s['party'] if m['hp']>0),None)
                if not living:raise AcquisitionAttention('Нет живого Pokémon для замены')
                self.tap('A' if c['party_cursor']==living['slot']-1 else 'DOWN')
            elif 'Task_HandleSelectionMenuInput' in tasks:
                if 1 not in c['party_actions']:raise AcquisitionAttention('Нет действия замены')
                desired=c['party_actions'].index(1);self.tap('A' if c['menu_cursor']==desired else 'DOWN' if c['menu_cursor']<desired else 'UP')
            else:
                # B advances battle messages and rejects only the expected
                # nickname prompt; planned move learning owns input per frame.
                self.tap('B' if intent=='catch' else 'A',wait=18)
        raise AcquisitionAttention('Бой не завершился за отведённое время')

    def heal(self):
        """Ensure HP, statuses and PP are restored; healthy calls send no input."""
        from .healing import recovery_reasons,HealingTelemetryError
        from .zones import zone_spec
        def needs_recovery(state):
            try:return recovery_reasons(state)
            except HealingTelemetryError as error:raise AcquisitionAttention(str(error)) from error
        state=self.state();controls=state['controls']
        if state.get('in_battle') or controls['callback']!='CB2_Overworld' or controls['field_locked']:
            raise AcquisitionAttention('Закрой меню и диалоги, дождись окончания перехода')
        if not needs_recovery(state):return False
        current=state['map']['name'];hub=next((h for h in zone_spec(self.g.root)['hubs'].values() if h['map']==current),None)
        self.go(tuple(hub['nurse']) if hub else (7,4));self.tap('UP');self.tap('A',wait=60)
        locked=False
        for _ in range(220):
            s=self.state();locked|=s['controls']['field_locked']
            if locked and not s['controls']['field_locked'] and not needs_recovery(s):return True
            self.tap('A',wait=24)
        raise AcquisitionAttention('Лечение не подтвердилось')
