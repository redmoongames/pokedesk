from .entity_names import display_entity_names as _entity_label
from .i18n import search_matches
from .entity_names import entity_aliases
from .table import Table
"""Offline Pokédex, exact XP calculator and measured route analytics."""
import json
from . import localized_tk as tk
from .scrolling import Scrollbar
from tkinter import ttk
from .localized_tk import filedialog
from datetime import datetime
from .catalog import catalog,species,experience_reward
from .ui import BG,CARD,TEXT,MUTED,GREEN,BLUE,Button,Tabs,Toggle,Stepper,label,theme
from .sprites import sprite
from .history import FPS

def window(parent,title,width=720,height=680):
    w=tk.Toplevel(parent);w.title(title);w.configure(bg=BG);w.geometry(f'{width}x{height}');theme(w);return w

def show_move(panel,number):
    from .pokemon_ui import show_move as open_move
    open_move(panel,number)
def show_species(panel,number,mon=None):
    from .pokemon_ui import show_species as open_species
    open_species(panel,number,mon)

def show_xp_calculator(panel,number,level=3):
    sp=species(number,panel.monitor.folder);w=window(panel.window,'Опыт · '+_entity_label(sp['name']),570,660);form=tk.Frame(w,bg=BG,padx=18,pady=16);form.pack(fill='both',expand=True);form.columnconfigure(1,weight=1);label(form,_entity_label(sp['name']),21,GREEN,bold=True,pack=False).grid(row=0,column=0,columnspan=2,sticky='w',pady=(0,14));values={}
    for row,(key,title,default,low,high) in enumerate([('level','Уровень побеждённого',level,1,100),('participants','Живых участников',2,1,6),('share_holders','Владельцев Exp. Share',0,0,6),('recipient_level','Уровень получателя',1,1,100)],start=1):
        label(form,title,12,pack=False).grid(row=row,column=0,sticky='w',padx=(0,20),pady=6);v=tk.IntVar(value=default);values[key]=v;Stepper(form,v,low,high).grid(row=row,column=1,sticky='ew')
    flags={}
    for row,(key,title,default) in enumerate([('participated','Получатель участвовал в бою',True),('exp_share','Держит Exp. Share',False),('lucky_egg','Держит Lucky Egg',False),('traded','Получен в обмене',False),('trainer','Бой с тренером',False),('alive','Получатель жив',True)],start=5):
        v=tk.BooleanVar(value=default);flags[key]=v;Toggle(form,title,v).grid(row=row,column=0,columnspan=2,sticky='ew',pady=2)
    result=label(form,'',17,GREEN,pack=False,wraplength=520);result.grid(row=11,column=0,columnspan=2,sticky='w',pady=14)
    def calculate(*_):
        try:
            args={k:int(v.get()) for k,v in values.items()};args.update({k:bool(v.get()) for k,v in flags.items()})
            if not 1<=args['participants']<=6 or not 0<=args['share_holders']<=6 or not 1<=args['recipient_level']<=100:raise ValueError('Проверь числовые значения')
            if args['exp_share'] and args['lucky_egg']:raise ValueError('Можно держать один предмет')
            if args['exp_share'] and not args['share_holders']:raise ValueError('Укажи владельцев Exp. Share')
            result.configure(text=f"Получатель: {experience_reward(sp['base_xp'],**args)} XP")
        except (ValueError,tk.TclError) as error:result.configure(text=str(error))
    for v in [*values.values(),*flags.values()]:v.trace_add('write',calculate)
    calculate()

