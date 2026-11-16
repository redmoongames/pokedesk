"""Button-driven link trade. Only mGBA's serial cable transmits Pokémon."""
from collections import deque
from .engine import BUTTONS
from .telemetry import symbols
from .acquisition_play import Player,AcquisitionAttention
from .link import Cable
from .trade_adapters import layout,preflight

class LinkPlayer(Player):
    def state(self):
        s=super().state()
        if s.get('map',{}).get('name')=='TradeCenter' and s['controls']['callback']=='CB2_Overworld':
            sy=symbols(self.g.root);lid=self.g.read8(sy['gLocalLinkPlayerId'])
            if lid<2:
                entry=sy['gLinkPlayerObjectEvents']+4*lid
                if self.g.read8(entry):
                    obj=sy['gObjectEvents']+36*self.g.read8(entry+2)
                    s['position']=dict(x=self.g.read16(obj+16)-7,y=self.g.read16(obj+18)-7,source='link_object_event')
        return s

    def go(self,goal,**options):
        if self.state()['map']['name']!='TradeCenter':return super().go(goal,**options)
        # Link avatars use a separate object index and no ordinary on-foot bit.
        # Keep short, verified walking pulses inside this one cable-only room.
        from .telemetry import read_map
        from .training import path_to
        goal=tuple(goal)
        for _ in range(240):
            state=self.state()
            if state['map']['name']!='TradeCenter':raise AcquisitionAttention('Изменилась карта комнаты обмена')
            if state['controls']['callback']!='CB2_Overworld' or state['controls']['field_locked']:self.advance(8);continue
            here=(state['position']['x'],state['position']['y'])
            sy=symbols(self.g.root);lid=self.g.read8(sy['gLocalLinkPlayerId']);entry=sy['gLinkPlayerObjectEvents']+4*lid
            if self.g.read8(entry+3)==1:self.advance(1);continue
            if here==goal:return
            grid=read_map(self.g);sy=symbols(self.g.root);lid=self.g.read8(sy['gLocalLinkPlayerId']);occupied=[]
            for i in range(4):
                entry=sy['gLinkPlayerObjectEvents']+4*i
                if i!=lid and self.g.read8(entry):
                    obj=sy['gObjectEvents']+36*self.g.read8(entry+2);occupied.append([self.g.read16(obj+16)-7,self.g.read16(obj+18)-7])
            grid=dict(grid,obstacles=occupied,objects=[],trainers=[],script_triggers=[])
            path=path_to(grid,here,goal)
            if not path:raise AcquisitionAttention('Нет пути к месту обмена')
            dx,dy=path[0][0]-here[0],path[0][1]-here[1];key={(1,0):'RIGHT',(-1,0):'LEFT',(0,1):'DOWN',(0,-1):'UP'}[(dx,dy)]
            # A link movement updates tile coordinates before its 16-frame
            # animation ends. Release as soon as the next tile is accepted;
            # holding a fixed pulse can queue another tile and oscillate.
            for frame in range(48):
                self.advance(1,BUTTONS[key])
                pos=self.state()['position']
                if (pos['x'],pos['y'])!=here:break
            self.advance(24)
        raise AcquisitionAttention('Не удалось пройти по комнате обмена')

def cursor_key(game,current,target):
    """Follow the ROM's exact cursor graph, including missing party slots."""
    sy=symbols(game.root);model=layout(game);ptr=game.read32(sy[model.pointer])
    if not 0x02000000<=ptr<0x0203f000:raise AcquisitionAttention('Не открыто меню обмена')
    allowed=set(i for i in range(13) if game.read8(ptr+model.allowed+i))
    if current==target:return 'A'
    queue=deque([(current,[])]);seen={current}
    while queue:
        here,path=queue.popleft()
        for direction,key in enumerate(['UP','DOWN','LEFT','RIGHT']):
            candidates=game.read_bytes(sy[model.graph]+here*24+direction*6,6)
            there=next((n for n in candidates if n in allowed),0)
            if there==target:return (path+[key])[0]
            if there not in seen:seen.add(there);queue.append((there,path+[key]))
    raise AcquisitionAttention('Нет пути к выбранному Pokémon в меню обмена')

