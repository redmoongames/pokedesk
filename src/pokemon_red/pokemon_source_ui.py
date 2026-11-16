from .entity_names import location_matches
from .i18n import render
"""Acquisition article: evolution conditions, family links and FireRed encounters."""
from . import localized_tk as tk
from .ui import BG,CARD,HOVER,TEXT,MUTED,GREEN,BLUE,Button,label,card,rounded,short,cached_font
from .table import Table
from .scrolling import Scrollbar
from .sprites import sprite
from .catalog import species
from .dex_reference import origin,origin_label,origin_description
from .pokemon_sources import source_data

class RelatedPokemon(tk.Canvas):
    def __init__(self,parent,root,record,command):
        super().__init__(parent,height=70,width=220,bg=BG,bd=0,highlightthickness=0,takefocus=True,cursor='hand2')
        self.record=record;self.command=command;self.hover=False;self.photo=sprite(self,root,record['species_id'])
        self.bind('<Configure>',lambda _:self.draw());self.bind('<Enter>',lambda _:self.over(True));self.bind('<Leave>',lambda _:self.over(False))
        self.bind('<FocusIn>',lambda _:self.draw());self.bind('<FocusOut>',lambda _:self.draw())
        self.bind('<Button-1>',self.invoke);self.bind('<Return>',self.invoke);self.bind('<space>',self.invoke)
    def over(self,value):self.hover=value;self.draw()
    def invoke(self,_=None):self.command(self.record['species_id']);return 'break'
    def draw(self):
        self.delete('all');w=max(1,self.winfo_width());r=self.record
        rounded(self,1,1,w-1,69,8,fill=HOVER if self.hover else CARD,outline=GREEN if self.focus_get() is self else '')
        if self.photo:self.create_image(30,35,image=self.photo)
        font=cached_font(self,('Helvetica',11,'bold'));small=cached_font(self,('Helvetica',9))
        self.create_text(60,24,text=short(r['name'].title(),max(1,w-90),font),font=font,fill=TEXT,anchor='w')
        self.create_text(60,46,text=short(r['relation'],max(1,w-78),small),font=small,fill=MUTED,anchor='w')
        self.create_text(w-17,25,text='→',font=('Helvetica',13),fill=BLUE)

