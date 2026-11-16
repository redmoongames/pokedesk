from .i18n import t,subscribe,unsubscribe
from .entity_names import ability_name,item_name,nature_name
from .entity_names import display_entity_names as _entity_label
from .ui import cached_font
"""Party overview and reusable current-Pokémon summary for the shared detail page."""
from . import localized_tk as tk
from tkinter import font as tkfont

from .ui import BG,CARD,TEXT,MUTED,GREEN,BLUE,Button,label,card,rounded,short
from .sprites import PokemonCard
from .catalog import species,catalog,ability
from .tooltips import Tooltip
from .types_ui import Badges,Matchups,draw_type,types_for,TYPE_INFO

from .stat_values_ui import StatValues,STATS,HIDDEN_STATS,STAT_NAMES
from .natures import nature_effect

class MoveCard(tk.Canvas):
    def __init__(self,parent,panel):
        super().__init__(parent,height=68,width=200,bg=BG,highlightthickness=0,bd=0,takefocus=True,cursor='hand2');self.panel=panel;self.move=None;self.hint=Tooltip(self)
        self.bind('<Configure>',lambda _:self.draw());self.bind('<Button-1>',lambda _:self.open());self.bind('<Return>',lambda _:self.open())
    def set(self,move):self.move=move;self.hint.text=(move or {}).get('description','');self.draw()
    def open(self):
        if self.move:__import__('pokemon_red.pokemon_ui',fromlist=['show_move']).show_move(self.panel,self.move['id'])
    def draw(self):
        if not self.winfo_exists():return
        self.delete('all');w=self.winfo_width();rounded(self,1,1,w-1,67,8,fill=CARD,outline='#2a3b4d')
        if not self.move:self.create_text(12,33,text='Пустой слот',font=('Helvetica',11),fill=MUTED,anchor='w');return
        m=self.move;font=cached_font(self,('Helvetica',11,'bold'));self.create_text(12,18,text=short(_entity_label(m['name']),w-24,font),font=font,fill=TEXT,anchor='w')
        draw_type(self,20,46,m['type_id'],size=16)
        detail=f"{TYPE_INFO.get(m['type_id'],TYPE_INFO[9])[1]} · PP {m.get('current_pp','—')}/{m.get('max_pp',m['pp'])}"
        if m['power']>1:detail+=' · сила '+str(m['power'])
        self.create_text(34,46,text=short(detail,w-46,cached_font(self,('Helvetica',10))),font=('Helvetica',10),fill=BLUE,anchor='w')