def perform_trade(a,b,give_uid,receive_uid,worker):
    reasons=preflight(a,b)
    if reasons:raise AcquisitionAttention('\n'.join(reasons))
    players=[LinkPlayer(a,worker),LinkPlayer(b,worker)];games=[a,b];uids=[give_uid,receive_uid]
    before=[{m['uid']:m for m in p.state()['party']} for p in players]
    if receive_uid in before[0] or give_uid in before[1]:raise AcquisitionAttention('В одной из сторон уже есть Pokémon с тем же уникальным ID; выбери другой экземпляр')
    for i in range(2):
        if uids[i] not in before[i] or len(before[i])<2:raise AcquisitionAttention('Для обмена выбранный Pokémon должен быть в команде из двух или более Pokémon')
        if before[i][uids[i]].get('is_egg'):raise AcquisitionAttention('Обмен яйцами пока не поддерживается')
        p=players[i];name=p.state()['map']['name']
        if not name.endswith('_PokemonCenter_1F'):raise AcquisitionAttention('Обе стороны должны находиться в Pokémon Center')
        p.go(layout(p.g).stairs_up);p.transition('LEFT',name.replace('_1F','_2F'));p.settle(button='A')
    worker.update(stage='Соединяем два Game Boy · настоящий link cable')
    callbacks=set();traded=False
    with Cable(a,b) as cable:
        for i,p in enumerate(players):
            def advance(frames=12,mask=0,i=i):
                for _ in range(frames):cable.advance(1,mask if i==0 else 0,mask if i==1 else 0);worker.heartbeat()
            p.advance=advance
        for p in players:p.go(layout(p.g).attendant);p.tap('UP');p.tap('A',wait=60)
        for _ in range(500):
            states=[p.state() for p in players]
            if all(s['map']['name']=='TradeCenter' and not s['controls']['field_locked'] for s in states):break
            for p,s in zip(players,states):
                if 'CB2_LinkError' in s['controls']['callback']:raise AcquisitionAttention('Ошибка соединения link cable')
                if 'error' in p.text().lower() or 'not ready' in p.text().lower():raise AcquisitionAttention('Игра отклонила подключение: '+p.text())
            masks=[0 if s['map']['name']=='TradeCenter' else BUTTONS['A'] for s in states]
            cable.advance(8,*masks);cable.advance(24);worker.heartbeat()
        else:raise AcquisitionAttention('Не удалось войти в Trade Center')
        worker.update(stage='Выбираем Pokémon для обмена')
        for i,p in enumerate(players):p.go((4 if i==0 else 7,6));p.tap('UP',frames=8,wait=40)
        for step in range(2500):
            states=[p.state() for p in players];masks=[]
            for i,(p,s) in enumerate(zip(players,states)):
                cb=s['controls']['callback'];callbacks.add(cb);sy=symbols(p.g.root)
                from .trade_adapters import learning_prompt
                if learning_prompt(p.g,s):raise AcquisitionAttention('Эволюция при обмене предлагает замену приёма; обе копии сохранены для ручного выбора')
                if 'LinkError' in cb:raise AcquisitionAttention('Связь прервалась; обе исходные стороны сохранены')
                received=[uids[1] in {m['uid'] for m in states[0]['party']},uids[0] in {m['uid'] for m in states[1]['party']}]
                traded|=all(received)
                model=layout(p.g);ptr=p.g.read32(sy[model.pointer]);key=None
                if cb=='CB2_TradeMenu' and 0x02000000<=ptr<0x0203f000:
                    mode=p.g.read8(ptr+model.mode);cursor=p.g.read8(ptr+model.cursor)
                    if mode==0:
                        target=12 if traded else next(m['slot']-1 for m in s['party'] if m['uid']==uids[i])
                        key=cursor_key(p.g,cursor,target)
                    elif mode==1:key='A' if s['controls']['menu_cursor']==1 else 'DOWN'
                    elif mode==3:
                        selected=p.g.read8(ptr+model.remote)%6
                        other=states[1-i]['party']
                        if selected>=len(other) or other[selected]['uid']!=uids[1-i] or s['party'][cursor]['uid']!=uids[i]:raise AcquisitionAttention('Не совпали предложенные Pokémon; обмен не подтверждён')
                        key='A' if s['controls']['menu_cursor']==0 else 'UP'
                    elif mode==4:key='A' if s['controls']['menu_cursor']==0 else 'UP'
                    elif mode==8:raise AcquisitionAttention('Игра отклонила обмен выбранными Pokémon')
                elif cb=='CB2_Overworld' and s['map']['name']=='TradeCenter':key=None
                else:key='A'
                masks.append(BUTTONS[key] if key else 0)
            if traded and all(s['map']['name']=='TradeCenter' and s['controls']['callback']=='CB2_Overworld' and not s['controls']['field_locked'] for s in states):break
            cable.advance(2,*masks);cable.advance(18);worker.heartbeat()
        else:raise AcquisitionAttention('Обмен не завершился; контрольные точки обеих сторон сохранены')
        worker.update(stage='Обмен выполнен · выходим из link room')
        for i,p in enumerate(players):p.go((5 if i==0 else 6,7))
        cable.advance(8,BUTTONS['DOWN'],BUTTONS['DOWN']);cable.advance(60)
        def disconnected():
            return all(not p.g.read32(symbols(p.g.root)['gReceivedRemoteLinkPlayers']) for p in players)
        for _ in range(350):
            states=[p.state() for p in players]
            # CloseLink clears the game's peer flags before the attendant's
            # return dialogue ends. No further serial frames are needed then.
            if disconnected():break
            masks=[BUTTONS['DOWN'] if s['map']['name']=='TradeCenter' and not s['controls']['field_locked'] else BUTTONS['UP'] if 'Task_YesNoMenu_HandleInput' in players[i].tasks(s) and s['controls']['menu_cursor']!=0 else BUTTONS['A'] for i,s in enumerate(states)]
            try:
                for frame in range(32):
                    if disconnected():break
                    cable.advance(1,*(masks if frame<8 else [0,0]));worker.heartbeat()
            except RuntimeError:
                # The software link may finish within a native scheduler call.
                # Only the explicit completion flags permit independent cores.
                if not disconnected():raise
        else:
            for i,p in enumerate(players):
                p.g.save_to(p.g.root/'exit-debug');(p.g.root/'exit-debug/screen.ppm').write_bytes(b'P6\n240 160\n255\n'+p.g.rgb());worker.event('exit_timeout',dict(side=i,state=p.state(),text=p.text()))
            raise AcquisitionAttention('Не завершён выход из Trade Center')
    worker.update(stage='Кабель отсоединён')
    # Return to independent cores only after the game has closed the connection.
    for i,p in enumerate(players):
        del p.advance
        for _ in range(350):
            s=p.state()
            if s['map']['name'].endswith('_PokemonCenter_2F') and s['controls']['callback']=='CB2_Overworld' and not s['controls']['field_locked']:break
            p.tap('A',wait=24)
        else:raise AcquisitionAttention('Не завершён выход к стойке Pokémon Center')
        name=p.state()['map']['name'];p.go(layout(p.g).stairs_down);p.transition('LEFT',name.replace('_2F','_1F'));p.settle(button='A');p.save_game()
    after=[{m['uid']:m for m in p.state()['party']} for p in players]
    if receive_uid not in after[0] or give_uid in after[0] or give_uid not in after[1] or receive_uid in after[1]:raise AcquisitionAttention('Не подтверждены обе стороны обмена')
    for i in range(2):
        expected=(set(before[i])-{uids[i]})|{uids[1-i]}
        if set(after[i])!=expected:raise AcquisitionAttention('Не совпадает состав после обмена')
    from .catalog import species,catalog
    for i in range(2):
        original=before[1-i][uids[1-i]];received=after[i][uids[1-i]];allowed={original['species_id']}
        if catalog(games[i].root)['items'].get(str(original['held_item']),'')!='EVERSTONE':
            allowed.update(e['target'] for e in species(original['species_id'],games[i].root)['evolutions'] if e['method']==5 or e['method']==6 and e['parameter']==original['held_item'])
        if not received['checksum_valid'] or received['species_id'] not in allowed or any(received[k]!=original[k] for k in ('shiny','personality','ivs','evs','level')):
            raise AcquisitionAttention('Не совпали данные полученного Pokémon')
    mon=after[0][receive_uid]
    worker.event('real_link_trade_verified',dict(give_uid=give_uid,receive_uid=receive_uid,callbacks=sorted(callbacks),received=mon))
    return mon
