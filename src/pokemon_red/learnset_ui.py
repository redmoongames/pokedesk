from .entity_names import display_entity_names as _entity_label
from .i18n import search_matches,render
from .entity_names import entity_aliases
"""Compare learnset rows before opening a full article; never pop up on selection."""
from . import localized_tk as tk
from tkinter import ttk

from .scrolling import Scrollbar
from .catalog import move
from .ui import BG,CARD,TEXT,MUTED,GREEN,AMBER,BLUE,Button,Toggle,label
from .types_ui import TYPE_INFO
from .move_reference import power_text,accuracy_text,category_text


class LearnsetView:
    def __init__(self,parent,root,sp,context,open_move,*,annotations=None,embedded=False):
        from .pokemon_ui import tree
        self.parent=parent;self.root=root;self.sp=sp;self.context=context or {};self.open_move=open_move;self.selected=None;self.mapping={};self.annotations=annotations or {};self.embedded=embedded
        label(parent,'Приёмы по уровням · FireRed',12,bold=True)
        controls=tk.Frame(parent,bg=BG);controls.pack(fill='x',pady=(8,2));self.query=tk.StringVar(parent,value='')
        label(controls,'Поиск',11,MUTED,pack=False).pack(side='left',padx=(0,8));self.entry=tk.Entry(controls,textvariable=self.query,bg=CARD,fg=TEXT,insertbackground=TEXT,bd=0,font=('Helvetica',12));self.entry.pack(side='left',fill='x',expand=True,ipady=7)
        self.count=label(controls,'',10,MUTED,pack=False);self.count.pack(side='right',padx=(10,0))
        self.preview=tk.Frame(parent,bg=CARD,padx=12,pady=10);self.preview.pack(side='bottom',fill='x',pady=(8,0));self.title=label(self.preview,'Выбери приём',12,bold=True);self.meta=label(self.preview,'',10,MUTED);self.summary=label(self.preview,'',11,wraplength=640);self.summary.pack_configure(pady=(4,8));self.open=Button(self.preview,'Открыть приём →' if embedded else 'Подробнее о приёме ↗',self.open_selected,variant='ghost',height=30);self.open.pack(anchor='w')
        self.warning=label(self.preview,'',10,AMBER,wraplength=640);self.warning.pack(before=self.open,fill='x',pady=(0,6))
        self.only_unique=tk.BooleanVar(parent,value=False)
        if embedded:Toggle(parent,'★ Только приёмы до эволюции',self.only_unique,self.fill).pack(fill='x')
        self.view=tree(parent,[('level','Lv',38),('name','Приём',155),('type','Тип',105),('power','Сила',55),('state','После эволюции',155)] if embedded else [('level','Lv',42),('name','Приём',162),('type','Тип',112),('power','Сила',64),('accuracy','Точн.',70),('pp','PP',40),('state','Изучение',120)],height=6)
        for col in ('level','power') if embedded else ('level','power','accuracy','pp'):self.view.column(col,anchor='center')
        if embedded:
            for child in self.view.master.winfo_children():
                if isinstance(child,Scrollbar):child.configure(height=1)
            self.view.master.pack_configure(fill='x',expand=False);self.view.pack_configure(fill='x',expand=False)
            self.preview.pack_forget();self.preview.pack(side='top',fill='x',expand=False,pady=(8,0))
        self.row_styles={'exclusive':'EvoUnique.Trainer.Treeview','branch':'EvoBranch.Trainer.Treeview','normal':'Evo.Trainer.Treeview'}
        if embedded:
            styles=ttk.Style(self.view)
            for kind,name in self.row_styles.items():styles.map(name,background=[('selected','#594124' if kind=='exclusive' else '#273b49')],foreground=[('selected','#ffdc91' if kind=='exclusive' else AMBER if kind=='branch' else TEXT)])
            self.view.configure(style=self.row_styles['normal'])
        self.view.tag_configure('known',foreground=GREEN)
        self.view.tag_configure('exclusive',background='#463321',foreground='#ffdc91',font=('Helvetica',12,'bold'))
        self.view.tag_configure('branch',foreground=AMBER)
        self.view.configure(selectmode='browse');self.view.bind('<Button-1>',lambda _:self.view.focus_set(),add='+');self.view.bind('<<TreeviewSelect>>',self.choose);self.view.bind('<Double-1>',self.open_selected);self.view.bind('<Return>',self.open_selected)
        self.trace=self.query.trace_add('write',lambda *_:self.fill());parent.bind('<Destroy>',self.destroyed,add='+');parent.bind('<Configure>',self.resize,add='+');self.fill()
    def resize(self,event):
        width=max(280,event.width-30);self.summary.configure(wraplength=width);self.warning.configure(wraplength=width);self.meta.configure(wraplength=width)
        if self.embedded:self.view.configure(displaycolumns=('level','name','power','state') if event.width<600 else ('level','name','type','power','state'))
    def set_species(self,sp,context,annotations):
        self.sp=sp;self.context=context or {};self.annotations=annotations;self.fill()
    def destroyed(self,event):
        if event.widget is self.parent:self.query.trace_remove('write',self.trace)
    def fill(self):
        selected=self.selected;self.view.delete(*self.view.get_children());self.mapping={};known={m['id'] for m in self.context.get('moves',[])};q=self.query.get().strip().casefold()
        for i,row in enumerate(self.sp['learnset']):
            m=move(row['move'],self.root);type_name=TYPE_INFO[m['type_id']][0]
            if not search_matches(q,entity_aliases('moves',m['id']),type_name,render(type_name,locale='en'),m['description'],m.get('description_en',''),category_text(m)):continue
            info=self.annotations.get(m['id'],{});kind=info.get('kind')
            if self.only_unique.get() and kind not in ('exclusive','branch'):continue
            state='Известен' if m['id'] in known else 'Был на Lv '+str(row['level']) if self.context and row['level']<=self.context['level'] else 'На Lv '+str(row['level'])
            tags=('known',) if m['id'] in known else ()
            if self.embedded:
                state={'exclusive':'★ Только здесь','branch':'△ Часть веток','later':'У поздней формы'}.get(kind,'Есть дальше' if kind else 'Конечная форма')
                if kind in ('exclusive','branch'):tags=(kind,)
                if m['id'] in known:state+=' · знает'
            key=str(i);self.mapping[key]=m['id']
            values=(row['level'],_entity_label(m['name']),type_name,power_text(m),state) if self.embedded else (row['level'],_entity_label(m['name']),type_name,power_text(m),accuracy_text(m),m['pp'],state)
            self.view.insert('','end',iid=key,values=values,tags=tags)
        if self.embedded:self.view.configure(height=max(1,min(6,len(self.mapping))))
        self.count.configure(text=f"{len(self.mapping)} / {len(self.sp['learnset'])}")
        keys=list(self.mapping)
        if keys:
            key=next((k for k in keys if self.mapping[k]==selected),next((k for k in keys if self.mapping[k] in known),keys[0]));self.view.selection_set(key);self.choose();self.view.see(key)
        else:self.selected=None;self.warning.configure(text='');self.title.configure(text='Ничего не найдено');self.meta.configure(text='');self.summary.configure(text='Для этой формы нет подходящих приёмов. Выключи фильтр ★ или измени поиск.' if self.only_unique.get() else 'Попробуй название, тип или эффект: например, «психический» или «паралич».');self.open.configure(state='disabled')
    def choose(self,_=None):
        selection=self.view.selection()
        if not selection or selection[0] not in self.mapping:return
        self.selected=self.mapping[selection[0]];m=move(self.selected,self.root);self.title.configure(text=_entity_label(m['name']));self.meta.configure(text=TYPE_INFO[m['type_id']][0]+' · '+category_text(m)+f" · PP {m['pp']} · точность {accuracy_text(m)}");self.summary.configure(text=m['description']);self.open.configure(state='normal')
        from .evolution_reference import outlook_text
        from .catalog import catalog
        if self.embedded:
            kind=self.annotations.get(self.selected,{}).get('kind');self.view.configure(style=self.row_styles.get(kind,self.row_styles['normal']))
        self.warning.configure(text=outlook_text(self.annotations.get(self.selected),catalog(self.root)['species'],known=any(a['id']==self.selected for a in self.context.get('moves',[]))))
    def open_selected(self,_=None):
        if self.selected:self.open_move(self.selected)
        return 'break'