class OwnedDetail:
    def __init__(self,panel,parent,on_back=None,back_title='← Отряд'):
        self.panel=panel;self.root=panel.monitor.folder;self.context=None;self.selected_uid=None
        self.frame=self.detail=tk.Frame(parent,bg=BG)
        if on_back:
            top=tk.Frame(self.detail,bg=BG);top.pack(fill='x',pady=(0,10));self.back_button=Button(top,back_title,on_back,variant='ghost');self.back_button.pack(side='left')
        self.hero=PokemonCard(self.detail,self.root);self.hero.pack(fill='x');self.identity=label(self.detail,'',10,MUTED);self.identity.pack_configure(pady=(5,8))
        self.matchups=Matchups(self.detail,self.root);self.matchups.pack(fill='x',pady=(0,8))
        self.ability_button=Button(self.detail,'',self.open_ability,anchor='w');self.ability_button.pack(fill='x',pady=(0,6));self.ability_hint=Tooltip(self.ability_button)
        self.nature=label(self.detail,'',9,MUTED);self.nature.pack_configure(pady=(0,4));self.nature_hint=Tooltip(self.nature)
        self.stat_grid=StatValues(self.detail);self.stat_grid.pack(fill='x')
        self.stats=self.stat_grid.stats;self.stat_values=self.stat_grid.values;self.stat_hints=self.stat_grid.hints;self.hp_hint=self.stat_grid.hp_hint
        label(self.detail,'Известные приёмы',12,bold=True).pack_configure(pady=(10,8));moves=tk.Frame(self.detail,bg=BG);moves.pack(fill='x');moves.columnconfigure((0,1),weight=1,uniform='moves');self.moves=[]
        for i in range(4):
            w=MoveCard(moves,panel);w.grid(row=i//2,column=i%2,sticky='ew',padx=(0 if i%2==0 else 5,5 if i%2==0 else 0),pady=(0,8));self.moves.append(w)
        self.item=label(self.detail,'',11,MUTED);self.item.pack_configure(pady=6);subscribe(self)
        self.frame.bind('<Destroy>',lambda e:unsubscribe(self) if e.widget is self.frame else None,add='+')
    def locale_changed(self):
        if self.frame.winfo_exists() and self.context:self.update_detail(self.context)
    def open_ability(self):
        if self.context:__import__('pokemon_red.pokemon_ui',fromlist=['show_ability']).show_ability(self.panel,self.context.get('ability_id',0))
    def update_detail(self,mon):
        self.context=dict(mon);self.hero.set(mon);sp=species(mon['species_id'],self.root);source='Противник' if mon.get('opponent') else __import__('pokemon_red.collection',fromlist=['location_label']).location_label(mon);self.identity.configure(text=source+(' · уровень при передаче' if mon.get('location')=='daycare' else '')+' · Дружба: '+str(mon.get('friendship','—')));self.matchups.set(mon)
        a=ability(mon.get('ability_id',0),self.root);self.ability_button.configure(text=ability_name(mon.get('ability_id',0)));self.ability_hint.text=a.get('mechanics',{}).get('text') or t('entity.abilities.'+str(mon.get('ability_id',0))+'.description')
        nature=nature_effect(mon.get('nature'))
        if nature:
            self.nature.configure(text=t('pokemon.nature',name=nature_name(mon['nature']))+(t('pokemon.no_nature_change') if not nature['modifiers'] else ''))
            changes='\n'.join(STAT_NAMES[key]+f': {modifier:+d}%' for key,modifier in nature['modifiers'].items())
            tooltip=('Характер '+nature_name(mon['nature'])+'\n'+changes+'\nВлияние уже учтено в характеристиках. HP не меняется.' if changes else 'Нейтральный характер: все характеристики без изменений (0%).')
        else:
            self.nature.configure(text='Характер: нет данных');tooltip='Характер этого Pokémon пока неизвестен.'
        if self.nature_hint.text!=tooltip:self.nature_hint.hide();self.nature_hint.text=tooltip
        self.stat_grid.set(mon)
        for i,w in enumerate(self.moves):w.set(mon['moves'][i] if i<len(mon['moves']) else None)
        item=item_name(mon['held_item']) if mon.get('held_item') else t('pokemon.no_item');self.item.configure(text=t('pokemon.held_item',item=item))
    def set(self,mon):
        self.selected_uid=mon['uid'];self.update_detail(mon)
    def refresh(self,state,inventory=None):
        if not self.selected_uid:return
        rows=(state or {}).get('party',[])+(inventory or {}).get('boxes',[])+(inventory or {}).get('daycare',[])
        current=next((m for m in rows if m['uid']==self.selected_uid),None)
        if current:self.update_detail(current)

class TeamView:
    def __init__(self,panel,parent):
        self.panel=panel;self.monitor=panel.monitor;self.root=self.monitor.folder
        self.home=tk.Frame(parent,bg=BG);self.home.pack(fill='x')
        head=tk.Frame(self.home,bg=BG);head.pack(fill='x',pady=(0,12));Button(head,t('party_edit.edit'),panel.open_party_editor,height=32).pack(side='right',padx=(6,0));Button(head,t('design.train'),panel.open_training,variant='primary',height=32).pack(side='right',padx=(10,0));label(head,'Отряд',20,bold=True,pack=False).pack(side='left');self.count=label(head,'',11,MUTED,pack=False);self.count.pack(side='right')
        from .party_row import PartyRow
        grid=tk.Frame(self.home,bg=BG);grid.pack(fill='x');grid.columnconfigure(0,weight=1);self.cards=[]
        for i in range(6):
            w=PartyRow(grid,self.root,lambda i=i:self.inspect_slot(i));w.grid(row=i,column=0,sticky='ew',pady=(0,2));self.cards.append(w)
        self.empty=label(self.home,'',11,MUTED);self.progress=label(self.home,'',11,MUTED);self.progress.pack_configure(pady=(8,4));self.badges=label(self.home,'',11,MUTED)
        self.battle_button=Button(self.home,'Панель боя ↗',self.monitor.show_battle_panel,variant='ghost');self.battle_button.pack(fill='x',pady=6)
    def inspect_slot(self,index):
        party=(self.monitor.last_state or {}).get('party',[])
        if index<len(party):self.inspect(party[index]['uid'],party[index])
    def inspect(self,uid,mon=None):return self.panel.open_pokemon(uid=uid,mon=mon)
    def refresh(self,state):
        from .party_row import party_row_signature
        data=state or {}
        signature=(tuple(party_row_signature(m) for m in data.get('party',[])),repr(data.get('pokedex')),tuple(data.get('badges') or ()),bool(data.get('battle')))
        if signature==getattr(self,'_signature',None):return
        self._signature=signature
        party=(state or {}).get('party',[]);self.count.configure(text=f'{len(party)} / 6')
        for i,w in enumerate(self.cards):
            if i<len(party):w.grid();w.set(party[i])
            else:w.grid_remove()
        self.empty.configure(text='' if party else 'Получи первого Pokémon в основном окне игры.')
        dex=(state or {}).get('pokedex');self.progress.configure(text=f"Pokédex · {dex['caught']} поймано / {dex['seen']} увидено" if dex else '');self.badges.configure(text=t('design.badges',count=len((state or {}).get('badges',[])),total=8))
        if (state or {}).get('battle'):self.battle_button.pack(fill='x',pady=6)
        else:self.battle_button.pack_forget()
