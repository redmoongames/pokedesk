"""Conservative PC transfers through game menus; never edit Pokémon RAM.

Only DEPOSIT / WITHDRAW modes are entered, and only the first action of their
context menu is accepted. Release and move/grab modes are never used.
"""
from .training import TrainingProblem

class Storage:
    def __init__(self,trainer):self.t=trainer;self.bot=trainer.bot
    def inventory(self):
        data=self.bot.inventory()
        if not data.get('ready'):raise TrainingProblem('storage_unavailable','Не удалось прочитать PC')
        return data
    def tasks(self,s):return {t['name']:t for t in s['controls']['tasks']}
    def wait_main(self):return self.t.wait_for(lambda s:'Task_PokeStorageMain' in self.tasks(s) and s['controls']['storage'] and s['controls']['storage']['state']==0,limit=1800)
    def open(self,mode):
        t=self.t
        from .zones import zone_spec
        if t.state()['map']['name'] not in {h['map'] for h in zone_spec(t.root)['hubs'].values()}:raise TrainingProblem('storage_location','Сборка команды доступна в поддерживаемом Pokémon Center')
        grid=self.bot.map();pcs=[(x,y) for y,row in enumerate(grid['tiles']) for x,tile in enumerate(row) if tile[1]==0x83]
        if not pcs:raise TrainingProblem('pc_not_found','В Pokémon Center не найден PC')
        # A real PC metatile, approached from its passable tile below.
        x,y=pcs[0];t.go((x,y+1));t.expect_interaction('storage');t.tap('UP');t.tap('A')
        deadline=t.state()['frame']+2400
        while t.state()['frame']<deadline:
            s=t.state();tasks=self.tasks(s)
            if 'Task_PCMainMenu' in tasks:
                task=tasks['Task_PCMainMenu'];data=task['data']
                if data[0]!=2:t.wait(6);continue
                if data[1]==mode:t.tap('A');self.wait_main();return
                t.tap('DOWN' if data[1]<mode else 'UP');continue
            # Someone/Bill's PC is the first choice. Do not traverse unknown lists.
            if 'Task_HandleMultichoiceInput' in tasks:
                cursor=s['controls']['menu_cursor']
                if cursor:t.tap('UP')
                else:t.tap('A')
            elif s['controls']['callback']=='CB2_Overworld':t.tap('A',wait=18)
            else:t.wait(10)
        raise TrainingProblem('pc_open_timeout','Меню PC не открылось. Проверь диалог вручную.')
    def close(self):
        t=self.t;deadline=t.state()['frame']+2000
        while t.state()['frame']<deadline:
            s=t.state();tasks=self.tasks(s);st=s['controls'].get('storage')
            if s['controls']['callback']=='CB2_Overworld' and not s['controls']['field_locked']:t.expect_interaction('travel');return
            if 'Task_PokeStorageMain' in tasks and st and st['state']==0:t.tap('B')
            elif 'Task_OnBPressed' in tasks and st and st['state']==2:t.tap(st.get('exit_key','B'))
            elif 'Task_PCMainMenu' in tasks and tasks['Task_PCMainMenu']['data'][0]==2:t.tap('B')
            elif s['controls']['callback']=='CB2_Overworld':t.tap('B',wait=18)
            else:t.wait(10)
        raise TrainingProblem('pc_close_timeout','Не удалось закрыть PC. Управление возвращено тебе.')
    def confirm_mon(self,mode):
        t=self.t;t.tap('A');deadline=t.state()['frame']+600
        while t.state()['frame']<deadline:
            s=t.state();st=s['controls'].get('storage');tasks=self.tasks(s)
            if 'Task_OnSelectedMon' in tasks and st and st['state']==2:
                if st['mode']!=mode:raise TrainingProblem('pc_mode_changed','PC оказался в другом режиме; действие отменено.')
                if s['controls']['menu_cursor']!=0:t.tap('UP');continue
                t.tap('A');return
            t.wait(6)
        raise TrainingProblem('pc_context_timeout','PC не подтвердил выбор Pokémon')
    def deposit(self,uid):
        t=self.t;inventory=self.inventory();party=inventory['party'];mon=next((m for m in party if m['uid']==uid),None)
        if mon is None:return
        if len(party)<=1 or not any(m['uid']!=uid and m['hp']>0 and not m['is_egg'] for m in party):raise TrainingProblem('last_usable_pokemon','Нельзя убрать последнего боеспособного Pokémon')
        if 121<=mon.get('held_item',0)<=132:raise TrainingProblem('pokemon_has_mail','У '+mon['nickname']+' письмо: сними его вручную перед сборкой команды.')
        counts={b:sum(m['box']==b for m in inventory['boxes']) for b in range(14)}
        box=next((b for b in range(14) if counts[b]<30),None)
        if box is None:raise TrainingProblem('boxes_full','Все PC-боксы заполнены; сборка остановлена.')
        self.open(1)
        for _ in range(20):
            s=self.wait_main();st=s['controls']['storage'];fresh=self.inventory();target=next(m['slot']-1 for m in fresh['party'] if m['uid']==uid)
            if st['area']!=1:raise TrainingProblem('pc_cursor_area','Ожидалось меню команды в режиме Deposit')
            if st['cursor']==target:break
            t.tap('DOWN' if st['cursor']<target else 'UP')
        else:raise TrainingProblem('pc_cursor_timeout','Не удалось выбрать Pokémon для PC')
        self.confirm_mon(1)
        deadline=t.state()['frame']+1800
        while t.state()['frame']<deadline:
            s=t.state();tasks=self.tasks(s);st=s['controls'].get('storage')
            if 'Task_DepositMenu' in tasks and st and st['state']==1:
                chosen=st.get('choose_box')
                if chosen==box:t.tap('A')
                elif chosen is not None:t.tap('RIGHT')
                else:t.wait(6)
            elif 'Task_PokeStorageMain' in tasks and st and st['state']==0:
                if any(m['uid']==uid for m in self.inventory()['party']):raise TrainingProblem('pc_deposit_rejected','PC отклонил перемещение '+mon['nickname'])
                self.close();self.bot.event('pc_deposit','В PC: '+mon['nickname'],pokemon_uid=uid,box=box);return
            else:t.wait(6)
        raise TrainingProblem('pc_transfer_timeout','PC не подтвердил помещение Pokémon в бокс')
    def withdraw(self,uid):
        t=self.t;inventory=self.inventory()
        if any(m['uid']==uid for m in inventory['party']):return
        if len(inventory['party'])>=6:raise TrainingProblem('party_full','Перед получением из PC нужен свободный слот')
        mon=next((m for m in inventory['boxes'] if m['uid']==uid),None)
        if mon is None:raise TrainingProblem('owned_pokemon_missing','Выбранный Pokémon больше не найден в PC')
        self.open(0)
        # START puts the cursor on the title; horizontal arrows change boxes.
        t.tap('START');self.wait_main()
        for _ in range(15):
            current=self.inventory()['current_box']
            if current==mon['box']:break
            t.tap('RIGHT');self.wait_main()
        else:raise TrainingProblem('pc_box_timeout','Не удалось открыть нужный бокс')
        t.tap('DOWN');self.wait_main()
        for _ in range(20):
            st=self.wait_main()['controls']['storage'];cursor=st['cursor'];target=mon['box_slot']
            if st['area']!=0:raise TrainingProblem('pc_cursor_area','Ожидался Pokémon в сетке бокса')
            if cursor==target:break
            if cursor//6!=target//6:t.tap('DOWN' if cursor//6<target//6 else 'UP')
            else:t.tap('RIGHT' if cursor%6<target%6 else 'LEFT')
        else:raise TrainingProblem('pc_cursor_timeout','Не удалось выбрать Pokémon в боксе')
        self.confirm_mon(0)
        self.wait_main()
        if not any(m['uid']==uid for m in self.inventory()['party']):raise TrainingProblem('pc_withdraw_rejected','PC не подтвердил получение '+mon['nickname'])
        self.close();self.bot.event('pc_withdraw','В команду: '+mon['nickname'],pokemon_uid=uid,box=mon['box'])
    def assemble(self,desired):
        inventory=self.inventory();party=inventory['party'];owned=party+inventory['boxes']
        if any(u not in {m['uid'] for m in owned} for u in desired):raise TrainingProblem('owned_pokemon_missing','Изменился список доступных Pokémon. Перезапусти подбор.')
        if {m['uid'] for m in party}==set(desired):
            self.bot.event('team_unchanged','Состав уже соответствует плану',team_uids=desired);return False
        self.bot.checkpoint('Перед автоматической сборкой команды')
        # Keep a living guard until a desired living Pokémon has been withdrawn.
        guard=next((m['uid'] for m in party if m['uid'] in desired and m['hp']>0),None) or next((m['uid'] for m in party if m['hp']>0),None)
        for m in party:
            if m['uid'] not in desired and m['uid']!=guard:self.deposit(m['uid'])
        for uid in desired:
            if len(self.inventory()['party'])>=6 and guard and guard not in desired:self.deposit(guard);guard=None
            self.withdraw(uid)
        if guard and guard not in desired:self.deposit(guard)
        actual={m['uid'] for m in self.inventory()['party']}
        if actual!=set(desired):raise TrainingProblem('team_mismatch','Состав команды отличается от плана; прокачка не начата.')
        self.bot.event('team_assembled','Команда собрана и проверена',team_uids=desired)
        return True

    def ensure_runner(self,uid,desired=()):
        if uid is None:return
        inventory=self.inventory()
        if any(m['uid']==uid for m in inventory['party']):return
        if len(inventory['party'])>=6:
            candidates=[m for m in inventory['party'] if m['uid']!=self.t.trainee]
            chosen=min(candidates,key=lambda m:(m['uid'] in desired,m['level']))
            self.deposit(chosen['uid'])
        self.withdraw(uid)
        if not any(m['uid']==uid and m['hp']>0 for m in self.inventory()['party']):raise TrainingProblem('runner_unavailable','Не удалось получить живого Pokémon для дороги из PC')
        self.bot.event('runner_collected','Pokémon для дороги получен из PC',pokemon_uid=uid)