def show_pokedex(panel):
    w=window(panel.window,'FireRed · Pokédex',620,720);label(w,'Pokédex',22,bold=True).pack_configure(padx=16,pady=14);search=tk.StringVar();entry=tk.Entry(w,textvariable=search,bg=CARD,fg=TEXT,insertbackground=TEXT,bd=0,font=('Helvetica',13));entry.pack(fill='x',padx=16,ipady=9)
    frame=tk.Frame(w,bg=BG);frame.pack(fill='both',expand=True,padx=16,pady=12);tree=Table(frame,columns=('type',),show='tree headings',style='Sprite.Treeview');tree.heading('#0',text='Pokémon');tree.heading('type',text='Тип');tree.column('#0',width=350);tree.column('type',width=200);scroll=Scrollbar(frame,command=tree.yview);scroll.pack(side='right',fill='y');tree.configure(yscrollcommand=scroll.set);tree.pack(fill='both',expand=True);images=[]
    def fill(*_):
        tree.delete(*tree.get_children());images.clear();q=search.get().lower()
        for s in sorted(catalog(panel.monitor.folder)['species'].values(),key=lambda s:s['national_id']):
            if search_matches(q,entity_aliases('species',s['id']),s['national_id']):
                image=sprite(tree,panel.monitor.folder,s['id']);images.append(image);tree.insert('','end',iid=str(s['id']),text=f"#{s['national_id']:03} {_entity_label(s['name'])}",image=image,values=(' / '.join(s['types']),))
    def open_selected(_=None):
        if tree.selection():
            show_species(panel,int(tree.selection()[0]))
            if hasattr(panel,'open_pokemon'):w.withdraw()
    search.trace_add('write',fill);tree.bind('<Double-1>',open_selected);Button(w,'Открыть Pokémon ↗',open_selected,variant='primary').pack(fill='x',padx=16,pady=(0,14));fill();entry.focus_set()

