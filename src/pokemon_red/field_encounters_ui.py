from .i18n import t
"""The left sidebar outside battles: local encounters and capture setup."""
from . import localized_tk as tk
from tkinter import ttk
from .ui import BG,TEXT,MUTED,GREEN,BLUE,Button,Select,label
from .table import Table
from .catalog import species
from .locations import location_name
from .location_reference import METHODS
from .field_encounters import populations,land_tiles
from .sprites import sprite
from .tooltips import Tooltip

class FieldEncountersView:
    def __init__(self,monitor,parent):
        self.monitor=monitor;self.root=monitor.folder;self.state={};self.key=None;self.map=None;self.rows={};self.photo=None;self.photos={}
        self.frame=tk.Frame(parent,bg=BG,padx=12,pady=12)
        label(self.frame,'Дикие встречи',17,bold=True);self.location=label(self.frame,'',12,BLUE,wraplength=300);self.location.pack_configure(pady=(6,3))
        self.where=label(self.frame,'',10,MUTED,wraplength=300);self.where.pack_configure(pady=(0,7))
        self.method=tk.StringVar();self.picker=Select(self.frame,self.method,command=lambda _:self.fill(),height=31,font=('Helvetica',10));self.picker.pack(fill='x',pady=(0,7))
        self.note=label(self.frame,'Проценты — доля вида среди встреч, не шанс боя за шаг.',9,MUTED,wraplength=300);self.note.pack_configure(pady=(0,7))
        self.table_frame=tk.Frame(self.frame,bg=BG);self.table_frame.pack(fill='both',expand=True)
        ttk.Style(self.frame).configure('EncounterIcons.Treeview',rowheight=40)
        self.table=Table(self.table_frame,columns=('name','chance','level'),show='tree headings',height=6,selectmode='browse',style='EncounterIcons.Treeview')
        self.table.column('#0',width=40,minwidth=40,stretch=False);self.table.heading('#0',text='')
        for key,title,width,minimum in [('name','Pokémon',150,90),('chance','Шанс',62,55),('level','Lv',65,55)]:
            self.table.heading(key,text=title);self.table.column(key,width=width,minwidth=minimum,stretch=key=='name',anchor='w' if key=='name' else 'center')
        self.table.pack(fill='both');self.table.bind('<<TreeviewSelect>>',lambda _:self.select());self.table.bind('<Return>',lambda _:self.open_capture())
        footer=tk.Frame(self.frame,bg=BG);footer.pack(side='bottom',fill='x',before=self.table_frame)
        hero=tk.Frame(footer,bg=BG);hero.pack(fill='x',pady=(9,3));self.portrait=tk.Label(hero,bg=BG);self.portrait.pack(side='left');self.detail=label(hero,'',10,MUTED,wraplength=250,pack=False);self.detail.pack(side='left',fill='x',expand=True,padx=(5,0));self.detail_hint=Tooltip(self.detail)
        self.inspect=Button(footer,'Открыть Pokémon ↗',self.open_species,variant='ghost',height=30,font=('Helvetica',10));self.inspect.pack(fill='x')
        self.capture=Button(footer,t('capture.action'),self.open_capture,variant='primary',height=35);self.capture.pack(fill='x',pady=(5,0))
        self.saved=Button(footer,t('capture.saved_title'),self.open_saved,variant='ghost',height=31);self.saved.pack(fill='x')
        self.frame.bind('<Configure>',self.resize)
    def resize(self,event):
        for widget in (self.location,self.where,self.note):widget.configure(wraplength=max(220,event.width-26))
        self.detail.configure(wraplength=max(160,event.width-80))
    def update(self,state):
        self.state=state;name=(state.get('map') or {}).get('name');groups=populations(self.root).get(name,{}) if state.get('ready') else {}
        position=state.get('position') or {};tile=land_tiles(self.root,name).get((position.get('x'),position.get('y'))) if groups else None
        self.where.configure(text=('Вы в траве' if tile=='grass' else 'Вы в пещере / зоне наземных встреч' if tile=='cave' else 'Встречи в этой локации') if groups else 'Здесь нет обычных диких встреч')
        key=(getattr(self.monitor,'generation',0),name,bool(groups))
        if self.key==key:return
        self.key=key;self.map=name;self.groups=groups;self.location.configure(text=location_name(name) if name else 'Дождитесь загрузки игры')
        self.methods={METHODS.get(method,method):method for method in groups};self.picker.configure(values=list(self.methods),state='normal' if groups else 'disabled')
        default='land_mons' if 'land_mons' in groups else next(iter(groups),'')
        self.method.set(METHODS.get(default,default));self.fill()
    def fill(self):
        previous=getattr(self,'selected',None);self.table.delete(*self.table.get_children());self.rows={}
        method=getattr(self,'methods',{}).get(self.method.get());self.active_method=method
        for row in getattr(self,'groups',{}).get(method,[]):
            key=str(row['species_id']);self.rows[key]=row;photo=sprite(self.frame,self.root,row['species_id'],scale=.5);self.photos[key]=photo;self.table.insert('','end',iid=key,image=photo or '',values=(species(row['species_id'],self.root)['name'],str(row['probability'])+'%',row['level_label']))
        self.table.configure(height=max(1,min(8,len(self.rows))))
        selected=previous if previous in self.rows else next(iter(self.rows),None)
        if selected:self.table.selection_set(selected)
        self.select()
    def select(self):
        selection=self.table.selection();self.selected=selection[0] if selection else None;row=self.rows.get(self.selected)
        for button in (self.inspect,self.capture):button.configure(state='normal' if row else 'disabled')
        if not row:self.detail.configure(text='Выберите место с дикими Pokémon.');self.portrait.configure(image='');self.photo=None;return
        name=species(row['species_id'],self.root)['name'];self.photo=sprite(self.frame,self.root,row['species_id'],scale=.5);self.portrait.configure(image=self.photo or '')
        self.detail.configure(text=name+' · '+str(row['probability'])+'%\nLv '+row['level_label']+('\n'+row['note'] if row.get('note') else ''));self.detail_hint.text=row.get('note','');self.capture.configure(text=t('capture.action_for',name=name))
    def trainer_panel(self):
        if getattr(self.monitor,'panel',None) is None:self.monitor.show_panel()
        return self.monitor.panel
    def open_saved(self):return self.monitor.battle_panel.open_saved_encounters(self.trainer_panel())
    def open_species(self):
        row=self.rows.get(getattr(self,'selected',None))
        if row:self.trainer_panel().open_pokemon(species_id=row['species_id'])
    def open_capture(self):
        row=self.rows.get(getattr(self,'selected',None))
        if not row or self.state.get('in_battle') or (self.state.get('map') or {}).get('name')!=self.map:return
        from .catch_view import open_autocatch
        return open_autocatch(self.trainer_panel(),row['species_id'],route=self.map,method=self.active_method)
