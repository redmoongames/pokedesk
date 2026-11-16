from .i18n import t
from .entity_names import pokemon_name
from .i18n import literal,subscribe,unsubscribe
from .entity_names import display_entity_names as _entity_label
"""One embedded page for an owned Pokémon, its forms, level-up moves and bases."""
import time
from . import localized_tk as tk
from .ui import BG,CARD,BORDER,TEXT,MUTED,GREEN,BLUE,AMBER,RED,Button,Tabs,Meter,label,card,rounded,short
from .catalog import catalog,species,ability,evolution_text
from .sprites import sprite
from .types_ui import Badges,Matchups,types_for
from .tooltips import Tooltip
from .evolution_reference import EvolutionIndex

STAT_LABELS=[('hp','HP'),('attack','Атака'),('defense','Защита'),('special_attack','Спец. атака'),('special_defense','Спец. защита'),('speed','Скорость')]

class FormCard(tk.Canvas):
    def __init__(self,parent,root,number,command):
        super().__init__(parent,bg=BG,height=72,width=120,highlightthickness=0,bd=0,cursor='hand2',takefocus=True)
        self.number=number;self.command=command;self.info=species(number,root);self.selected=False;self.current=False;self.image=sprite(self,root,number,scale=.5)
        self.bind('<Configure>',lambda _:self.draw());self.bind('<Button-1>',self.invoke);self.bind('<Return>',self.invoke);self.bind('<space>',self.invoke);self.bind('<FocusIn>',lambda _:self.draw());self.bind('<FocusOut>',lambda _:self.draw())
        Tooltip(self,self.info['name'])
    def invoke(self,_=None):self.command(self.number);return 'break'
    def draw(self):
        from tkinter import font
        if not self.winfo_exists():return
        self.delete('all');w=self.winfo_width();rounded(self,1,1,w-1,71,8,fill='#213449' if self.selected else CARD,outline=BLUE if self.selected else GREEN if self.current else BORDER,width=2 if self.selected or self.focus_get() is self else 1)
        if self.image:self.create_image(w/2,22,image=self.image)
        f=font.Font(root=self,font=('Helvetica',9,'bold'));self.create_text(w/2,47,text=short(self.info['name'],w-12,f),font=f,fill=TEXT)
        self.create_text(w/2,62,text='Твой Pokémon' if self.current else '✓ Выбрано' if self.selected else '#'+str(self.info['national_id']).zfill(3),font=('Helvetica',8),fill=GREEN if self.current else BLUE if self.selected else MUTED)

