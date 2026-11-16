from .entity_names import pokemon_name
from .i18n import literal
from .entity_names import display_entity_names as _entity_label
from .table import Table
from .ui import cached_font
from .i18n import t
"""Owned collection: searchable party + all PC boxes, with shared details."""
import time
from . import localized_tk as tk
from tkinter import ttk

from .ui import BG,CARD,HOVER,BORDER,TEXT,MUTED,GREEN,BLUE,AMBER,Button,Segments,Toggle,Select,label,rounded,short
from .sprites import sprite
from .types_ui import draw_type,types_for,TYPE_INFO
from .collection import owned_pokemon,filter_pokemon,location_label,read_daycare
from .catalog import species
from .tooltips import Tooltip

class CollectionCard(tk.Canvas):
    def __init__(self,parent,root,mon,command):
        super().__init__(parent,height=112,width=240,bg=BG,highlightthickness=0,bd=0,takefocus=True,cursor='hand2')
        self.root_path=root;self.mon=mon;self.command=command;self.hover=False;self.photo=sprite(self,root,mon['species_id'],shiny=mon.get('shiny',False));self.hint=Tooltip(self,('Shiny · ' if mon.get('shiny') else '')+mon['species']+'\n'+location_label(mon))
        self.bind('<Configure>',lambda _:self.draw());self.bind('<Enter>',lambda _:self.over(True));self.bind('<Leave>',lambda _:self.over(False));self.bind('<FocusIn>',lambda _:self.draw());self.bind('<FocusOut>',lambda _:self.draw())
        self.bind('<Button-1>',self.invoke);self.bind('<Return>',self.invoke);self.bind('<space>',self.invoke)
    def invoke(self,_=None):self.command();return 'break'
    def over(self,value):self.hover=value;self.draw()
    def draw(self):
        self.delete('all');m=self.mon;w=max(100,self.winfo_width());rounded(self,1,1,w-1,111,9,fill=HOVER if self.hover else CARD,outline=GREEN if self.focus_get() is self else BORDER)
        if self.photo:self.create_image(36,37,image=self.photo)
        f=cached_font(self,('Helvetica',11,'bold'));title=literal(('✦ ' if m.get('shiny') else '')+pokemon_name(m))
        self.create_text(78,20,text=short(title,w-136,f),anchor='w',font=f,fill=AMBER if m.get('shiny') else TEXT);self.create_text(w-12,20,text=f"Lv {m['level']}",anchor='e',font=('Helvetica',10),fill=MUTED)
        sp=species(m['species_id'],self.root_path);subtitle=m['species'] if m.get('nickname')!=m['species'] else f"#{sp.get('national_id',m['species_id']):03d}"+(' · Shiny' if m.get('shiny') else '')
        self.create_text(78,43,text=short(subtitle,w-90,cached_font(self,('Helvetica',10))),anchor='w',font=('Helvetica',10),fill=MUTED)
        self.create_text(78,65,text=short(location_label(m),w-90,cached_font(self,('Helvetica',9))),anchor='w',font=('Helvetica',9),fill=GREEN if m['location']=='party' else MUTED)
        x=20
        for typ in types_for(m,self.root_path):
            draw_type(self,x,94,typ,size=16);text=TYPE_INFO.get(typ,TYPE_INFO[9])[1];self.create_text(x+12,94,text=text,font=('Helvetica',9),fill=TEXT,anchor='w');x+=28+cached_font(self,('Helvetica',9)).measure(text)

SECTIONS=[('party','Отряд'),('owned','Мои покемоны'),('dex','Покедекс'),('acquisition','Автоловля')]

