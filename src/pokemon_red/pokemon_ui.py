from .i18n import t
from .entity_names import pokemon_name
from .i18n import literal
from .entity_names import display_entity_names as _entity_label
from .table import Table
"""Sprite-led Pokémon inspector, shared mechanics and live opponent cards."""
from . import localized_tk as tk
from .scrolling import Scrollbar
from tkinter import ttk

from .catalog import catalog,species,move,ability,evolution_text,effectiveness
from .ui import BG,CARD,TEXT,MUTED,GREEN,BLUE,AMBER,Button,Tabs,Meter,theme,label,card
from .sprites import sprite,PokemonCard
from .types_ui import Badges,Matchups,types_for

STATS={'hp':'HP','attack':'Атака','defense':'Защита','speed':'Скорость','special_attack':'Спец. атака','special_defense':'Спец. защита'}

def page(notebook,title):
    frame=tk.Frame(notebook,bg=BG,padx=16,pady=10);notebook.add(frame,text=title);return frame

def tree(parent,columns,height=10):
    frame=tk.Frame(parent,bg=BG);frame.pack(fill='both',expand=True,pady=8)
    view=Table(frame,columns=[c[0] for c in columns],show='headings',style='Trainer.Treeview',height=height)
    for key,title,width in columns:view.heading(key,text=title);view.column(key,width=width,minwidth=45)
    scroll=Scrollbar(frame,command=view.yview,style='Dark.Vertical.TScrollbar');scroll.pack(side='right',fill='y');view.configure(yscrollcommand=scroll.set);view.pack(fill='both',expand=True)
    return view

def detail_window(panel,key,title,height=550):
    windows=getattr(panel,'detail_windows',{});w=windows.get(key)
    if w is None or not w.winfo_exists():
        w=tk.Toplevel(panel.window);w.configure(bg=BG);w.geometry(f'610x{height}');windows[key]=w;panel.detail_windows=windows
    for child in w.winfo_children():child.destroy()
    theme(w);w.title(title);w.deiconify();w.lift()
    body=tk.Frame(w,bg=BG,padx=20,pady=16);body.pack(fill='both',expand=True);return body

def show_move(panel,number):
    from .move_details_ui import show_move as open_move
    return open_move(panel,number)

def show_ability(panel,number):
    a=ability(number,panel.monitor.folder)
    if not a:return
    body=detail_window(panel,'ability','Способность · '+_entity_label(a['name']),340);label(body,_entity_label(a['name']),23,GREEN,bold=True);label(body,'Пассивная способность',11,MUTED).pack_configure(pady=(6,18));label(body,t('entity.abilities.'+str(number)+'.description'),14,wraplength=550)
    extra=a.get('mechanics',{}).get('text')
    if extra:label(body,extra,12,wraplength=550).pack_configure(pady=(16,0))