def show_history(panel):
    existing=getattr(panel,'history_window',None)
    if existing and existing.winfo_exists():existing.deiconify();existing.lift();return
    w=panel.history_window=window(panel.window,'FireRed · История и аналитика',960,740);w.minsize(760,580)
    head=tk.Frame(w,bg=BG);head.pack(fill='x',padx=18,pady=14);label(head,'История и аналитика',22,bold=True,pack=False).pack(side='left');Button(head,'Экспорт JSON',lambda:export(),variant='ghost').pack(side='right');tabs=Tabs(w);tabs.pack(fill='both',expand=True,padx=14,pady=(0,12));pages={}
    for key,title in [('routes','Эффективность'),('cycles','Циклы'),('battles','Бои'),('events','События')]:
        page=tk.Frame(tabs,bg=BG,padx=4,pady=8);tabs.add(page,text=title);pages[key]=page
    width_path=panel.monitor.folder/'Data/analytics-columns.json'
    try:width_state=json.loads(width_path.read_text())
    except (OSError,ValueError):width_state={}
    def table(parent,columns):
        frame=tk.Frame(parent,bg=BG);frame.pack(fill='both',expand=True,pady=8);view=Table(frame,columns=[x[0] for x in columns],show='headings',height=5,style='Trainer.Treeview',selectmode='browse')
        table_key=','.join(c[0] for c in columns);weights=width_state.get(table_key,{k:width for k,_,width in columns})
        for key,title,width in columns:view.heading(key,text=title);view.column(key,width=width,minwidth=40)
        def fit(event):
            available=max(1,event.width-4);total=sum(max(1,weights.get(k,40)) for k,_,_ in columns);used=0
            for i,(key,_,_) in enumerate(columns):
                width=max(40,int(available*max(1,weights.get(key,40))/total)) if i<len(columns)-1 else max(40,available-used)
                view.column(key,width=width);used+=width
        view.bind('<Configure>',fit)
        def save_widths(event):
            if not getattr(view,'_drag_columns',False):return
            view._drag_columns=False;weights.update({k:view.column(k,'width') for k,_,_ in columns});width_state[table_key]=dict(weights)
            from .engine import atomic_bytes
            atomic_bytes(width_path,json.dumps(width_state).encode(),durable=True)
        view.bind('<ButtonPress-1>',lambda e:setattr(view,'_drag_columns',view.identify_region(e.x,e.y)=='separator'),add='+');view.bind('<ButtonRelease-1>',save_widths,add='+')
        scroll=Scrollbar(frame,command=view.yview);scroll.pack(side='right',fill='y');view.configure(yscrollcommand=scroll.set);view.pack(fill='both',expand=True);
        def sort_column(key):
            reverse=getattr(view,'_sort_column',None)==(key,False);view._sort_column=(key,reverse)
            def value(item):
                text=getattr(view,'sort_values',{}).get(item,{}).get(key,view.set(item,key))
                try:return (0,float(text.replace(' ','')))
                except ValueError:return (1,text)
            for index,item in enumerate(sorted(view.get_children(),key=value,reverse=reverse)):view.move(item,'',index)
        view._apply_sort=lambda:sort_column(view._sort_column[0]) if hasattr(view,'_sort_column') else None
        for key,_,_ in columns:view.heading(key,command=lambda k=key:sort_column(k))
        return view
    def text(parent,height=7):
        widget=tk.Text(parent,height=height,bg=CARD,fg=TEXT,wrap='word',padx=12,pady=10,relief='flat',font=('Helvetica',11),state='disabled');widget.pack(fill='x',pady=8);return widget
    def set_text(widget,value):widget.configure(state='normal');widget.delete('1.0','end');widget.insert('end',value);widget.configure(state='disabled')
    def date(value):return datetime.fromisoformat(value).astimezone().strftime('%d.%m %H:%M:%S') if value else '—'
    summary=label(pages['routes'],'Только полные циклы · подготовка команды исключена',12,GREEN)
    from .zones import zone_spec
    zones=zone_spec(panel.monitor.folder)
    def route_label(key):return zones['zones'].get(key,{}).get('label',key)
    def clinic_label(key):return zones['hubs'].get(key,{}).get('label',key or '—')
    rates=table(pages['routes'],[('route','Зона',130),('game','XP/мин игры',110),('active','XP/мин (реал.)',125),('cycles','Циклов',65),('last','Последний замер',130),('quality','Контекст',135)])
    label(pages['routes'],'Состав, предметы, Center и условия — в деталях строки. Подготовка и неполные циклы исключены.',10,MUTED,wraplength=880)
    rates_detail=text(pages['routes'],6)
    cycles=table(pages['cycles'],[('time','Начало',135),('route','Зона',105),('number','Цикл',45),('status','Статус',110),('xp','XP цель / все',100),('timegame','Игр. мин',75),('wall','Реал. мин',85),('battles','Бои',45)]);cycle_detail=text(pages['cycles'],8)
    battles=table(pages['battles'],[('time','Время',135),('enemy','Противник',275),('outcome','Итог',150),('xp','XP команды',100)]);battle_detail=text(pages['battles'],7)
    raw=tk.BooleanVar(value=False);Toggle(pages['events'],'Включая нажатия и перемещения',raw).pack(fill='x');events=table(pages['events'],[('time','Время',140),('message','Событие',600)]);event_detail=text(pages['events'],9)
    records={};revision=-1
    w.analytics_tables=dict(rates=rates,cycles=cycles,battles=battles,events=events)
    def selected(kind,view,widget):
        if not view.selection():return
        row=records.get(kind,{}).get(view.selection()[0])
        if row is None:return
        if kind=='rates':
            lines=[f"{row['route']} · {row['cycles']} полных циклов · +{row['target_xp']} XP цели",f"{row['xp_game_minute']:.1f} XP / игровая минута · {row['xp_active_minute']:.1f} XP / минута без пауз"]
            lines.insert(1,clinic_label(row.get('clinic'))+' · участок '+str(row.get('area') or '—'))
            lines.insert(2,('Полный контекст' if row['context_complete'] else 'Старые данные: контекст неполон')+' · последний замер '+date(row['last_sample_at'])+' · '+row['speed_note'])
            context=row.get('context') or {};cfg=context.get('config',{});versions=context.get('versions',{})
            if cfg:lines.append(f"Лечение: HP < {cfg['heal_percent']}% · порог KO {cfg['target_ohko_threshold']:.0%} · политика {versions.get('policy_name','—')}")
            if versions:lines.append('Версия расчётов: '+versions.get('policy','')[:12]+' · навигация '+versions.get('navigation','')[:12])
            lines += [f"{m['nickname']} Lv {m['level']} · "+' / '.join(a.get('name',str(a['id'])) for a in m['moves'])+(' · предмет: '+catalog(panel.monitor.folder)['items'].get(str(m.get('held_item',0)),'Нет')) for m in row['team']]
        elif kind=='cycles':
            body=json.loads(row['body']);lines=[f"{row['route']} · {row['strategy']} · {row['status']}",f"Цель +{row['target_xp'] or 0} XP · команда +{row['team_xp'] or 0} XP · боёв {row['battles'] or 0}",f"Время: {(row['game_seconds'] or 0):.1f} игровых сек · {(row['wall_seconds'] or 0):.1f} сек с паузами · {(row['active_seconds'] or 0):.1f} сек без пауз"]
            lines.insert(1,clinic_label(body.get('clinic'))+' · участок '+str(body.get('area') or '—'))
            forecast=body.get('forecast');evaluation=body.get('evaluation')
            if forecast:
                lines.insert(2,f"Прогноз до выхода: {forecast['target_xp']:.0f} XP / {forecast['game_seconds']:.0f} сек · {forecast['xp_game_minute']:.1f} XP/мин · модель {forecast['version']}")
                if evaluation and evaluation['kind']=='complete':lines.insert(3,f"Ошибка прогноза времени {evaluation['time_error_percent']:+.0f}% · XP {evaluation['xp_error']:+.0f} · факт {evaluation['actual_xp_game_minute']:.1f} XP/мин")
                elif evaluation:lines.insert(3,'Неполный цикл: сравнение с прогнозом полного захода не выполняется')
            lines += [f"{m['nickname']} Lv {m['level']} · +{body.get('gains',{}).get(m['uid'],0)} XP" for m in body.get('team',[])]
        elif kind=='battles':
            d=row['detail'];lines=[f"{row['outcome']} · {row['map']} · {row['frames']/FPS:.1f} игровых сек · {d['controller']}"]+[f"{g['name']}: +{g['xp']} XP · Lv {g['from_level']} → {g['level']}" for g in d.get('gains',[])]
        else:lines=[row['message'],row['code'],json.dumps(row['details'],ensure_ascii=False,indent=2)]
        set_text(widget,'\n'.join(lines))
    for kind,view,widget in [('rates',rates,rates_detail),('cycles',cycles,cycle_detail),('battles',battles,battle_detail),('events',events,event_detail)]:view.bind('<<TreeviewSelect>>',lambda _,k=kind,v=view,d=widget:selected(k,v,d))
    def replace(view,kind,rows,formatter):
        selection=view.selection();scroll=view.yview();view.delete(*view.get_children());records[kind]={}
        import hashlib
        view.sort_values={}
        for r in rows:
            identity=r.get('id') if kind!='rates' else (r['route'],r['target_uid'],r['team_fingerprint'],r.get('legacy_run_id') or '')
            key=hashlib.sha256(str(identity).encode()).hexdigest()[:24];records[kind][key]=r;view.insert('','end',iid=key,values=formatter(r));view.sort_values[key]=dict(last=r.get('last_sample_at',''),time=r.get('time',r.get('started_at','')))
        if hasattr(view,'_sort_column'):
            key,reverse=view._sort_column;view._sort_column=(key,not reverse);view._apply_sort()
        if selection and selection[0] in records[kind]:view.selection_set(selection[0])
        if scroll:view.yview_moveto(scroll[0])
    def export():
        path=filedialog.asksaveasfilename(parent=w,title='Экспорт циклов',defaultextension='.json',initialfile='pokemon-training.json',filetypes=[('JSON','*.json')])
        if path:
            from pathlib import Path
            panel.monitor.history.export(Path(path))
    def refresh(force=False):
        nonlocal revision
        if not w.winfo_exists():return
        h=panel.monitor.history
        if force or revision!=h.revision:
            replace(rates,'rates',h.comparisons(),lambda r:(route_label(r['route']),f"{r['xp_game_minute']:.1f}",f"{r['xp_active_minute']:.1f}",r['cycles'],date(r['last_sample_at']),'Полный' if r['context_complete'] else 'Неполный'))
            replace(cycles,'cycles',h.cycles(),lambda r:(date(r['started_at']),r['route'],r['number'],'Завершён' if r['status']=='completed' else 'Выполняется' if r['status']=='running' else 'Незавершён',f"{r['target_xp'] or 0} / {r['team_xp'] or 0}",f"{(r['game_seconds'] or 0)/60:.1f}",f"{(r['active_seconds'] or 0)/60:.1f}",r['battles'] or 0))
            replace(battles,'battles',h.rows(),lambda r:(date(r['time']),', '.join(f"{m['species']} Lv {m['level']}" for m in r['detail']['enemies'].values()),r['outcome'],f"+{r['xp']}"))
            rows=h.events(1000 if raw.get() else 3000);rows=[r for r in rows if raw.get() or r['code'] not in ('movement','bot_input','player_input','pokemon_changed')][:300];replace(events,'events',rows,lambda r:(date(r['time']),r['message']));revision=h.revision
        w.after(1500,refresh)
    def filter_changed(*_):
        nonlocal revision
        revision=-1
    raw.trace_add('write',filter_changed);refresh()