class PokemonSourceView:
    def __init__(self,panel,parent,number,on_related):
        self.panel=panel;self.parent=parent;self.root=panel.monitor.folder;self.on_related=on_related;self.number=None
        self.title=label(parent,'',17,bold=True);self.origin=label(parent,'',11,BLUE);self.origin.pack_configure(pady=(5,12))
        self.evolution=card(parent);self.evolution.pack(fill='x');self.summary=label(parent,'',11,MUTED,wraplength=480);self.summary.pack_configure(pady=(8,0))
        self.related_title=label(parent,'Связанные покемоны',13,bold=True);self.related_title.pack_configure(pady=(18,8))
        self.related=tk.Frame(parent,bg=BG);self.related.pack(fill='x');self.related.columnconfigure((0,1),weight=1,uniform='related');self.links=[]
        label(parent,'Места ловли · FireRed',13,bold=True).pack_configure(pady=(18,7))
        label(parent,'Шанс — доля вида среди встреч выбранным способом, без Repel и других модификаторов. Это не вероятность поимки. Часть локаций открывается по сюжету.',10,MUTED,wraplength=480).pack_configure(pady=(0,10))
        self.search_row=tk.Frame(parent,bg=CARD,padx=10,pady=7);self.search_row.pack(fill='x');label(self.search_row,'Локация',10,MUTED,pack=False).pack(side='left',padx=(0,10))
        self.query=tk.StringVar();self.search=tk.Entry(self.search_row,textvariable=self.query,bg=CARD,fg=TEXT,insertbackground=TEXT,bd=0,font=('Helvetica',11));self.search.pack(side='left',fill='x',expand=True)
        self.table_frame=tk.Frame(parent,bg=BG);self.table_frame.pack(fill='x',pady=(8,0))
        self.table=Table(self.table_frame,columns=('name','method','chance','levels'),show='headings',style='Trainer.Treeview',height=1,selectmode='browse')
        for key,title,width,minimum,anchor in [('name','Локация',190,135,'w'),('method','Способ',100,75,'w'),('chance','Шанс',68,60,'center'),('levels','Lv',70,60,'center')]:
            self.table.heading(key,text=title);self.table.column(key,width=width,minwidth=minimum,anchor=anchor,stretch=key=='name')
        scroll=Scrollbar(self.table_frame,command=self.table.yview,height=1);scroll.pack(side='right',fill='y');self.table.configure(yscrollcommand=scroll.set);self.table.pack(fill='x',expand=True)
        self.table.tag_configure('here',foreground=GREEN);self.table.bind('<<TreeviewSelect>>',self.describe)
        self.table.heading('name',text='Локация ↗');self.table.tag_configure('link',foreground=BLUE);self.map_press=None
        self.table.bind('<ButtonPress-1>',self.location_pressed,add='+');self.table.bind('<ButtonRelease-1>',self.location_released,add='+')
        self.table.bind('<Return>',self.open_location);self.table.bind('<space>',self.open_location)
        self.table.bind('<Motion>',self.location_hover,add='+');self.table.bind('<Leave>',lambda _:self.table.configure(cursor=''),add='+')
        self.detail=label(parent,'',10,MUTED,wraplength=480);self.detail.pack_configure(pady=(7,0))
        self.empty=label(parent,'',11,MUTED,wraplength=480);self.empty.pack_configure(pady=(7,0))
        self.query_trace=self.query.trace_add('write',lambda *_:self.fill());parent.bind('<Configure>',self.resize,add='+');parent.bind('<Destroy>',self.destroyed,add='+')
        self.set_species(number)
    def destroyed(self,event):
        if event.widget is self.parent:self.query.trace_remove('write',self.query_trace)
    def resize(self,event):
        width=max(260,event.width-12)
        def wrap(parent):
            for child in parent.winfo_children():
                if isinstance(child,tk.Label) and int(child.cget('wraplength') or 0):child.configure(wraplength=max(220,width-(28 if parent is self.evolution else 0)))
        wrap(self.parent);wrap(self.evolution)
    def set_species(self,number):
        if self.number==number:return
        self.number=number;self.data=source_data(number,self.root);self.title.configure(text='Получение · '+self.data['name']);self.origin.configure(text=origin_label(number,self.root))
        for child in self.evolution.winfo_children():child.destroy()
        entry=origin(number,self.root);parents=self.data['parents']
        if parents:
            label(self.evolution,'Из предыдущей формы',10,MUTED)
            for p in parents:
                label(self.evolution,p['name'].title()+' → '+self.data['name'].title(),13,bold=True).pack_configure(pady=(6,4))
                label(self.evolution,p['condition'],11,wraplength=450)
            if self.data['needs_national_dex']:label(self.evolution,'Для эволюции в вид вне Канто нужен National Pokédex.',10,BLUE,wraplength=450).pack_configure(pady=(7,0))
        else:
            label(self.evolution,'Начальная форма',12,bold=True)
            label(self.evolution,'Предыдущей эволюционной формы нет.' if entry.get('method')=='wild' else origin_description(number,self.root),11,wraplength=450).pack_configure(pady=(5,0))
        special=entry.get('category')!='firered' or entry.get('method') in ('gift','breed')
        summary=[origin_description(number,self.root)] if parents and special else []
        summary.extend(self.data['alternatives']);self.summary.configure(text='\n'.join(summary))
        if summary:self.summary.pack(fill='x',pady=(8,0),after=self.evolution)
        else:self.summary.pack_forget()
        for child in self.related.winfo_children():child.destroy()
        self.links=[]
        for i,record in enumerate(self.data['related']):
            link=RelatedPokemon(self.related,self.root,record,self.on_related);link.grid(row=i//2,column=i%2,sticky='ew',padx=(0 if i%2==0 else 6,6 if i%2==0 else 0),pady=(0,6));self.links.append(link)
        if not self.links:label(self.related,'У этого вида нет других форм в эволюционной ветке.',10,MUTED,wraplength=480).grid(row=0,column=0,columnspan=2,sticky='w')
        self.query.set('');self.fill()
    def fill(self):
        if self.number is None:return
        if self.data['encounters']:self.search_row.pack(fill='x')
        query=self.query.get().strip().casefold();self.rows=[r for r in self.data['encounters'] if location_matches(query,r['map'],r['location'],r['method_label'],render(r['method_label'],locale='en'))]
        self.table.delete(*self.table.get_children());self.mapping={};current=(self.panel.monitor.last_state or {}).get('map',{}).get('name')
        for i,r in enumerate(self.rows):
            key=str(i);self.mapping[key]=r;self.table.insert('','end',iid=key,values=(r['location'],r['method_label'],str(r['probability'])+'%',r['level_label']),tags=('here',) if r['map']==current else ('link',))
        self.table.configure(height=max(1,min(8,len(self.rows))))
        if self.rows:
            self.table_frame.pack(fill='x',pady=(8,0),after=self.search_row);self.empty.pack_forget();self.detail.pack(fill='x',pady=(7,0),after=self.table_frame);self.table.selection_set('0');self.describe()
        else:
            self.table_frame.pack_forget();self.detail.pack_forget();self.empty.pack(fill='x',pady=(7,0));self.empty.configure(text='Ничего не найдено. Попробуй другое название локации.' if self.data['encounters'] else 'Обычных мест ловли в FireRed нет. Способ получения указан выше.')
        if self.data['encounters']:self.search_row.pack(fill='x',before=self.table_frame if self.rows else self.empty)
        else:self.search_row.pack_forget()
    def describe(self,_=None):
        selected=self.table.selection();record=self.mapping.get(selected[0]) if selected else None
        if not record:return
        self.detail.configure(text=record['location']+' · '+record['method_label']+' · Lv '+record['level_label']+(' · '+record['note'] if record['note'] else ''))
    def location_hover(self,event):
        if self.table.identify_row(event.y):self.table.configure(cursor='hand2')
    def location_pressed(self,event):
        row=self.table.identify_row(event.y)
        self.map_press=(row,event.x,event.y) if row else None
    def location_released(self,event):
        pressed=self.map_press;self.map_press=None
        if pressed and pressed[0]==self.table.identify_row(event.y) and abs(event.x-pressed[1])<=6 and abs(event.y-pressed[2])<=6:
            return self.open_location(row=pressed[0])
    def open_location(self,_=None,*,row=None):
        selected=self.table.selection();record=self.mapping.get(row if row is not None else selected[0] if selected else None)
        if record:self.panel.details.open_location_map(record['map'],encounter=record)
        return 'break'