class PokemonInspector:
    def __init__(self,panel):
        self.panel=panel;self.root=panel.monitor.folder;self.history=[];self.context=None;self.number=None
        self.window=tk.Toplevel(panel.window);self.window.configure(bg=BG);self.window.geometry('790x780');self.window.minsize(660,650);theme(self.window)
        top=tk.Frame(self.window,bg=BG,padx=18,pady=10);top.pack(fill='x');self.back=Button(top,'← Назад',self.go_back,variant='ghost',width=95);self.back.pack(side='left');self.heading=label(top,'',10,MUTED,pack=False);self.heading.pack(side='right')
        hero=tk.Frame(self.window,bg=BG,padx=16);hero.pack(fill='x');self.portrait=tk.Label(hero,bg=BG);self.portrait.pack(side='left');info=tk.Frame(hero,bg=BG);info.pack(side='left',fill='x',expand=True,padx=12);self.hero_title=label(info,'',23,bold=True);self.hero_types=Badges(info);self.hero_types.pack(fill='x',pady=3);self.hero_detail=label(info,'',11,MUTED)
        self.tabs=Tabs(self.window);self.tabs.pack(fill='both',expand=True,padx=14,pady=10);self.refresh_live()
    def navigate(self,number,mon=None,*,remember=True,raise_window=True):
        if remember and self.number is not None:self.history.append((self.number,self.context))
        self.number=number;self.context=mon;sp=species(number,self.root)
        for item in self.tabs.tabs():self.tabs.nametowidget(item).destroy()
        self.window.title('Pokémon · '+_entity_label(sp['name']));self.heading.configure(text=f"#{sp['national_id']:03} · FireRed")
        self.image=sprite(self.window,self.root,number,scale=2,shiny=(mon or {}).get('shiny',False),gray=mon is not None and mon.get('hp',1)<=0);self.portrait.configure(image=self.image)
        self.hero_title.configure(text=literal(('✦ ' if mon.get('shiny') else '')+pokemon_name(mon)) if mon else _entity_label(sp['name']));self.hero_types.set(sp['type_ids']);self.hero_detail.configure(text=f"Lv {mon['level']} · {_entity_label(sp['name'])}" if mon else 'Справочник вида')
        self.back.configure(state='normal' if self.history else 'disabled')
        if mon:self.build_current(page(self.tabs,'Противник' if mon.get('opponent') else 'Мой Pokémon'))
        self.build_species(page(self.tabs,'Вид'),sp);self.build_learnset(page(self.tabs,'Приёмы'),sp);self.build_evolutions(page(self.tabs,'Эволюции'),sp)
        if raise_window:self.window.deiconify();self.window.lift()
    def go_back(self):
        if self.history:
            number,mon=self.history.pop();self.navigate(number,mon,remember=False)
    def build_current(self,parent):
        box=card(parent);box.pack(fill='x');self.live_title=label(box,'',15,GREEN,bold=True);self.live_detail=label(box,'',11,MUTED,wraplength=680);self.live_detail.pack_configure(pady=6);self.hp=Meter(box);self.hp.pack(fill='x',pady=5);self.live_xp=label(box,'',11);self.xp=Meter(box,color=BLUE);self.xp.pack(fill='x',pady=5)
        self.live_stats=tree(parent,[('stat','Характеристика',240),('current','Сейчас',130),('base','База вида',140)],height=6)
        for key,title in STATS.items():self.live_stats.insert('','end',iid=key,values=(title,'—','—'))
        self.ability_button=Button(parent,'',lambda:show_ability(self.panel,self.context.get('ability_id',0)),anchor='w');self.ability_button.pack(fill='x',pady=6)
        frame=tk.Frame(parent,bg=BG);frame.pack(fill='x');frame.columnconfigure((0,1),weight=1);self.move_buttons=[]
        for i in range(4):
            b=Button(frame,'',lambda i=i:self.open_current_move(i),anchor='w',height=38);b.grid(row=i//2,column=i%2,sticky='ew',padx=(0 if i%2==0 else 4,4 if i%2==0 else 0),pady=4);self.move_buttons.append(b)
        self.update_current(self.context)
    def open_current_move(self,index):
        moves=self.context.get('moves',[])
        if index<len(moves):show_move(self.panel,moves[index]['id'])
    def update_current(self,mon):
        sp=species(mon['species_id'],self.root);self.live_title.configure(text=f"HP {mon['hp']} / {mon['max_hp']} · {mon.get('status','')}")
        self.image=sprite(self.window,self.root,mon['species_id'],scale=2,shiny=mon.get('shiny',False),gray=mon['hp']<=0);self.portrait.configure(image=self.image);self.hero_types.set(types_for(mon,self.root))
        item=catalog(self.root)['items'].get(str(mon.get('held_item',0)),'—') if mon.get('held_item') else '—'
        self.live_detail.configure(text=f"Предмет: {item} · Дружба: {mon.get('friendship','—')}"+(' · '+mon['location_note'] if mon.get('location_note') else ' · PC: HP рассчитаны' if mon.get('location')=='box' else ''))
        self.hp.set(mon['hp']/max(1,mon['max_hp']));self.hero_detail.configure(text=f"Lv {mon['level']} · {_entity_label(sp['name'])}"+(' · ✦ Shiny' if mon.get('shiny') else ''))
        if 'experience' in mon and mon['level'] in range(1,101):
            curve=catalog(self.root)['growth'][sp['growth']];lv=mon['level'];self.live_xp.configure(text=f"{mon['experience']} XP · до следующего уровня {mon['exp_to_next_level']}");self.xp.set(1 if lv==100 else (mon['experience']-curve[lv])/max(1,curve[lv+1]-curve[lv]))
        else:self.live_xp.configure(text='');self.xp.set(0)
        for key,title in STATS.items():
            value=f"{mon['hp']}/{mon['max_hp']}" if key=='hp' else mon.get('stats',{}).get(key,'—');stage=mon.get('stages',{}).get(key,0)
            self.live_stats.item(key,values=(title,str(value)+(f' · {stage:+d} ступ.' if stage else ''),sp['base_stats'][key]))
        a=ability(mon.get('ability_id',0),self.root);self.ability_button.configure(text=a.get('name','—')+' · пассивная способность ↗')
        for i,b in enumerate(self.move_buttons):
            if i<len(mon.get('moves',[])):
                m=mon['moves'][i];b.configure(text=f"{_entity_label(m['name'])} · {m.get('current_pp','?')}/{m.get('max_pp',m['pp'])} PP ↗",state='normal')
            else:b.configure(text='Пустой слот',state='disabled')
    def refresh_live(self):
        if not self.window.winfo_exists():return
        if self.context:
            state=self.panel.monitor.last_state or {};party=state.get('party',[])
            if self.context.get('opponent'):party=(state.get('battle') or {}).get('enemy_party',[])
            current=next((m for m in party if m.get('uid')==self.context.get('uid')),None)
            if current:
                current=dict(current,opponent=bool(self.context.get('opponent')))
                if current['species_id']!=self.number:self.navigate(current['species_id'],current,remember=False,raise_window=False)
                else:self.context=current;self.update_current(current)
            elif self.context.get('opponent'):self.context['location_note']='Бой завершён';self.update_current(self.context)
        self.window.after(350,self.refresh_live)
    def build_species(self,parent,sp):
        stats=tree(parent,[('stat','Базовая характеристика',330),('value','Значение',200)],height=6)
        for key,title in STATS.items():stats.insert('','end',values=(title,sp['base_stats'][key]))
        row=tk.Frame(parent,bg=BG);row.pack(fill='x',pady=6)
        for number in sp['abilities']:
            a=ability(number,self.root);Button(row,_entity_label(a['name'])+' ↗',lambda n=number:show_ability(self.panel,n)).pack(side='left',padx=(0,8))
        matchups=Matchups(parent,self.root);matchups.pack(fill='x',pady=(10,4));matchups.set(dict(species_id=sp['id'],ability_id=0))
        label(parent,f"Базовый XP {sp['base_xp']} · Дружба {sp['friendship']} · Catch rate {sp['catch_rate']}",11,MUTED).pack_configure(pady=12)
    def build_learnset(self,parent,sp):
        from .learnset_ui import LearnsetView
        self.learnset_view=LearnsetView(parent,self.root,sp,self.context,lambda number:show_move(self.panel,number))
    def build_evolutions(self,parent,sp):
        all_species=catalog(self.root)['species'];reverse={}
        for entry in all_species.values():
            for e in entry['evolutions']:reverse.setdefault(e['target'],[]).append(entry['id'])
        roots={sp['id']}
        while any(n in reverse for n in roots):roots={p for n in roots for p in reverse.get(n,[n])}
        view=Table(parent,columns=('condition',),show='tree headings',style='Sprite.Treeview',height=6);view.heading('#0',text='Pokémon');view.heading('condition',text='Эволюция');view.column('#0',width=260);view.column('condition',width=420);view.pack(fill='both',expand=True,pady=8);mapping={};self.evo_images=[]
        def add(number,parent='',condition='Исходный вид'):
            s=species(number,self.root);image=sprite(view,self.root,number);self.evo_images.append(image);iid=view.insert(parent,'end',text=_entity_label(s['name'])+(' ◀' if number==sp['id'] else ''),image=image,values=(condition,),open=True);mapping[iid]=number
            for e in s['evolutions']:add(e['target'],iid,evolution_text(e,self.root))
        for number in sorted(roots):add(number)
        def open_selected(_=None):
            if view.selection():self.navigate(mapping[view.selection()[0]])
        Button(parent,'Открыть выбранный вид ↗',open_selected).pack(anchor='w');view.bind('<Double-1>',open_selected)
        label(parent,'Эволюции вне Kanto могут требовать National Dex. День и ночь в FireRed отсутствуют.',10,MUTED,wraplength=680).pack_configure(pady=10)

def show_species(panel,number,mon=None):
    if hasattr(panel,'open_pokemon'):return panel.open_pokemon(mon=mon,species_id=number)
    # Compatibility for a trainer already loaded before this update.
    inspector=getattr(panel,'inspector',None)
    if inspector is None or not inspector.window.winfo_exists():inspector=PokemonInspector(panel);panel.inspector=inspector
    return inspector.navigate(number,mon)


# Stable import path for an already loaded trainer and external tools.
from .battle_panel import BattlePanel