class DexList:
    """A single native table keeps all 386 species searchable without 386 widgets."""
    def __init__(self,hub,parent):
        from .dex_reference import dex_rows
        from .scrolling import Scrollbar
        self.hub=hub;self.rows=dex_rows(hub.root);self.signature=None
        label(parent,'✓ — есть в коллекции · нажми на вид, чтобы открыть карточку',10,MUTED,wraplength=490).pack_configure(pady=(0,7))
        box=tk.Frame(parent,bg=BG);box.pack(fill='x')
        self.view=Table(box,columns=('number','name','type','source'),show='headings',height=13,selectmode='browse',style='Trainer.Treeview')
        for key,title,width in [('number','№',40),('name','Вид',155),('type','Тип',125),('source','Получение',160)]:
            self.view.heading(key,text=title);self.view.column(key,width=width,minwidth=width if key=='number' else 90,stretch=key!='number')
        self.view.column('number',anchor='center')
        scroll=Scrollbar(box,command=self.view.yview,height=1);scroll.pack(side='right',fill='y');self.view.configure(yscrollcommand=scroll.set);self.view.pack(fill='x',expand=True)
        for key,color in [('firered',TEXT),('leafgreen',BLUE),('other',MUTED),('event',AMBER)]:self.view.tag_configure(key,foreground=color)
        self.view.bind('<ButtonRelease-1>',self.clicked);self.view.bind('<Return>',self.open_selected);self.view.bind('<space>',self.open_selected)
        self.empty=label(parent,'',11,MUTED,wraplength=480)
        label(parent,'FireRed — получение в этой версии, иногда через эволюцию или обмен. LeafGreen и «Другая игра» — нужен перенос. «Особое получение» — событие или специальный источник. Подробности — в карточке.',10,MUTED,wraplength=490).pack_configure(pady=(7,0))
        hub.canvas.bind('<Configure>',self.resize,add='+')
    def resize(self,event=None):
        if self.hub.section.get()!='dex':return
        height=self.hub.canvas.winfo_height();rowheight=int(ttk.Style(self.view).lookup('Trainer.Treeview','rowheight') or 34)
        self.view.configure(height=max(1,min(len(self.view.get_children()),24,max(1,(height-165)//rowheight))))
    def fill(self,query):
        from .dex_reference import filter_dex,origin,origin_label
        rows=filter_dex(self.rows,query,self.hub.category_values.get(self.hub.dex_category.get(),'all'),self.hub.root);owned={m['species_id'] for m in self.hub.rows}
        key=tuple((s['id'],s['id'] in owned) for s in rows)
        if key==self.signature:return
        self.signature=key;selected=self.view.selection();scroll=self.view.yview()[0];children=self.view.get_children()
        if children:self.view.delete(*children)
        for sp in rows:
            n=sp['id'];self.view.insert('','end',iid=str(n),values=(f"{sp['national_id']:03}",('✓ ' if n in owned else '')+_entity_label(sp['name']).title(),' / '.join(TYPE_INFO[t][1] for t in sp['type_ids']),origin_label(n,self.hub.root)),tags=(origin(n,self.hub.root)['category'],))
        if selected and self.view.exists(selected[0]):self.view.selection_set(selected[0])
        self.view.yview_moveto(scroll);self.empty.configure(text='' if rows else 'Ничего не найдено. Измени поиск или источник получения.');self.resize()
    def clicked(self,event):
        if self.view.identify_region(event.x,event.y) not in ('cell','tree'):return
        row=self.view.identify_row(event.y)
        if row:self.view.selection_set(row);self.open_selected()
    def open_selected(self,_=None):
        selected=self.view.selection()
        if selected:self.hub.panel.open_pokemon(species_id=int(selected[0]))
        return 'break'

class CollectionView:
    def __init__(self,panel,parent):
        self.panel=panel;self.monitor=panel.monitor;self.root=self.monitor.folder;self.rows=[];self.widgets=[];self.signature=None;self.last_poll=0
        self.parent=parent;self.container=panel.page_containers['collection'];self.canvas=panel.page_canvases[str(self.container)]
        self.section=tk.StringVar(value='party' if getattr(panel,'workspace',False) else 'owned');self.current=self.section.get();self.queries={key:tk.StringVar() for key,_ in SECTIONS if key!='acquisition'};self.scrolls={};self.dex=None;self.acquisition=None
        # Navigation and the subsection's query stay visible while the list scrolls.
        self.header=tk.Frame(self.container,bg=BG,padx=4,pady=8);self.header.pack(side='top',fill='x',before=self.canvas)
        self.navigation=Segments(self.header,([('party',t('workspace.party')),('owned',t('workspace.collection')),('dex',t('workspace.dex'))] if getattr(panel,'workspace',False) else [('owned',t('design.owned')),('dex','Pokédex'),('acquisition',t('design.hunts'))]),self.section,self.select);self.navigation.pack(fill='x',pady=(0,9))
        for _,button in self.navigation.buttons:button.pack_forget()
        for i,(_,button) in enumerate(self.navigation.buttons):
            button.font.configure(size=10);width=button.font.measure(button.text)+28
            button.configure(width=1);self.navigation.columnconfigure(i,weight=width)
            button.grid(row=0,column=i,sticky='ew',padx=(0 if i==0 else 4,0))
        self.search=tk.Frame(self.header,bg=CARD,padx=10,pady=8);self.search.pack(fill='x')
        self.search_title=label(self.search,'Поиск в отряде',10,MUTED,pack=False);self.search_title.pack(side='left',padx=(0,10))
        self.query=self.queries['party'];self.entry=tk.Entry(self.search,textvariable=self.query,bg=CARD,fg=TEXT,insertbackground=TEXT,bd=0,font=('Helvetica',12));self.entry.pack(side='left',fill='x',expand=True)
        clear=Button(self.search,'×',lambda:self.query.set(''),variant='ghost',width=40,height=24);clear.pack(side='right',padx=(5,0));Tooltip(clear,'Очистить поиск в этом разделе')
        self.filters=tk.Frame(self.header,bg=BG);self.filters.pack(fill='x',pady=(6,0));self.only_shiny=tk.BooleanVar(value=False)
        self.shiny_toggle=Toggle(self.filters,'Только Shiny',self.only_shiny,self.render)
        from .dex_reference import edition_text
        self.dex_category=tk.StringVar(value=edition_text('FireRed',self.root));self.category_values={'Все источники':'all','FireRed':'firered','Из LeafGreen':'leafgreen','Из другой игры':'other','Особое получение':'event'}
        self.category_values={edition_text(k,self.root):v for k,v in self.category_values.items()}
        self.dex_filter=Select(self.filters,self.dex_category,values=list(self.category_values),command=lambda _:self.render())
        self.bodies={key:tk.Frame(parent,bg=BG) for key,_ in SECTIONS};self.bodies['party'].pack(fill='x')
        self.card_hosts={};self.empty={}
        for key in ('party','owned'):
            body=self.bodies[key];grid=tk.Frame(body,bg=BG);grid.pack(fill='x');grid.columnconfigure((0,1),weight=1,uniform='collection');self.card_hosts[key]=grid;self.empty[key]=label(body,'',12,MUTED,wraplength=480)
        self.party_view=None
        if getattr(panel,'workspace',False):
            from .team_view import TeamView
            self.card_hosts['party'].pack_forget();self.empty['party'].pack_forget()
            self.party_view=TeamView(panel,self.bodies['party']);panel.team_view=self.party_view;panel.party_cards=self.party_view.cards
        self.cached_cards={};self.signatures={};self.traces=[]
        for key,var in self.queries.items():self.traces.append((var,var.trace_add('write',lambda *_,k=key:self.query_changed(k))))
        parent.bind('<Destroy>',self.destroyed,add='+');self.select(self.current)
    def destroyed(self,event):
        if event.widget is not self.parent:return
        for var,trace in self.traces:var.trace_remove('write',trace)
        if self.acquisition:self.acquisition.close()
    def select(self,key):
        if key not in self.bodies:raise ValueError(key)
        old=self.current
        if old!=key:self.scrolls[old]=self.canvas.yview()[0]
        for body in self.bodies.values():body.pack_forget()
        self.current=key;self.section.set(key);self.bodies[key].pack(fill='x')
        self.shiny_toggle.pack_forget();self.dex_filter.pack_forget()
        if key=='party' and self.party_view:
            self.search.pack_forget();self.filters.pack_forget();self.party_view.refresh(self.monitor.last_state)
        elif key=='acquisition':
            self.search.pack_forget();self.filters.pack_forget();self.ensure_acquisition()
        else:
            self.search.pack(fill='x');self.query=self.queries[key];self.entry.configure(textvariable=self.query)
            self.search_title.configure(text={'party':'Поиск в отряде','owned':'Поиск в коллекции','dex':'Поиск по видам'}[key])
            if key in ('owned','dex'):
                self.filters.pack(fill='x',pady=(6,0))
                if key=='owned':self.shiny_toggle.pack(fill='x')
                else:self.dex_filter.pack(fill='x')
            else:self.filters.pack_forget()
            self.render()
        if old!=key:
            self.canvas.update_idletasks();self.canvas.yview_moveto(self.scrolls.get(key,0))
        self.header.lift();self.panel.footer.lift()
    def ensure_acquisition(self):
        if self.acquisition is None:
            from .acquisition_view import AcquisitionView
            body=self.bodies['acquisition'];dock=tk.Frame(body,bg=BG);dock.pack(side='bottom',fill='x')
            self.acquisition=AcquisitionView(self.panel,body,dock,embedded=True);self.acquisition.actions.pack(fill='x')
            row=tk.Frame(self.acquisition.actions,bg=BG);row.pack(fill='x',pady=(6,0))
            Button(row,'Взять управление · F9',self.monitor.take_control,variant='primary').pack(side='left',fill='x',expand=True)
            Button(row,'Пауза / продолжить',self.monitor.toggle_pause).pack(side='right',padx=(6,0))
        self.acquisition.refresh();return self.acquisition
    def open_acquisition(self):
        if getattr(self.panel,'workspace',False):return self.panel.open_acquisition()
        self.panel.show('collection');self.select('acquisition');return self.acquisition
    def query_changed(self,key):
        if key!=self.current:return
        self.render();self.canvas.yview_moveto(0)
        if key=='dex' and self.dex:self.dex.view.yview_moveto(0)
    def refresh(self,state=None,force=False):
        if self.current=='party' and self.party_view:
            self.party_view.refresh(state or self.monitor.last_state);return
        # No inventory reads or card reconstruction for the background-hunt screen.
        if self.current=='acquisition':
            if self.acquisition:self.acquisition.refresh()
            return
        if force or time.monotonic()-self.last_poll>=2:
            self.last_poll=time.monotonic();inv=self.monitor.inventory_snapshot()
            if inv.get('ready'):
                self.rows=owned_pokemon(dict(inv,daycare=inv.get('daycare',[])));self.render()
    def render(self):
        key=self.current
        if key=='acquisition' or key=='party' and self.party_view:return
        if key=='dex':
            if self.dex is None:self.dex=DexList(self,self.bodies['dex'])
            self.dex.fill(self.query.get());return
        rows=filter_pokemon(self.rows,self.query.get(),'party' if key=='party' else 'shiny' if self.only_shiny.get() else 'all')
        signature=tuple((m['uid'],m['species_id'],m['level'],m.get('nickname'),m.get('shiny'),m['location'],m.get('slot'),m.get('box'),m.get('box_slot'),m.get('daycare_name')) for m in rows)
        self.empty[key].configure(text='Ничего не найдено · измени поиск'+(' или выключи Shiny' if key=='owned' and self.only_shiny.get() else '') if self.rows and not rows else 'Покемоны появятся после загрузки игры' if not self.rows else '')
        if signature==self.signatures.get(key):return
        self.signatures[key]=signature
        for w in self.cached_cards.get(key,[]):w.destroy()
        cards=[]
        for i,mon in enumerate(rows):
            w=CollectionCard(self.card_hosts[key],self.root,mon,lambda m=mon:self.inspect(m));w.grid(row=i,column=0,columnspan=2,sticky='ew',pady=(0,8));cards.append(w)
        self.cached_cards[key]=cards;self.widgets=cards
    def inspect(self,mon):return self.panel.open_pokemon(mon=mon)