class FormSelector:
    def __init__(self,parent,root,index,number,current,command):
        self.frame=tk.Frame(parent,bg=BG);self.frame.pack(fill='x');self.cards=[];self.columns=None
        for n in index.family(number):self.cards.append(FormCard(self.frame,root,n,command))
        self.frame.bind('<Configure>',self.layout);self.set(number,current)
    def layout(self,event):
        cols=max(1,min(len(self.cards),4,event.width//115))
        if cols==self.columns:return
        self.columns=cols
        for col in range(4):self.frame.columnconfigure(col,weight=1 if col<cols else 0,uniform='forms' if col<cols else '')
        for i,w in enumerate(self.cards):w.grid(row=i//cols,column=i%cols,sticky='ew',padx=(0,6 if i%cols<cols-1 else 0),pady=(0,6))
    def set(self,number,current):
        for w in self.cards:w.selected=w.number==number;w.current=w.number==current;w.draw()

class BaseStats(tk.Canvas):
    def __init__(self,parent):
        super().__init__(parent,bg=CARD,height=233,width=360,highlightthickness=0,bd=0);self.sp=None;self.bind('<Configure>',lambda _:self.draw())
    def set(self,sp):self.sp=sp;self.draw()
    def draw(self):
        if not self.sp or not self.winfo_exists():return
        self.delete('all');w=max(300,self.winfo_width());colors=[GREEN,AMBER,BLUE,'#d69ec3','#98c8d4','#c6bd86']
        for i,(key,title) in enumerate(STAT_LABELS):
            y=22+i*33;value=self.sp['base_stats'][key];self.create_text(12,y,text=title,anchor='w',font=('Helvetica',11),fill=TEXT)
            left=133;right=w-50;self.create_rectangle(left,y-5,right,y+5,fill=BORDER,outline='');self.create_rectangle(left,y-5,left+(right-left)*value/255,y+5,fill=colors[i],outline='');self.create_text(w-12,y,text=str(value),anchor='e',font=('Helvetica',12,'bold'),fill=TEXT)
        self.create_text(12,221,text='Сумма базовых характеристик: '+str(sum(self.sp['base_stats'].values())),anchor='w',font=('Helvetica',10),fill=MUTED)

class PokemonPage:
    def __init__(self,panel,parent,number,mon=None):
        self.panel=panel;self.root=panel.monitor.folder;self.parent=parent;subscribe(self);parent.bind('<Destroy>',lambda e:unsubscribe(self) if e.widget is parent else None,add='+');self.context=dict(mon) if mon else None;self.uid=(mon or {}).get('uid');self.current_number=number;self.selected=number;self.index=EvolutionIndex(catalog(self.root)['species']);self.last_inventory=0;self.form_states={}
        hero=tk.Frame(parent,bg=BG);hero.pack(fill='x',pady=(2,10));self.portrait=tk.Label(hero,bg=BG);self.portrait.pack(side='left');info=tk.Frame(hero,bg=BG);info.pack(side='left',fill='x',expand=True,padx=(8,0));self.title=label(info,'',19,bold=True);self.identity=label(info,'',10,MUTED,wraplength=410);self.types=Badges(info);self.types.pack(fill='x',pady=4);self.health=label(info,'',11,GREEN);self.hp=Meter(info);self.hp.pack(fill='x',pady=(3,0))
        self.live_xp=label(info,'',10,MUTED);self.live_xp.pack(fill='x',pady=(5,0))
        if not mon:self.health.pack_forget();self.hp.pack_forget();self.live_xp.pack_forget()
        self.catch_hero=Button(info,t('capture.action'),self.open_catch,variant='ghost',height=29);self.catch_hero.pack(anchor='w',pady=(4,0))
        if mon:self.catch_hero.pack_forget()
        self.party_badge=label(info,'',10,GREEN);self.train_button=Button(info,t('training.auto_train'),self.open_training,variant='primary',height=30)
        self.party_badge.pack_forget()
        self.tabs=Tabs(parent);self.tabs.pack(fill='both',expand=True)
        self.pages={}
        entries=[('current',t('design.personal') if not (mon or {}).get('opponent') else 'Противник')] if mon else []
        for key,title in entries+[('moves',t('design.moves')),('base',t('design.species')),('source',t('design.source'))]:
            page=tk.Frame(self.tabs,bg=BG,pady=8);self.tabs.add(page,text=title);self.pages[key]=page
        for _,_,button in self.tabs.entries:
            button.font.configure(size=10);button.configure(width=button.font.measure(button.text)+28)
        if mon:
            from .team_view import OwnedDetail
            self.owned=OwnedDetail(panel,self.pages['current']);self.owned.frame.pack(fill='x');self.owned.hero.pack_forget();self.owned.set(mon)
        else:self.owned=None
        moves=self.pages['moves'];label(moves,'Эволюции и изучение приёмов',13,bold=True).pack_configure(pady=(0,8));self.forms=FormSelector(moves,self.root,self.index,number,number if mon else None,self.select_form)
        self.form_info=label(moves,'',11,BLUE,wraplength=480);self.form_info.pack_configure(pady=(4,6))
        self.loss_summary=label(moves,'',10,AMBER,wraplength=480);self.loss_summary.pack_configure(pady=(0,8))
        from .learnset_ui import LearnsetView
        self.learnset=LearnsetView(moves,self.root,species(number,self.root),self.context,self.panel.open_move,annotations=self.index.outlook(number),embedded=True)
        label(moves,'★ Только у этой формы по уровню · △ Зависит от ветки. Сравнение не включает TM, разведение и обучение у NPC.',10,MUTED,wraplength=480).pack_configure(pady=(8,0))
        base=self.pages['base'];self.base_title=label(base,'',15,bold=True);self.base_stats=BaseStats(base);self.base_stats.pack(fill='x',pady=(8,10))
        label(base,'База одинакова у всех Pokémon этого вида. Текущие значения зависят также от уровня, характера, IV и EV.',11,MUTED,wraplength=480).pack_configure(pady=(0,12));self.base_abilities=tk.Frame(base,bg=BG);self.base_abilities.pack(fill='x')
        self.base_matchups=Matchups(base,self.root);self.base_matchups.pack(fill='x',pady=(12,4))
        self.change_form=Button(base,'Выбрать другую форму →',lambda:self.tabs.select(self.pages['moves']),variant='ghost');self.change_form.pack(anchor='w')
        from .pokemon_source_ui import PokemonSourceView
        self.source_view=PokemonSourceView(panel,self.pages['source'],number,self.open_related)
        self.source_title=self.source_view.title;self.source_origin=self.source_view.origin;self.source_text=self.source_view.summary
        self.catch_button=Button(self.pages['source'],t('capture.action'),self.open_catch,variant='primary',anchor='w');self.catch_button.pack(fill='x',pady=(12,5))
        self.catch_hint=label(self.pages['source'],'',10,MUTED,wraplength=480)
        self.source_link=Button(moves,'',self.open_source,variant='ghost',height=30,anchor='w');self.source_link.pack(fill='x',before=self.forms.frame,pady=(0,7))
        parent.bind('<Configure>',self.resize,add='+');self.update_identity();self.select_form(number,save=False)
        if not mon:self.tabs.select(self.pages['moves'])
    def in_party(self):
        return bool(self.uid and not (self.context or {}).get('opponent') and any(m.get('uid')==self.uid for m in (self.panel.monitor.last_state or {}).get('party',[])))
    def trainable_uid(self):
        if (self.context or {}).get('opponent'):return None
        monitor=self.panel.monitor;inventory=getattr(monitor,'last_inventory',None) or {}
        owned=(monitor.last_state or {}).get('party',[])+inventory.get('boxes',[])
        if self.uid:return self.uid if any(m.get('uid')==self.uid and not m.get('is_egg') for m in owned) else None
        matches=[m for m in owned if m.get('species_id')==self.current_number and not m.get('is_egg')]
        return matches[0]['uid'] if len(matches)==1 else None
    def update_membership(self):
        if self.in_party():
            self.party_badge.configure(text=t('training.in_party'))
            if not self.party_badge.winfo_manager():self.party_badge.pack(fill='x',pady=(4,0))
        else:self.party_badge.pack_forget()
        if self.trainable_uid():
            if not self.train_button.winfo_manager():self.train_button.pack(anchor='w',pady=(5,0))
        else:self.train_button.pack_forget()
    def open_training(self):
        uid=self.trainable_uid()
        if uid:return self.panel.open_training(uid)
    def open_catch(self):
        from .catch_view import open_autocatch
        return open_autocatch(self.panel,self.selected)
    def update_catch(self):
        from .capture_target import catchable_species
        wild=self.selected in catchable_species(self.root)
        self.catch_button.configure(state='normal' if wild else 'disabled');self.catch_hero.configure(state='normal' if wild else 'disabled')
        self.catch_hint.configure(text='Доступность места и способа проверяется перед запуском.' if wild else 'У этой формы нет обычных диких встреч в FireRed. Получение: подарок, эволюция, обмен или особое событие.')
    def resize(self,event):
        width=max(280,event.width-15);self.identity.configure(wraplength=max(250,width-80));self.form_info.configure(wraplength=width);self.loss_summary.configure(wraplength=width)
        def wrap(parent):
            for w in parent.winfo_children():
                if isinstance(w,tk.Label) and int(w.cget('wraplength') or 0)>0:w.configure(wraplength=width)
        for page in self.pages.values():wrap(page)
    def update_identity(self):
        self.update_membership()
        sp=species(self.current_number,self.root);m=self.context or {};self.photo=sprite(self.parent,self.root,self.current_number,shiny=m.get('shiny',False),gray=bool(m and m.get('hp',1)<=0));self.portrait.configure(image=self.photo or '')
        if hasattr(self,'source_view'):self.source_view.set_species(self.current_number)
        self.title.configure(text=literal(('✦ ' if m.get('shiny') else '')+pokemon_name(m)) if m else _entity_label(sp['name']))
        self.identity.configure(text=((str(t('design.level',level=m['level'])) if m.get('nickname','').casefold()==m.get('species','').casefold() else f"{_entity_label(sp['name'])} · Lv {m['level']}") if m else f"#{sp['national_id']:03} · справочник FireRed")+(' · противник' if m.get('opponent') else ''));self.types.set(types_for(m,self.root) if m else sp['type_ids'])
        if m:
            ratio=m.get('hp',0)/max(1,m.get('max_hp',1));self.health.configure(text=f"HP {m.get('hp','—')} / {m.get('max_hp','—')} · {m.get('status','')}",fg=GREEN if ratio>.5 else AMBER if ratio>.2 else RED);self.hp.set(ratio,color=GREEN if ratio>.5 else AMBER if ratio>.2 else RED)
            self.live_xp.configure(text=t('design.next_level',xp=m['exp_to_next_level']) if 'exp_to_next_level' in m and m.get('level',0)<100 else '')
    def select_form(self,number,*,save=True):
        from .dex_reference import origin_label
        if save:
            self.form_states[self.selected]=dict(query=self.learnset.query.get(),unique=self.learnset.only_unique.get(),selected=self.learnset.selected,scroll=self.learnset.view.yview()[0])
        self.selected=number;self.update_catch();sp=species(number,self.root);self.forms.set(number,self.current_number if self.context else None)
        self.source_link.configure(text=_entity_label(sp['name']).title()+' · Как получить →')
        parents=self.index.parents[number]
        self.form_info.configure(text=_entity_label(sp['name'])+' · '+(' / '.join('из '+_entity_label(species(p,self.root)['name'])+': '+('недоступно в FireRed; нужна эволюция в другой игре поколения III' if e['method'] in (2,3) else evolution_text(e,self.root)) for p,e in parents) if parents else 'Начальная форма'))
        outlook=self.index.outlook(number);exclusive=sum(v['kind']=='exclusive' for v in outlook.values());branch=sum(v['kind']=='branch' for v in outlook.values())
        self.loss_summary.configure(text=f'★ Только у этой формы по уровню: {exclusive}'+(f' · △ Зависят от ветки: {branch}' if branch else '') if exclusive or branch else 'Уникальных потерь при эволюции по уровню нет' if self.index.children(number) else 'Конечная форма: дальше эволюций нет')
        state=self.form_states.get(number,{});self.learnset.query.set(state.get('query',''));self.learnset.only_unique.set(state.get('unique',False));self.learnset.selected=state.get('selected');self.learnset.set_species(sp,self.context,outlook)
        self.learnset.view.yview_moveto(state.get('scroll',0));self.base_title.configure(text='Базовые характеристики · '+_entity_label(sp['name']));self.base_stats.set(sp)
        for w in self.base_abilities.winfo_children():w.destroy()
        label(self.base_abilities,'Возможные способности вида',11,MUTED)
        for n in sp['abilities']:
            a=ability(n,self.root);Button(self.base_abilities,_entity_label(a['name'])+' ↗',lambda n=n:__import__('pokemon_red.pokemon_ui',fromlist=['show_ability']).show_ability(self.panel,n),anchor='w').pack(fill='x',pady=(5,0))
        self.base_matchups.set(dict(species_id=number,ability_id=0))
    def open_related(self,number):
        return self.panel.details.open_related_pokemon(number)
    def open_source(self):
        if self.selected==self.current_number:self.tabs.select(self.pages['source'])
        else:self.open_related(self.selected)
    def locale_changed(self):
        if self.parent.winfo_exists():
            self.update_identity();self.select_form(self.selected)
    def refresh(self,state):
        self.update_membership()
        if not self.uid:return
        state=state or {};monitor=self.panel.monitor
        if (self.context or {}).get('opponent'):rows=(state.get('battle') or {}).get('enemy_party',[])
        else:
            inv=getattr(monitor,'last_inventory',{}) or {};rows=state.get('party',[])+inv.get('boxes',[])+inv.get('daycare',[])
            if not any(m.get('uid')==self.uid for m in state.get('party',[])) and time.monotonic()-self.last_inventory>=2:
                self.last_inventory=time.monotonic();inv=monitor.inventory_snapshot();rows=state.get('party',[])+inv.get('boxes',[])+inv.get('daycare',[])
        current=next((m for m in rows if m.get('uid')==self.uid and m.get('checksum_valid',True)),None)
        if not current:return
        current=dict(current,**({'opponent':True} if (self.context or {}).get('opponent') else {}))
        if current==self.context:return
        previous=self.current_number;self.context=current;self.current_number=current['species_id'];self.update_identity()
        if self.owned:self.owned.update_detail(current)
        if self.selected==previous and self.current_number!=previous:self.select_form(self.current_number)
        else:
            self.forms.set(self.selected,self.current_number);self.learnset.context=current;self.learnset.choose()
