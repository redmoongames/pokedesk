from .i18n import t,literal,render,subscribe,unsubscribe
from .entity_names import item_name
from .i18n import search_matches
from .entity_names import entity_aliases
from .table import Table
"""Bag, storage and complete item library with contextual auto collection."""
import time
from . import localized_tk as tk
from tkinter import ttk

from .ui import BG,CARD,TEXT,MUTED,GREEN,AMBER,RED,Button,Segments,Select,label,card
from .scrolling import Scrollbar
from .inventory_library import holdings,library_rows,sort_rows
from .item_sources import availability
from .player_inventory import read_player_inventory,POCKETS
from .item_catalog import items,item_icon
from .item_delivery import eligible_couriers,quantity,verify_template,FINISHED,PRODUCTS,product,capacity_error

class InventoryView:
    def __init__(self,panel,parent):
        self.panel=panel;self.parent=parent;self.project=panel.monitor.folder;self.data=items(self.project);self.signature=None;self.last_poll=0;self.rows=[];self.photos={};self.queue_signature=None;self.courier_signature=None;self.counts={};self.sort_field="name";self.sort_reverse=False;self.selected_id=None;self.return_source="bag";self.detail_window=None;self.source_queries={};self.source_positions={};self.current_source='bag';self.changing_source=False
        head=tk.Frame(parent,bg=BG);head.pack(fill='x');self.count=label(head,'',10,MUTED,pack=False);self.count.pack(side='right')
        self.source=tk.StringVar(value='bag');self.tabs=Segments(parent,[('bag','Сумка'),('pc','Хранилище'),('library','Библиотека предметов')],self.source,lambda _:self.select());self.tabs.pack(fill='x',pady=(14,12));self.tabs.buttons[-1][1].configure(width=100);self.tabs.buttons[-1][1].font.configure(size=11)
        self.bag_body=tk.Frame(parent,bg=BG);self.delivery_body=tk.Frame(parent,bg=BG)
        bar=tk.Frame(self.bag_body,bg=BG);bar.pack(fill='x');self.query=tk.StringVar();self.search=tk.Entry(bar,textvariable=self.query,bg=CARD,fg=TEXT,insertbackground=TEXT,relief='flat',font=('Helvetica',12));self.search.pack(side='left',fill='x',expand=True,ipady=8)
        self.pocket=tk.StringVar(value='Все карманы');self.pocket_select=Select(bar,self.pocket,values=['Все карманы']+[p[1] for p in POCKETS if p[0]!='pc'],command=lambda _:self.fill(),width=155);self.pocket_select.pack(side='right',padx=(8,0))
        label(self.bag_body,'Название предмета · поиск на русском и английском',10,MUTED,pady=6)
        style=ttk.Style(parent);style.configure('Inventory.Treeview',background=CARD,fieldbackground=CARD,foreground=TEXT,rowheight=56,borderwidth=0,font=('Helvetica',11));style.map('Inventory.Treeview',background=[('selected','#294238')]);style.configure('Inventory.Treeview.Heading',background=BG,foreground=MUTED,relief='flat',padding=(4,8))
        table_frame=tk.Frame(self.bag_body,bg=BG);table_frame.pack(fill='both',expand=True,pady=(6,0));self.table=Table(table_frame,columns=('name','count','pocket'),show='tree headings',style='Inventory.Treeview',selectmode='browse',height=5)
        self.table.column('#0',width=58,minwidth=58,stretch=False);self.table.heading('#0',text='')
        for key,title,width in [('name','Предмет',230),('count','Кол-во',65),('pocket','Карман',110)]:self.table.heading(key,text=title,command=lambda k=key:self.sort(k));self.table.column(key,width=width,minwidth=50,anchor='e' if key=='count' else 'w',stretch=key=='name')
        scroll=Scrollbar(table_frame,command=self.table.yview);scroll.pack(side='right',fill='y');self.table.pack(side='left',fill='both',expand=True);self.table.configure(yscrollcommand=scroll.set)
        self.description=label(self.bag_body,'',10,MUTED,wraplength=475,pady=10);self.table.bind('<<TreeviewSelect>>',self.describe);self.table.bind('<Configure>',self.fit_columns)
        self.table.bind('<Double-1>',lambda _:self.open_details());self.table.bind('<Return>',lambda _:self.open_details())
        actions=tk.Frame(self.bag_body,bg=BG);actions.pack(fill='x');self.details_button=Button(actions,'Подробнее',self.open_details);self.details_button.pack(side='left');self.collect_button=Button(actions,'Автосбор',self.collect,variant='primary');self.collect_button.pack(side='right');self.collect_hint=label(self.bag_body,'Выберите предмет',10,MUTED,wraplength=475,pady=6)
        self.queue_link=Button(self.bag_body,'Очередь автосбора',self.open_queue,variant='ghost');self.queue_link.pack(fill='x',pady=(4,0))
        self.query.trace_add('write',lambda *_:self.fill());self.build_delivery();self.select();subscribe(self)
        self.parent.bind('<Destroy>',lambda e:unsubscribe(self) if e.widget is self.parent else None,add='+')
    def locale_changed(self):
        if self.parent.winfo_exists():self.fill()
    def select(self):
        self.source_queries[self.current_source]=self.query.get()
        self.source_positions[self.current_source]=self.table.yview()[0]
        changed=self.current_source!=self.source.get();self.current_source=self.source.get()
        if changed:
            self.changing_source=True;self.query.set(self.source_queries.get(self.current_source,''));self.changing_source=False
        if self.source.get()=='delivery':
            for i,info in self.data.items():
                if availability(self.project,i,dict(ready=True,items=self.rows))[0]:self.delivery_choices[info['title']]=i
            self.item_picker.configure(values=list(self.delivery_choices))
        self.bag_body.pack_forget();self.delivery_body.pack_forget();(self.delivery_body if self.source.get()=='delivery' else self.bag_body).pack(fill='both',expand=True)
        self.pocket_select.configure(state='disabled' if self.source.get()=='pc' else 'normal');self.fill();self.refresh(force=True)
        if changed:self.table.yview_moveto(self.source_positions.get(self.current_source,0))
    def fit_columns(self,event):
        columns=('name','count','pocket') if event.width>=550 else ('name','count')
        if tuple(self.table['displaycolumns'])!=columns:self.table.configure(displaycolumns=columns)
    def sort(self,key):
        if key not in ('name','count'):return
        self.sort_reverse=not self.sort_reverse if self.sort_field==key else key=='count';self.sort_field=key;self.fill()
    def fill(self):
        if self.changing_source:return
        if self.source.get()=='delivery':self.count.configure(text='Автосбор в сумку');return
        pc=self.source.get()=='pc';library=self.source.get()=='library';q=self.query.get().strip().casefold();pocket=self.pocket.get()
        source=library_rows(self.data,self.counts) if library else self.rows
        rows=[r for r in source if r['id'] in self.data and (library or (r['pocket']=='pc')==pc) and (pc or pocket=='Все карманы' or (r.get('pocket_name')==pocket if not library else next((title for key,title,*_ in POCKETS if key=={1:'items',2:'key',3:'balls',4:'tmhm',5:'berries'}.get(self.data[r['id']]['pocket_id'])),None)==pocket)) and search_matches(q,entity_aliases('items',r['id'],r.get('name','')),self.data[r['id']]['title'])]
        rows=sort_rows(rows,self.data,self.sort_field,self.sort_reverse)
        selected=self.table.selection();previous=self.mapping.get(selected[0],{}).get('id') if selected and hasattr(self,'mapping') else self.selected_id
        self.table.delete(*self.table.get_children());self.mapping={};target=None
        for r in rows:
            info=self.data[r['id']];key=f"{r['pocket']}:{r['slot']}";photo=item_icon(self.table,self.project,r['id']);self.photos[r['id']]=photo
            title=item_name(r['id'],info['title']);english=info['name'].title();location=info['usage'] if library else r.get('pocket_name','')
            self.table.insert('','end',iid=key,image=photo,values=(title,'×'+str(r['quantity']),location));self.mapping[key]=r
            if r['id']==previous:target=key
        if target:self.table.selection_set(target)
        self.describe()
        self.count.configure(text=f"Позиций: {len(rows)} · всего ×{sum(r['quantity'] for r in rows)}")
    def describe(self,_=None):
        selection=self.table.selection();r=self.mapping.get(selection[0]) if selection else None
        self.selected_id=r['id'] if r else None
        self.details_button.configure(state='normal' if r else 'disabled')
        if not r:
            self.description.configure(text='Библиотека показывает и отсутствующие предметы. Количество включает сумку, PC и предметы у Pokémon.' if self.source.get()=='library' else 'Выберите предмет, чтобы узнать его действие.');self.collect_button.configure(state='disabled');self.collect_hint.configure(text='');return
        info=self.data[r['id']];counts=self.counts.get(r['id'],{});where=f"Сумка ×{counts.get('bag',0)} · PC ×{counts.get('pc',0)} · у Pokémon ×{sum(counts.get(k,0) for k in ('party','boxes','daycare'))}"
        text=render(info['description']).replace('\n',' ');preview=text if len(text)<=220 else text[:217].rsplit(' ',1)[0]+'…'
        self.description.configure(text=preview+'\n'+where)
        okay,reason=availability(self.project,r['id'],dict(ready=True,items=self.rows));self.collect_button.configure(state='normal' if okay else 'disabled');self.collect_hint.configure(text=reason)
    def open_details(self):
        item=self.selected_id
        if item not in self.data:return
        if getattr(self.panel,'workspace',False):return self.panel.details.open_item(item)
        if self.detail_window and self.detail_window.winfo_exists():self.detail_window.destroy()
        info=self.data[item];window=self.detail_window=tk.Toplevel(self.parent);window.title(item_name(item,info['title']));window.configure(bg=BG);window.geometry('520x590');window.minsize(400,420)
        head=tk.Frame(window,bg=BG,padx=18,pady=18);head.pack(fill='x');photo=item_icon(window,self.project,item);tk.Label(head,image=photo,bg=BG).pack(side='left',padx=(0,14));label(head,item_name(item,info['title']),16,bold=True);label(head,t('inventory.english_name',name=literal(info['name'].title())),11,MUTED)
        body=tk.Frame(window,bg=BG,padx=18);body.pack(fill='both',expand=True);text=tk.Text(body,bg=CARD,fg=TEXT,relief='flat',wrap='word',font=('Helvetica',12),padx=14,pady=14,highlightthickness=0);scroll=Scrollbar(body,command=text.yview);scroll.pack(side='right',fill='y');text.pack(fill='both',expand=True);text.configure(yscrollcommand=scroll.set)
        c=self.counts.get(item,{});ownership=f"Всего ×{c.get('total',0)}\nСумка ×{c.get('bag',0)} · хранилище PC ×{c.get('pc',0)}\nУ отряда ×{c.get('party',0)} · в коробках ×{c.get('boxes',0)} · в пансионе ×{c.get('daycare',0)}"
        price=f"Цена в данных игры: ₽{info['price']} · продажа: ₽{info['price']//2}. Наличие в магазинах зависит от места и сюжета." if info['price'] else 'Магазинная цена не установлена.'
        text.insert('1.0',info['description']+'\n\n'+ownership+'\n\n'+info['availability_note']+'\n'+('Можно передавать с Pokémon.' if info['holdable'] else 'Нельзя передавать с Pokémon.')+'\n'+price);text.configure(state='disabled')
        actions=tk.Frame(window,bg=BG,padx=18,pady=14);actions.pack(side='bottom',fill='x',before=body);okay,reason=availability(self.project,item,dict(ready=True,items=self.rows));label(actions,reason,10,MUTED,wraplength=470);button=Button(actions,'Автосбор',lambda:(window.destroy(),self.collect(item)),variant='primary');button.pack(fill='x',pady=(8,0));button.configure(state='normal' if okay else 'disabled');window.bind('<Escape>',lambda _:window.destroy())
    def build_article(self,parent,item):
        info=self.data[item];photo=item_icon(parent,self.project,item)
        head=tk.Frame(parent,bg=BG);head.pack(fill='x',pady=(0,10))
        icon=tk.Label(head,image=photo,bg=BG);icon.image=photo;icon.pack(side='left',padx=(0,12))
        label(head,item_name(item,info['title']),18,bold=True)
        label(head,t('inventory.english_name',name=literal(info['name'].title())),11,MUTED)
        c=self.counts.get(item,{})
        label(parent,t('workspace.item_stock',total=c.get('total',0),bag=c.get('bag',0),pc=c.get('pc',0),held=sum(c.get(k,0) for k in ('party','boxes','daycare'))),12,GREEN,wraplength=430).pack_configure(pady=(0,12))
        for text in (info['description'],info['availability_note'],t('workspace.item_trade_yes') if info['holdable'] else t('workspace.item_trade_no')):
            label(parent,text,12,TEXT,wraplength=430).pack_configure(pady=(0,10))
        okay,reason=availability(self.project,item,dict(ready=True,items=self.rows))
        label(parent,reason,11,MUTED,wraplength=430)
        def collect():
            self.panel.details.back();self.panel.show('inventory');self.collect(item)
        button=Button(parent,t('workspace.collect'),collect,variant='primary');button.pack(fill='x',pady=(10,0));button.configure(state='normal' if okay else 'disabled')
        parent.bind('<Configure>',lambda e:[child.configure(wraplength=max(230,e.width-12)) for child in parent.winfo_children() if isinstance(child,tk.Label)],add='+')
    def collect(self,item=None):
        item=self.selected_id if item is None else item
        if item not in self.data:return
        okay,_=availability(self.project,item,dict(ready=True,items=self.rows))
        if not okay:return
        self.return_source=self.source.get() if self.source.get()!='delivery' else self.return_source
        self.delivery_choices[self.data[item]['title']]=item;self.item_picker.configure(values=list(self.delivery_choices));self.delivery_item.set(self.data[item]['title']);self.source.set('delivery');self.select()
    def open_queue(self):
        self.return_source=self.source.get();self.source.set('delivery');self.select()
    def close_collection(self):
        self.source.set(self.return_source);self.select()
    def build_delivery(self):
        parent=self.delivery_body
        Button(parent,'← К предметам',self.close_collection,variant='ghost').pack(anchor='w',pady=(0,8))
        label(parent,'Предмет для доставки',11,MUTED).pack_configure(pady=(0,4))
        self.delivery_choices={v['title']:k for k,v in PRODUCTS.items()}
        for i,info in self.data.items():
            if availability(self.project,i,dict(ready=True,items=self.rows))[0]:self.delivery_choices[info['title']]=i
        self.delivery_item=tk.StringVar(value=PRODUCTS[14]['title']);self.item_picker=Select(parent,self.delivery_item,values=list(self.delivery_choices),command=lambda _:self.refresh(force=True));self.item_picker.pack(fill='x',pady=(0,10))
        box=card(parent);box.pack(fill='x');row=tk.Frame(box,bg=CARD);row.pack(fill='x');self.item_photo=item_icon(row,self.project,14);self.item_image=tk.Label(row,image=self.item_photo,bg=CARD);self.item_image.pack(side='left',padx=(0,12))
        titles=tk.Frame(row,bg=CARD);titles.pack(side='left',fill='x',expand=True);self.item_title=label(titles,PRODUCTS[14]['title'],14,bold=True);self.stock=label(titles,'',10,MUTED,wraplength=410);self.template_status=label(box,'',10,GREEN,wraplength=470);self.template_status.pack_configure(pady=(8,0))
        self.mode=tk.StringVar(value='add');Segments(parent,[('add','Добавить'),('target','Довести до')],self.mode,lambda _:self.calculate()).pack(fill='x',pady=(14,8))
        row=tk.Frame(parent,bg=BG);row.pack(fill='x');label(row,'Количество',11,MUTED,pack=False).pack(side='left');self.amount=tk.StringVar(value='1');self.quantity_entry=tk.Entry(row,textvariable=self.amount,width=7,bg=CARD,fg=TEXT,insertbackground=TEXT,relief='flat',font=('Helvetica',13));self.quantity_entry.pack(side='left',padx=12,ipady=6);self.total=label(row,'',10,MUTED,pack=False,wraplength=275);self.total.pack(side='left',fill='x',expand=True)
        label(parent,'Курьер из отряда',11,MUTED).pack_configure(pady=(12,4));self.courier=tk.StringVar();self.courier_picker=Select(parent,self.courier,values=[]);self.courier_picker.pack(fill='x');self.courier_choices={}
        label(parent,'В списке только курьеры, которых нет в копии донора. После каждого предмета оба возвращаются. Дружба курьера может снизиться.',10,MUTED,wraplength=470).pack_configure(pady=8)
        label(parent,'Доставка занимает основную игру и заканчивается в Pokémon Center. Перед запуском заверши бой или диалог.',10,MUTED,wraplength=470).pack_configure(pady=(0,8))
        self.error=label(parent,'',10,RED,wraplength=470);self.enqueue_button=Button(parent,'Добавить автосбор',self.enqueue,variant='primary');self.enqueue_button.pack(fill='x',pady=(4,14))
        label(parent,'Очередь автосбора',14,bold=True);self.queue_body=tk.Frame(parent,bg=BG);self.queue_body.pack(fill='x',pady=(8,0));self.amount.trace_add('write',lambda *_:self.calculate())
    def selected_item(self):
        return self.delivery_choices[self.delivery_item.get()]
    def calculate(self):
        item=self.selected_item();info=product(item,self.project);inv=dict(ready=True,items=self.rows);current=quantity(inv,item)
        self.item_title.configure(text=info['title']);self.item_photo=item_icon(self.item_image,self.project,item);self.item_image.configure(image=self.item_photo)
        self.stock.configure(text=f"В сумке: {current} · {info['hint']}")
        try:
            requested=int(self.amount.get())
            if not 1<=requested<=999:raise ValueError()
            count=requested if self.mode.get()=='add' else max(0,requested-current);after=current+count;self.total.configure(text=f'{current} → {after} · обменов: {count*2}'+(f' · ≈{max(1,round(count/2))} мин' if count>1 else ' · ≈30 с' if count else ''));valid=bool(count and after<=999)
        except ValueError:self.total.configure(text='Введи число от 1 до 999');valid=False
        template_ok,reason=availability(self.project,item,inv);self.template_status.configure(text=reason,fg=GREEN if template_ok else RED)
        self.enqueue_button.configure(state='normal' if valid and self.courier_choices and template_ok and not capacity_error(inv,item) else 'disabled')
    def enqueue(self):
        try:
            self.panel.monitor.delivery.enqueue(int(self.amount.get()),self.mode.get(),self.courier_choices[self.courier.get()],self.selected_item());self.error.configure(text='');self.queue_signature=None;self.refresh(force=True)
        except Exception as error:self.error.configure(text=str(error))
    def action(self,job_id,action):
        try:
            manager=self.panel.monitor.delivery
            if action=='start':manager.start(job_id)
            else:manager.pause(job_id,cancel=action=='cancel')
            self.error.configure(text='');self.queue_signature=None;self.refresh(force=True)
        except Exception as error:self.error.configure(text=str(error))
    def refresh_queue(self):
        manager=self.panel.monitor.delivery;rows=manager.jobs();signature=tuple((r['id'],r.get('item_id',14),r['status'],r['delivered'],r.get('stage'),r.get('last_cycle_seconds')) for r in rows);op=self.panel.monitor.operation
        if manager.current and op.active:
            from .acquisition import read_json
            live=read_json(op.job/'status.json',{});signature+=(live.get('stage'),)
        else:live={}
        if signature==self.queue_signature:return
        self.queue_signature=signature
        for child in self.queue_body.winfo_children():child.destroy()
        if not rows:label(self.queue_body,'Заданий пока нет. Добавь нужное количество в очередь.',10,MUTED,wraplength=470);return
        for r in [r for r in rows if r['status'] not in FINISHED]+[r for r in rows if r['status'] in FINISHED][-5:]:
            box=card(self.queue_body);box.pack(fill='x',pady=(0,8));title=tk.Frame(box,bg=CARD);title.pack(fill='x')
            item=r.get('item_id',14);photo=item_icon(title,self.project,item,scale=1);tk.Label(title,image=photo,bg=CARD).pack(side='left',padx=(0,8));label(title,f"{product(item,self.project)['name']} · {r['delivered']} / {r['amount']}",12,bold=True)
            stage=live.get('stage') if manager.current and manager.current['job_id']==r['id'] and live else r['stage'];label(box,stage,10,GREEN if r['status']=='done' else AMBER if r['status']=='attention' else MUTED,wraplength=440)
            if r.get('last_cycle_seconds') and r['status'] not in FINISHED:label(box,f"Осталось примерно {max(1,round(max(0,r['amount']-r['delivered'])*r['last_cycle_seconds']/60))} мин · основная игра занята обменами",10,MUTED,wraplength=440)
            if r['status'] not in FINISHED:
                actions=tk.Frame(box,bg=CARD);actions.pack(fill='x',pady=(8,0));running=r['status'] in ('running','pausing')
                Button(actions,'Приостановить' if running else 'Начать' if r['status']=='queued' else 'Продолжить',lambda i=r['id'],a='pause' if running else 'start':self.action(i,a),height=30).pack(side='left');Button(actions,'Отменить',lambda i=r['id']:self.action(i,'cancel'),height=30,variant='ghost').pack(side='right')
    def refresh(self,force=False):
        if not force and time.monotonic()-self.last_poll<.7:return
        self.last_poll=time.monotonic();m=self.panel.monitor;inv=m.bag_snapshot()
        if inv['ready']:
            inventory=m.inventory_snapshot() if hasattr(m,'inventory_snapshot') else getattr(m,'last_inventory',{})
            counts=holdings(inv['items'],inventory,m.last_state);signature=(tuple((r['pocket'],r['slot'],r['id'],r['quantity']) for r in inv['items']),repr(counts))
            if force or signature!=self.signature:self.signature=signature;self.rows=inv['items'];self.counts=counts;self.fill()
        else:self.count.configure(text='Загрузи сохранение')
        couriers=eligible_couriers((m.last_state or {}).get('party',[]),self.project,self.selected_item());signature=tuple((r['uid'],r.get('level')) for r in couriers)
        if force or signature!=self.courier_signature:
            selected=self.courier_choices.get(self.courier.get());self.courier_choices={f"{r['nickname']} · Lv {r['level']} · место {r['slot']}":r['uid'] for r in couriers};self.courier_picker.configure(values=list(self.courier_choices) or ['Нет подходящего курьера в отряде']);self.courier.set(next((k for k,v in self.courier_choices.items() if v==selected),next(iter(self.courier_choices),'Нет подходящего курьера в отряде')));self.courier_signature=signature
        self.calculate()
        if self.source.get()=='delivery':self.refresh_queue()
        active=sum(r['status'] not in FINISHED for r in m.delivery.jobs());self.queue_link.configure(text='Очередь автосбора'+(f' · {active}' if active else ''))

def show_inventory(panel):panel.show('inventory')
