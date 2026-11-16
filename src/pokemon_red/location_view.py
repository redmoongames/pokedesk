
from .paths import resource
from .i18n import t as tmsg,literal,subscribe,unsubscribe
from .entity_names import species_name,item_name
from .table import Table
from .tooltips import Tooltip
from .entity_names import location_matches
"""Trainer location reference and a reviewable auto-travel destination picker."""
import json,webbrowser
from . import localized_tk as tk
from tkinter import ttk

from .ui import BG,CARD,TEXT,MUTED,GREEN,BLUE,AMBER,Button,Toggle,Stepper,Collapse,Select,label,card
from .location_reference import point_label,METHODS,reference
from .locations import location_name
from .catalog import species
from .scrolling import Scrollbar
from .travel_service import TravelService
from .travel import reachability_summary
from .engine import atomic_bytes
from .catch_view import open_autocatch
from .sprites import sprite

class LocationView:
    def __init__(self,panel,parent):
        self.parent=parent;self._last_info=None;self.panel=panel;subscribe(self);parent.bind('<Destroy>',lambda e:unsubscribe(self) if e.widget is parent else None,add='+');self.monitor=panel.monitor;self.root=self.monitor.folder;self.map=None;self.travel=None;self.request_id=0;self.map_generation=None
        head=tk.Frame(parent,bg=BG);head.pack(fill='x');self.title=label(head,'Локация',20,bold=True,pack=False);self.title.pack(side='left');Button(head,'Автопутешествие',self.open_travel,variant='primary').pack(side='right');head.bind('<Configure>',lambda e:self.title.configure(wraplength=max(150,e.width-190)))
        self.selected_map=None;self.map_choice=tk.StringVar();self.map_labels={location_name(name)+' · '+name:name for name in reference(self.root)['maps']}
        choice=tk.Frame(parent,bg=BG);choice.pack(fill='x',pady=(8,4))
        self.map_picker=Select(choice,self.map_choice,values=list(self.map_labels),command=self.choose_map,height=32);self.map_picker.pack(side='left',fill='x',expand=True)
        Button(choice,tmsg('workspace.here'),self.show_current,variant='ghost',height=32).pack(side='right',padx=(6,0))
        self.position=label(parent,'',11,BLUE);self.position.pack_configure(pady=(5,4));self.position_hint=Tooltip(self.position,'Координаты клеток от (0, 0), слева направо и сверху вниз. Для NPC указана постоянная опорная точка.');self.note=label(parent,'',10,MUTED,wraplength=510)
        refresh=Button(head,'↻',lambda:self.refresh(force=True),variant='ghost',width=34,height=30);refresh.pack(side='right',padx=(4,0));Tooltip(refresh,'Обновить справку по сохранению')
        self.body=tk.Frame(parent,bg=BG);self.body.pack(fill='x');self.body.bind('<Configure>',self.wrap)
    def wrap(self,event):
        def visit(widget):
            for child in widget.winfo_children():
                if isinstance(child,tk.Label):child.configure(wraplength=max(180,event.width-40))
                visit(child)
        visit(self.body)
    def choose_map(self,caption):
        self.selected_map=self.map_labels.get(caption);self.refresh(force=True)
    def show_current(self):
        self.selected_map=(self.monitor.last_state.get('map') or {}).get('name');self.refresh(force=True)
    def refresh(self,state=None,force=False):
        state=state or self.monitor.last_state
        if not state or not state.get('ready'):self.position.configure(text='Дождитесь загрузки сохранения');return
        name=self.selected_map or state['map']['name'];self.selected_map=name
        self.map_choice.set(next((label for label,key in self.map_labels.items() if key==name),name))
        p=state['position']
        self.position.configure(text=tmsg('workspace.reference_current',location=location_name(name),x=p['x'],y=p['y']) if name==state['map']['name'] else tmsg('workspace.reference_map',location=location_name(name)))
        if self.travel:self.travel.status_refresh()
        generation=self.monitor.generation
        if name==self.map and self.map_generation==generation and not force:return
        self.map=name;self.map_generation=generation;self.request_id+=1;request_id=self.request_id
        self.note.configure(text='Загружаем справку…')
        def accept(info):
            if request_id==self.request_id and generation==self.monitor.generation and self.body.winfo_exists():self.render_info(name,info)
        def failed(error):
            if request_id==self.request_id and self.body.winfo_exists():
                self.map=None;self.note.configure(text=str(error))
        self.monitor.watch(self.monitor.location_info(name),accept,failed)
    def locale_changed(self):
        if self.parent.winfo_exists() and self._last_info and self._last_info[0]==self.map:self.render_info(*self._last_info)
    def render_info(self,name,info):
        self._last_info=(name,info)
        for child in self.body.winfo_children():child.destroy()
        self.encounter_photos=[]
        self.title.configure(text=location_name(name));self.note.configure(text='')
        if not info:label(self.body,'Справка этой карты ещё не загружена',12,MUTED);return
        label(self.body,'Переходы',16,bold=True).pack_configure(pady=(8,4))
        symbols_to_names={m['id']:n for n,m in reference(self.root)['maps'].items()}
        for exit in info['connections']:
            label(self.body,location_name(symbols_to_names.get(exit['map'],exit['map']))+' · граница карты',11,MUTED)
        for exit in info['warps']:
            target=symbols_to_names.get(exit.get('dest_map'))
            label(self.body,(location_name(target) if target else 'Сюжетный / переменный переход')+' · '+point_label([exit['x'],exit['y']]),11,MUTED,wraplength=490)
        if not info['connections'] and not info['warps']:label(self.body,'Обычных выходов в событиях карты нет.',11,MUTED)
        label(self.body,'Встречи Pokémon',16,bold=True).pack_configure(pady=(8,6))
        if not info['encounters']:label(self.body,'Обычных случайных встреч на этой карте нет.',11,MUTED)
        for method in info['encounters']:
            label(self.body,METHODS.get(method['method'],method['method']),12,BLUE,bold=True).pack_configure(pady=(7,4))
            for row in method['population']:
                sp=species(row['species_id'],self.root);box=card(self.body);box.pack(fill='x',pady=2)
                photo=sprite(box,self.root,row['species_id'],scale=.5)
                if photo:
                    self.encounter_photos.append(photo);icon=tk.Label(box,image=photo,bg=CARD,cursor='hand2');icon.pack(side='left',padx=(0,8));icon.bind('<Button-1>',lambda _,n=row['species_id']:self.panel.open_pokemon(species_id=n))
                Button(box,sp.get('name',str(row['species_id'])),lambda n=row['species_id']:self.panel.open_pokemon(species_id=n),variant='ghost',height=27,anchor='w').pack(side='left',fill='x',expand=True)
                levels=str(row['min_level']) if row['min_level']==row['max_level'] else f"{row['min_level']}–{row['max_level']}"
                Button(box,tmsg('capture.short'),lambda n=row['species_id'],r=name,m=method['method']:open_autocatch(self.panel,n,route=r,method=m),variant='ghost',height=29).pack(side='right',padx=(7,0))
                label(box,f"{row['probability']:g}% · Lv {levels}",11,GREEN,pack=False).pack(side='right')
        if info['encounters']:label(self.body,'Проценты — доля вида среди встреч выбранного способа, а не шанс встречи за шаг. Подарки и сюжетные Pokémon перечислены у соответствующих NPC.',10,MUTED,wraplength=490).pack_configure(pady=(6,8))
        items=Collapse(self.body,'Предметы');items.pack(fill='x',pady=(10,0))
        if not info['items']:label(items.body,'Предметов и подарков с распознанным постоянным событием не найдено.',11,MUTED,wraplength=490)
        for item in info['items']:
            box=card(items.body);box.pack(fill='x',pady=3)
            kind={'ground':'На земле','hidden':'Скрытый предмет','gift':'Подарок / условие NPC'}[item['kind']]
            label(box,item['name']+(f" ×{item['quantity']}" if item['quantity']!=1 else ''),12,GREEN if not item['collected'] else MUTED,bold=True)
            label(box,kind+' · '+point_label(item['point'])+(' · уже получен / событие скрыто' if item['collected'] else ''),10,MUTED,wraplength=490)
            if item['kind']=='gift':label(box,'Доступность зависит от разговора, сюжета и условий NPC.',10,AMBER,wraplength=490)
            if item.get('underfoot'):label(box,'Нужно стоять непосредственно на этой клетке.',10,BLUE)
        objects=[o for o in info['objects'] if o['kind']!='item']
        objects_section=Collapse(self.body,tmsg('design.location_objects',count=len(objects)));objects_section.pack(fill='x',pady=(8,0))
        for obj in objects:
            box=card(objects_section.body);box.pack(fill='x',pady=3)
            trainer=obj.get('trainers',[None])[0] if obj.get('trainers') else None
            title=tmsg('world.trainer_label',role=tmsg('trainers.class.'+trainer['trainer_class']),name=literal(trainer['name'].title())) if trainer else obj['label']
            label(box,title,12,bold=True)
            detail=point_label(obj['point'])+(' · опорная точка движения' if obj['moving'] else ' · постоянная точка')
            if obj['hidden_now']:detail+=' · сейчас скрыт событием'
            label(box,detail,10,MUTED,wraplength=490)
            if obj['graphics']=='NURSE':label(box,'Восстанавливает HP, PP и снимает статусы.',11,BLUE,wraplength=490)
            if obj['graphics']=='MART_CLERK':label(box,'Покупка и продажа предметов.',11,BLUE,wraplength=490)
            for trainer in obj['trainers'][:1]:
                party=', '.join(species_name(m['species_id'])+' Lv '+str(m['level']) for m in trainer['party'])
                label(box,(tmsg('world.defeated') if trainer['defeated'] else tmsg('world.double_battle' if trainer['double'] else 'world.single_battle'))+(' · '+party if party else ''),11,GREEN if trainer['defeated'] else AMBER,wraplength=490)
            for m in obj['facts']['pokemon']:
                label(box,('Подарок / выбор' if m['kind']=='gift' else 'Сюжетная встреча')+' · '+species_name(m['species_id'])+' Lv '+str(m['level']),11,BLUE,wraplength=490)
            if obj['facts']['shop']:
                from .catalog import catalog
                items=catalog(self.root)['items'];label(box,'Магазин: '+', '.join(item_name(i,items.get(str(i),str(i))) for i in obj['facts']['shop']),11,MUTED,wraplength=490)
        label(objects_section.body,'Данные событий FireRed · справка включает скрытые и сюжетные объекты; фактическое появление зависит от прогресса.',10,MUTED,wraplength=490).pack_configure(pady=(12,4))
        Button(self.body,'Источники карты и сценариев ↗',lambda:webbrowser.open(info['sources'][0]),variant='ghost',anchor='w').pack(fill='x')
    def open_travel(self):
        if self.travel and not self.travel.closed:self.travel.window.deiconify();self.travel.window.lift();return
        self.travel=TravelWindow(self)


