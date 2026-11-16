from .i18n import t,literal
from .entity_names import species_name
"""Four background hunt slots and one local slot in the main window."""
import time
from . import localized_tk as tk
from tkinter import ttk

from .acquisition import starters_for,read_json,write_json,job_active,WILD_TEMPLATE
from .hunting_template import wild_options
from .hunt_board import HuntBoard
from .capture import catch_probability
from .sprites import sprite
from .catalog import catalog,species
from .ui import BG,CARD,TEXT,MUTED,GREEN,BLUE,AMBER,Button,Toggle,Stepper,Select,label,card

STATES={'searching':'Поиск','capturing':'Встречен · ловим','preparing':'Подготовка','obtained':'Найден · готовим обмен','training':'Докачка','ready':'Пойман · готов к переносу','paused':'Назначен · на паузе','attention':'Нужно внимание','error':'Прерван','cancelled':'Отменён','transferred':'Перенесён в основную игру'}
active=job_active

class AcquisitionView:
    def __init__(self,panel,parent,dock,*,embedded=False):
        self.panel=panel;self.project=panel.monitor.folder;self.parent=parent;self.board=HuntBoard(self.project);self.manager=self.board.manager;self.rows={};self.viewers=[];self.closed=False;self.last_poll=0;self.seen_operation=None;self.cards=[]
        if not embedded:label(parent,'Ловля Pokémon',21,bold=True)
        label(parent,'4 фоновых слота · основная игра остаётся свободна',11,MUTED).pack_configure(pady=(4,12))
        label(parent,'Стартовые у профессора или охота на открытых территориях. Цветной портрет — Pokémon получен и сохранён.',10,BLUE,wraplength=495).pack_configure(pady=(0,10))
        for index in range(4):
            box=card(parent);box.pack(fill='x',pady=(0,8));top=tk.Frame(box,bg=CARD);top.pack(fill='x')
            image_box=tk.Frame(top,bg=CARD,width=64,height=64);image_box.pack(side='left',padx=(0,12));image_box.pack_propagate(False)
            portrait=tk.Label(image_box,bg=CARD);portrait.pack(expand=True)
            info=tk.Frame(top,bg=CARD);info.pack(side='left',fill='x',expand=True)
            title=label(info,'',13,bold=True);status=label(info,'',10,MUTED,wraplength=280)
            info.bind('<Configure>',lambda e,a=title,b=status:(a.configure(wraplength=max(120,e.width)),b.configure(wraplength=max(120,e.width))))
            watch=Button(top,'Смотреть ↗',lambda i=index:self.watch_slot(i),height=28);watch.pack(side='right')
            buttons=tk.Frame(box,bg=CARD);buttons.pack(fill='x',pady=(7,0))
            configure=Button(buttons,'Назначить',lambda i=index:self.configure_slot(i),height=30);configure.pack(side='left')
            run=Button(buttons,'Запустить',lambda i=index:self.run_slot(i),height=30);run.pack(side='left',padx=5)
            cancel=Button(buttons,'Отменить',lambda i=index:self.cancel_slot(i),height=30);cancel.pack(side='left')
            transfer=Button(buttons,'Перенести',lambda i=index:self.transfer_slot(i),variant='primary',height=30);transfer.pack(side='right')
            self.cards.append(dict(layouts={k:b.pack_info() for k,b in dict(configure=configure,run=run,cancel=cancel,transfer=transfer,watch=watch).items()},portrait=portrait,title=title,status=status,configure=configure,run=run,cancel=cancel,transfer=transfer,watch=watch,photo=None,key=None))
        current=(panel.monitor.last_state.get('map') or {}).get('name');default_route=current if current in catalog(self.project)['routes'] else next(iter(catalog(self.project)['routes']),'Route1')
        self.local_path=self.project/'Sessions/acquisition/local-slot.json';self.local=read_json(self.local_path,dict(config=dict(species_id=0,shiny=False,route=default_route),status='idle'))
        label(parent,t('design.main_session'),17,bold=True).pack_configure(pady=(14,6))
        box=card(parent);box.pack(fill='x');self.local_title=label(box,'',12,bold=True);self.local_status=label(box,'В основном игровом окне · для ловли Pokémon на обмен',10,MUTED,wraplength=470)
        row=tk.Frame(box,bg=CARD);row.pack(fill='x',pady=(8,0))
        self.local_configure=Button(row,'Настроить',self.configure_local,height=32);self.local_configure.pack(side='left')
        self.local_run=Button(row,'Запустить',self.run_local,height=32);self.local_run.pack(side='left',padx=6)
        self.local_cancel=Button(row,'Отменить',self.cancel_local,height=32);self.local_cancel.pack(side='left')
        label(parent,'Локальная ловля и перенос забирают управление основной игрой. F9 останавливает действие. Перед каждым запуском создаётся резервная копия.',10,BLUE,wraplength=495).pack_configure(pady=(8,12))
        self.calculator(parent)
        self.actions=tk.Frame(dock,bg=BG,padx=4,pady=8);self.status=label(self.actions,'Фоновые слоты работают независимо от основного окна.',10,MUTED,wraplength=505)
        parent.bind('<Destroy>',lambda e:self.close() if e.widget is parent else None,add='+');self.refresh()
    def error(self,error):self.status.configure(text=str(error),fg=AMBER)
    def configure_slot(self,index):
        row=self.board.row(index)
        if row and active(row):return self.error('Сначала приостанови этот слот')
        config=self.board.slot(index)['config'] or dict(species_id=1,shiny=False,train=False,target_level=10)
        window=tk.Toplevel(self.panel.window);window.title('Слот '+str(index+1));window.configure(bg=BG);body=card(window);body.pack(fill='both',expand=True,padx=14,pady=14)
        chosen=tk.StringVar();shiny=tk.BooleanVar(value=config['shiny']);train=tk.BooleanVar(value=config['train']);level=tk.IntVar(value=config['target_level'])
        source=tk.StringVar(value='Открытые территории' if config.get('source')=='wild' else 'Стартовые у Оука');mapping={}
        label(body,'Источник охоты',11,MUTED);Select(body,source,values=['Стартовые у Оука','Открытые территории'],command=lambda _:populate()).pack(fill='x',pady=8)
        label(body,'Кого получить',16,bold=True);selector=Select(body,chosen,values=[]);selector.pack(fill='x',pady=8)
        Toggle(body,'Только Shiny',shiny).pack(fill='x');training_toggle=Toggle(body,'Докачать до уровня',train);training_toggle.pack(fill='x',pady=8);level_control=Stepper(body,level,5,100);level_control.pack(fill='x')
        hint=label(body,'',10,MUTED,wraplength=390);hint.pack_configure(pady=8)
        def populate():
            wild=source.get()=='Открытые территории';mapping.clear()
            for n in wild_options(self.project) if wild else starters_for(self.project):mapping[species(n,self.project)['name'].title()]=n
            selector.configure(values=list(mapping));chosen.set(next((k for k,v in mapping.items() if v==config['species_id']),next(iter(mapping),'')))
            training_toggle.configure(state='disabled' if wild else 'normal');level_control.configure(state='disabled' if wild else 'normal')
            training_toggle.enabled=not wild;training_toggle.draw()
            if wild:train.set(False)
            hint.configure(text='Маршрут выбирается автоматически. Охотник использует усыпление и при необходимости Leech Seed. Докачка дикой добычи пока недоступна.' if wild else 'Профессор выдаёт стартового без покеболов. Докачка сохраняет базовый вид. Поиск Shiny может занять долгое время.')
        populate()
        def save():
            try:
                self.board.assign(index,dict(species_id=mapping[chosen.get()],source='wild' if source.get()=='Открытые территории' else 'starter',shiny=shiny.get(),train=train.get(),target_level=level.get()));window.destroy();self.last_poll=0;self.refresh()
            except Exception as e:self.error(e)
        Button(body,'Назначить в слот',save,variant='primary').pack(fill='x',pady=8)
    def run_slot(self,index):
        try:
            row=self.board.row(index)
            if row and active(row):self.board.pause(index)
            else:self.board.start(index)
            self.last_poll=0;self.refresh()
        except Exception as e:self.error(e)
    def cancel_slot(self,index):
        try:self.board.cancel(index);self.last_poll=0;self.refresh()
        except Exception as e:self.error(e)
    def watch_slot(self,index):
        row=self.board.row(index)
        if not row:return
        window=tk.Toplevel(self.panel.window);window.title('Охота · слот '+str(index+1));window.configure(bg=BG)
        title=label(window,'Наблюдение за отдельной сессией · управление основной игрой свободно',11,MUTED,wraplength=460);title.pack_configure(padx=12,pady=10)
        screen=tk.Label(window,bg=BG);screen.pack(padx=12,pady=4);stage=label(window,'',11,BLUE,wraplength=460);stage.pack_configure(pady=10)
        job=self.manager.job(row['id']);self.viewers.append(window)
        def tick():
            if not window.winfo_exists():return
            state=read_json(job/'status.json',{});stage.configure(text=state.get('stage','Ожидание первого кадра'))
            try:
                stamp=(job/'screen.ppm').stat().st_mtime_ns
                if stamp!=getattr(screen,'stamp',None):
                    screen.photo=tk.PhotoImage(data=(job/'screen.ppm').read_bytes()).zoom(2,2);screen.configure(image=screen.photo);screen.stamp=stamp
            except (OSError,tk.TclError):pass
            window.after(500,tick)
        tick()
    def transfer_slot(self,index):
        row=self.board.row(index)
        if not row or row.get('status')!='ready':return
        m=self.panel.monitor
        if m.operation.active:return self.error('Основная игра уже занята')
        inventory=m.inventory_snapshot();mons=[p for p in inventory.get('party',[])+inventory.get('boxes',[]) if p.get('checksum_valid') and not p.get('is_egg')]
        choices={'Поймать нового обычного Pokémon':None}
        for mon in mons:
            place='команда' if mon.get('location')=='party' else 'PC '+mon.get('box_name','')
            text=f"{mon['nickname']} · Lv {mon['level']} · {place} · {mon['uid'][-6:]}";choices[text]=mon['uid']
        window=tk.Toplevel(self.panel.window);window.title('Перенос Pokémon');window.configure(bg=BG);body=card(window);body.pack(fill='both',expand=True,padx=14,pady=14)
        target=(row.get('pokemon')or{});label(body,('Shiny ' if target.get('shiny') else '')+species(row['config']['species_id'],self.project)['name'].title(),16,bold=True)
        label(body,'Кого отдать взамен',11,MUTED).pack_configure(pady=(12,4));choice=tk.StringVar(value=next(iter(choices)));Select(body,choice,values=list(choices)).pack(fill='x')
        label(body,'Сначала сохраняются обе стороны. Автоматика дойдёт до Center, проведёт настоящий обмен и вернёт управление. Все остальные Pokémon сохраняются; при заполненной команде один временно перемещается в PC.',10,BLUE,wraplength=440).pack_configure(pady=10)
        def begin():
            try:
                config=dict(donor_job=row['id'],give_uid=choices[choice.get()],origin_map=(m.last_state.get('map')or{}).get('name'))
                m.operation.begin('trade',config);window.destroy();self.last_poll=0;self.refresh()
            except Exception as e:self.error(e)
        Button(body,'Начать обмен',begin,variant='primary').pack(fill='x')
    def configure_local(self):
        if self.panel.monitor.operation.active:return self.error('Основная игра занята')
        config=self.local['config']
        if config.get('schema_version')==2:
            from .catch_view import open_autocatch
            return open_autocatch(self.panel,config['species_id'],route=config.get('route'),method=config.get('method'),preset=config)
        routes=catalog(self.project)['routes'];window=tk.Toplevel(self.panel.window);window.title('Локальная ловля');window.configure(bg=BG);body=card(window);body.pack(fill='both',expand=True,padx=14,pady=14)
        route=tk.StringVar(value=config.get('route') if config.get('route') in routes else next(iter(catalog(self.project)['routes']),'Route1'));chosen=tk.StringVar();shiny=tk.BooleanVar(value=config.get('shiny',False));mapping={}
        label(body,'Маршрут',11,MUTED);Select(body,route,values=sorted(routes),command=lambda _:populate()).pack(fill='x',pady=6)
        label(body,'Pokémon',11,MUTED);selector=Select(body,chosen,values=['Любой обычный Pokémon']);selector.pack(fill='x',pady=6)
        def populate():
            mapping.clear();mapping['Любой Pokémon']=0
            for mon in routes[route.get()]['population']:mapping[species(mon['species_id'],self.project)['name']]=mon['species_id']
            selector.configure(values=list(mapping));chosen.set(next((k for k,v in mapping.items() if v==config.get('species_id')),next(iter(mapping))))
        populate();Toggle(body,'Только Shiny',shiny).pack(fill='x')
        label(body,'Использует твоё основное сохранение и обычные Poké Ball. При полной команде добыча отправляется в PC. Неизвестные сюжетные препятствия требуют игрока.',10,BLUE,wraplength=420).pack_configure(pady=10)
        def save():self.local.update(config=dict(species_id=mapping[chosen.get()],route=route.get(),shiny=shiny.get()),status='idle',pokemon=None);write_json(self.local_path,self.local);window.destroy();self.last_poll=0;self.refresh()
        Button(body,'Сохранить',save,variant='primary').pack(fill='x')
    def run_local(self):
        m=self.panel.monitor
        try:
            if m.operation.active:
                if read_json(m.operation.job/'operation.json',{}).get('kind')=='local':m.operation.command('pause')
                else:raise ValueError('Дождись завершения обмена')
            else:
                m.operation.begin('local',self.local['config']);self.local.update(status='running',pokemon=None);write_json(self.local_path,self.local)
            self.last_poll=0;self.refresh()
        except Exception as e:self.error(e)
    def cancel_local(self):
        if self.panel.monitor.operation.active:self.panel.monitor.operation.command('cancel')
        else:self.local.update(status='cancelled');write_json(self.local_path,self.local);self.last_poll=0;self.refresh()
    def refresh(self):
        if self.closed or time.monotonic()-self.last_poll<.5:return
        self.last_poll=time.monotonic();rows=self.manager.poll();self.board.reconcile(rows);self.rows={r['id']:r for r in rows};m=self.panel.monitor
        for index,c in enumerate(self.cards):
            slot=self.board.slot(index);row=self.board.row(index,rows);config=slot['config'];found=bool(row and row.get('pokemon'));running=bool(row and active(row));state=row.get('status') if row else None
            title=t('hunt.background_session_state',number=index+1,name=species_name(config['species_id']) if config else t('hunt.unassigned'),marker=' ✦' if config and config['shiny'] else '');c['title'].configure(text=title)
            text=(row.get('stage') or STATES.get(state,'')) if row else 'Назначь Pokémon для поиска' if not config else 'Готов к запуску'
            if state in ('ready','transferred','paused','cancelled'):text=STATES[state]
            if row and row.get('pause_pending') and running:text='Завершаем безопасный этап · пауза…'
            c['status'].configure(text=text,fg=GREEN if state in ('ready','transferred') else AMBER if state in ('attention','error') else MUTED)
            key=(config['species_id'],config['shiny'],found) if config else None
            if c['key']!=key:
                c['photo']=sprite(c['portrait'],self.project,config['species_id'],shiny=config['shiny'],gray=not found) if config else None;c['portrait'].configure(image=c['photo'] or '',text='' if config else '—');c['key']=key
            c['configure'].configure(text='Изменить' if config else 'Назначить',state='disabled' if running else 'normal')
            c['run'].configure(text='Пауза' if running else 'Дальше' if row and state in ('paused','attention','error') else 'Запустить',state='normal' if config and state not in ('ready','transferred','cancelled') else 'disabled')
            c['cancel'].configure(state='normal' if config and state not in ('transferred','cancelled') else 'disabled');c['transfer'].configure(state='normal' if state=='ready' and not m.operation.active else 'disabled');c['watch'].configure(state='normal' if row else 'disabled')
            visible={'configure':not running,'run':bool(config and state not in ('ready','transferred','cancelled')),'cancel':bool(config and state not in ('transferred','cancelled')),'transfer':state=='ready','watch':bool(row)}
            for key,show in visible.items():
                widget=c[key]
                if not show:widget.pack_forget()
                elif not widget.winfo_manager():widget.pack(**c['layouts'][key])
            c['configure'].configure(variant='primary' if not config else 'ghost')
            c['run'].configure(variant='primary');c['transfer'].configure(variant='primary')
        self.local=read_json(self.local_path,self.local)
        operation=m.operation.result
        if operation and operation['operation_id']!=self.seen_operation:
            self.seen_operation=operation['operation_id']
            if operation['kind']=='local':self.local.update(config=operation.get('config',self.local['config']),status=operation['status'],pokemon=operation.get('result',{}).get('pokemon'),stage=operation.get('stage'));write_json(self.local_path,self.local)
        config=self.local['config'];self.local_title.configure(text=(species(config['species_id'],self.project)['name'] if config.get('species_id') else 'Любой Pokémon')+(' ✦' if config.get('shiny') else '')+' · '+(config.get('route') or 'Автовыбор'))
        local_running=m.operation.active and m.operation.kind=='local';busy_trade=m.operation.active and not local_running
        self.local_status.configure(text='Основная игра занята обменом' if busy_trade else m.notice if local_running else self.local.get('stage') or STATES.get(self.local.get('status'),'В основном игровом окне'))
        self.local_run.configure(text='Пауза' if local_running else 'Продолжить' if self.local.get('status')=='paused' else 'Запустить',state='disabled' if busy_trade else 'normal');self.local_configure.configure(state='disabled' if m.operation.active else 'normal');self.local_cancel.configure(state='disabled' if busy_trade else 'normal')
        if m.operation.active:self.status.configure(text=m.notice,fg=BLUE)
        elif operation:self.status.configure(text=operation.get('stage','Готово'),fg=GREEN if operation.get('status')=='ready' else MUTED)
    def close(self):self.closed=True

    def calculator(self,parent):
        Button(parent,'Калькулятор ловли ↗',self.open_calculator,variant='ghost',anchor='w').pack(fill='x',pady=(0,6))
    def open_calculator(self):
        if getattr(self,'calculator_window',None) and self.calculator_window.winfo_exists():self.calculator_window.lift();return
        self.calculator_window=tk.Toplevel(self.panel.window);self.calculator_window.title('Калькулятор ловли');self.calculator_window.configure(bg=BG)
        box=card(self.calculator_window);box.pack(fill='both',expand=True,padx=14,pady=14);label(box,'Калькулятор ловли',18,bold=True)
        label(box,'HP, catch rate и статус · обычные шары FireRed',10,MUTED,wraplength=470)
        self.calc_rate=tk.IntVar(value=45);self.calc_hp=tk.IntVar(value=20);self.calc_max=tk.IntVar(value=20)
        grid=tk.Frame(box,bg=BG);grid.pack(fill='x',pady=8)
        for i,(name,var,lo,hi) in enumerate((('Catch rate',self.calc_rate,1,255),('Текущие HP',self.calc_hp,1,999),('Макс. HP',self.calc_max,1,999))):
            grid.columnconfigure(i,weight=1);label(grid,name,10,MUTED,pack=False).grid(row=0,column=i,sticky='w');Stepper(grid,var,lo,hi).grid(row=1,column=i,sticky='ew',padx=(0,5))
        self.calc_ball=tk.StringVar(value='Poké Ball');self.calc_status=tk.StringVar(value='В норме')
        Select(box,self.calc_ball,values=['Poké Ball','Great Ball','Ultra Ball'],command=lambda _:self.calculate()).pack(fill='x',pady=4)
        Select(box,self.calc_status,values=['В норме','Сон','Заморозка','Паралич','Яд','Ожог'],command=lambda _:self.calculate()).pack(fill='x',pady=4)
        self.calc_result=label(box,'',11,BLUE,wraplength=470)
        for var in (self.calc_rate,self.calc_hp,self.calc_max):var.trace_add('write',lambda *_:self.calculate())
        self.calculate()

    def calculate(self):
        try:
            row=catch_probability(self.calc_rate.get(),self.calc_hp.get(),self.calc_max.get(),ball_id={'Poké Ball':4,'Great Ball':3,'Ultra Ball':2}[self.calc_ball.get()],status={'В норме':0,'Сон':1,'Заморозка':0x20,'Паралич':0x40,'Яд':8,'Ожог':0x10}[self.calc_status.get()])
            chance=row['probability'];text=f'Шанс одного броска: {chance:.2%}. '+('Можно бросать без ослабления.' if chance>=.2 else 'Ниже 20%: ослабление только при проверенной безопасности, иначе бросок без атаки.')
        except (ValueError,tk.TclError):text='Укажи HP в пределах максимального значения.'
        self.calc_result.configure(text=text)