class TravelWindow:
    def __init__(self,view):
        self.view=view;self.m=view.monitor;self.closed=False;self.service=TravelService();self.rows={};self.selected=None;self.result=None;self.loading=False;self.request_id=0
        self.window=tk.Toplevel(view.panel.window);self.window.title('Автопутешествие');self.window.geometry('760x740');self.window.minsize(620,590);self.window.configure(bg=BG);self.window.protocol('WM_DELETE_WINDOW',self.close);self.window.bind('<Destroy>',lambda e:self.close() if e.widget is self.window else None,add='+')
        head=tk.Frame(self.window,bg=BG,padx=16,pady=12);head.pack(fill='x');label(head,'Автопутешествие',21,bold=True);self.origin=label(head,'',11,BLUE)
        try:previous=json.loads((self.m.folder/'Data/travel.json').read_text())
        except (OSError,ValueError):previous={}
        maximum=previous.get('max_auto_speed',12)
        if type(maximum) is not int or not 1<=maximum<=16:maximum=12
        self.allow=tk.BooleanVar(value=False);self.auto=tk.BooleanVar(value=previous.get('auto_speed',True) is not False);self.maximum=tk.IntVar(value=maximum)
        Toggle(head,'Сражаться с NPC на пути',self.allow,self.refresh_routes).pack(fill='x',pady=(8,3));Toggle(head,'Управлять скоростью',self.auto).pack(fill='x')
        row=tk.Frame(head,bg=BG);row.pack(fill='x',pady=(5,0));label(row,'Максимальная скорость ИИ',11,pack=False).pack(side='left');Stepper(row,self.maximum,1,16).pack(side='right')
        self.search=tk.StringVar();entry=tk.Entry(head,textvariable=self.search,bg=CARD,fg=TEXT,insertbackground=TEXT,relief='flat',font=('Helvetica',12));entry.pack(fill='x',ipady=6,pady=(10,0));label(head,'Поиск по названию локации',10,MUTED)
        content=tk.Frame(self.window,bg=BG,padx=16);content.pack(fill='both',expand=True)
        self.tree=Table(content,columns=('name','status'),show='headings',selectmode='browse',height=12,style='Trainer.Treeview');self.tree.heading('name',text='Локация');self.tree.heading('status',text='Доступность');self.tree.column('name',width=400);self.tree.column('status',width=170)
        scroll=Scrollbar(content,command=self.tree.yview);self.tree.configure(yscrollcommand=scroll.set);scroll.pack(side='right',fill='y');self.tree.pack(fill='both',expand=True)
        foot=tk.Frame(self.window,bg=BG,padx=16,pady=12);foot.pack(side='bottom',fill='x',before=content);self.detail=label(foot,'',11,MUTED,wraplength=710);self.activity=label(foot,'',11,BLUE,wraplength=710)
        actions=tk.Frame(foot,bg=BG);actions.pack(fill='x',pady=(10,0));Button(actions,'Обновить маршруты',self.refresh_routes).pack(side='left');self.start=Button(actions,'Отправиться',self.run,variant='primary');self.start.pack(side='right');Button(foot,'Забрать управление · F9',self.m.take_control,variant='ghost').pack(fill='x',pady=(6,0))
        self.tree.bind('<<TreeviewSelect>>',lambda _:self.select());self.tree.bind('<Down>',lambda _:self.move_selection(1));self.tree.bind('<Up>',lambda _:self.move_selection(-1));self.tree.bind('<Home>',lambda _:self.move_selection(0,edge=True));self.tree.bind('<End>',lambda _:self.move_selection(-1,edge=True));self.search.trace_add('write',lambda *_:self.fill());self.after=None;self.refresh_routes();self.poll()
    def refresh_routes(self):
        if self.closed:return
        try:
            s=self.m.last_state
            if not s or not s.get('ready'):raise ValueError('Дождитесь загрузки игры')
            if getattr(self.m,'operation',None) and self.m.operation.active:raise ValueError('Основная игра занята другой операцией')
            self.origin.configure(text=location_name(s['map']['name'])+' · '+point_label([s['position']['x'],s['position']['y']]))
            self.loading=True;self.request_id+=1;request_id=self.request_id;generation=self.m.generation;allow=self.allow.get()
            self.start.configure(state='disabled');self.activity.configure(text='Проверяем клетки, NPC, сюжет и доступный отряд…')
            def accept(snapshot):
                if self.closed or request_id!=self.request_id:return
                if generation!=self.m.generation or snapshot['generation']!=generation:
                    self.loading=False;self.activity.configure(text='Сохранение изменилось. Обновите маршруты.');return
                self.service.request(self.m.folder,snapshot['state'],allow)
            def failed(error):
                if not self.closed and request_id==self.request_id:self.loading=False;self.activity.configure(text=str(error))
            self.m.watch(self.m.travel_snapshot(),accept,failed)
        except Exception as error:self.activity.configure(text=str(error))
    def fill(self):
        if self.closed:return
        selected=self.selected;query=self.search.get().strip().casefold();self.tree.delete(*self.tree.get_children());self.rows={}
        if not self.result:return
        for row in sorted(self.result['rows'],key=lambda r:(not r['reachable'],r['label'])):
            if not location_matches(query,row['name'],row['label']):continue
            key=row['name'];self.rows[key]=row;status='Можно добраться' if row['reachable'] else 'Нужны бои с NPC' if row.get('can_battle') else 'Вы здесь' if row.get('current') else 'Недоступно'
            self.tree.insert('','end',iid=key,values=(row['label'],status))
        if selected in self.rows:self.tree.selection_set(selected);self.tree.see(selected)
        else:self.selected=None
        self.select()
    def move_selection(self,delta,edge=False):
        keys=list(self.tree.get_children())
        if not keys:return 'break'
        selected=self.tree.selection()
        index=(0 if delta==0 else len(keys)-1) if edge else max(0,min(len(keys)-1,(keys.index(selected[0])+delta) if selected else 0))
        self.tree.selection_set(keys[index]);self.tree.focus(keys[index]);self.tree.see(keys[index]);self.select();return 'break'
    def select(self):
        ids=self.tree.selection();self.selected=ids[0] if ids else None;row=self.rows.get(self.selected)
        if not row:self.detail.configure(text='Выберите локацию. Недоступные места тоже можно выбрать, чтобы увидеть причину.');self.start.configure(state='disabled');return
        text=row.get('reason','')
        if row['reachable']:
            stops=' → '.join(location_name(l['destination']) for l in row['legs'])
            text=f"{row['steps']} шагов · бои с NPC: {row['battles']} · приёмы: {', '.join(row['tools']) or 'не нужны'}\n{stops}\nПеред запуском путь и отряд проверяются заново. Прибытие — на паузе."
        self.detail.configure(text=text);self.start.configure(state='normal' if row['reachable'] and self.controls_ready() and not self.loading and not self.m.automation.running and not (getattr(self.m,'operation',None) and self.m.operation.active) else 'disabled')
    def controls_ready(self):
        state=self.m.last_state or {};controls=state.get('controls',{})
        return bool(state.get('ready') and not state.get('in_battle') and controls.get('callback')=='CB2_Overworld' and not controls.get('field_locked') and not controls.get('moving'))
    def status_refresh(self):
        if self.closed:return
        info=self.m.automation.info()
        if not info['running'] and not self.loading and not self.controls_ready():
            self.activity.configure(text='Для запуска закончите бой или диалог и остановитесь на клетке.');self.start.configure(state='disabled')
        if info['running']:self.activity.configure(text=(info.get('stage') or info['reason'])+' · F9 — остановить');self.start.configure(state='disabled')
    def poll(self):
        if self.closed:return
        ready=self.service.poll()
        if ready:
            self.loading=False;self.result,error=ready
            self.activity.configure(text=error or reachability_summary(self.result));self.fill()
        self.status_refresh();self.after=self.window.after(100,self.poll)
    def run(self):
        row=self.rows.get(self.selected)
        if not row or not row['reachable']:return
        try:
            from .automatic_speed import speed_cap
            cap=speed_cap(self.maximum.get());cfg=dict(destination=row['name'],allow_trainers=self.allow.get(),auto_speed=self.auto.get(),max_auto_speed=cap)
            atomic_bytes(self.m.folder/'Data/travel.json',json.dumps(cfg).encode(),durable=True);self.m.start_bot(resource(self.m.folder,'Bots/travel.py'));self.activity.configure(text='Сохраняем прогресс и начинаем путешествие…');self.select()
        except Exception as error:self.activity.configure(text=str(error))
    def close(self):
        if self.closed:return
        self.closed=True;self.service.close()
        try:
            if self.after:self.window.after_cancel(self.after)
            self.window.destroy()
        except tk.TclError:pass
