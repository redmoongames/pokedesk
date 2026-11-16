from .entity_names import display_entity_names as _entity_label
from .table import Table
"""Explicit review of final moves and every implied skip/replacement/evolution."""
from . import localized_tk as tk
from tkinter import ttk

from .catalog import move,species
from .move_plan import curriculum,default_moves,compile_plan,needs_approval,decision_order
from .ui import BG,CARD,TEXT,MUTED,BLUE,AMBER,GREEN,Button,label,card
from .types_ui import TYPE_INFO,draw_type
from .tooltips import Tooltip

def decision_text(step,root):
    if step['kind']=='evolve':
        return ('Отменить ' if step['action']=='cancel' else '')+_entity_label(species(step['species'],root)['name'])+' → '+_entity_label(species(step['target_species'],root)['name'])
    if step['action']=='replace':return _entity_label(move(step['forget'],root)['name'])+' → '+_entity_label(move(step['move'],root)['name'])
    if step['action']=='skip':return 'Пропустить '+_entity_label(move(step['move'],root)['name'])
    return 'Свободный слот: '+_entity_label(move(step['move'],root)['name'])

def review_lines(plan,root):
    entries=[*plan['decisions'],*[s for s in plan['steps'] if s['action']=='auto']]
    entries.sort(key=decision_order)
    return '\n'.join(f"Lv {s['level']} · {decision_text(s,root)}" for s in entries) or 'Текущий набор и вид сохраняются; запросов выбора до цели нет.'

class MoveSetup:
    def __init__(self,setup,parent):
        self.setup=setup;self.root=setup.monitor.folder;self.uid=None;self.selected=None;self.mode='natural';self.custom=False;self.target=None;self.window=None;self.signature=None;self.contract=None;self.approved=setup.config.get('approved_plan_id')
        self.frame=card(parent);self.frame.pack(fill='x',pady=(8,0));head=tk.Frame(self.frame,bg=CARD);head.pack(fill='x')
        label(head,'Приёмы и эволюции',12,bold=True,pack=False).pack(side='left');self.edit=Button(head,'Принять решения',self.open,variant='ghost');self.edit.pack(side='right')
        self.cells=tk.Frame(self.frame,bg=CARD);self.cells.pack(fill='x');self.hint=label(self.frame,'Выбери Pokémon',10,MUTED,wraplength=450)
        self.schedule=tk.Text(self.frame,height=2,wrap='word',bg=CARD,fg=MUTED,bd=0,font=('Helvetica',10),state='disabled');self.schedule.pack_forget()
    def adopt(self,cfg):
        self.uid=cfg['trainee'];self.selected=list(cfg['final_moves']) if cfg.get('final_moves') else None;self.mode=cfg.get('evolution_mode','natural');self.approved=cfg.get('approved_plan_id');self.custom=True;self.signature=None
    def review_reason(self,plan=None):
        contract=(plan or {}).get('move_plan') if plan is not None else self.contract
        if contract and needs_approval(contract) and contract['id']!=self.approved:return f"Прими решения по уровням · {len(contract['decisions'])}"
        return ''
    def update(self,mon,running=False):
        self.target=mon;self.edit.configure(state='disabled' if running or not mon else 'normal')
        if running and self.window and self.window.winfo_exists():self.window.destroy()
        if mon and not running:
            if mon['uid']!=self.uid:
                self.uid=mon['uid'];self.custom=self.setup.config.get('trainee')==self.uid and bool(self.setup.config.get('final_moves'))
                self.mode=self.setup.config.get('evolution_mode','natural') if self.custom else 'natural';self.selected=list(self.setup.config['final_moves']) if self.custom else None;self.approved=self.setup.config.get('approved_plan_id') if self.custom else None
            if not self.custom:
                try:self.selected=default_moves(mon,int(self.setup.target.get()),self.root,self.mode)
                except ValueError:self.selected=list(a['id'] for a in mon['moves'])
        goal=int(self.setup.target.get())
        key=(self.uid,tuple(self.selected or []),self.mode,running,self.approved,goal,mon['level'] if mon else None,mon['species_id'] if mon else None,tuple(a['id'] for a in mon['moves']) if mon else ())
        if key==self.signature:return
        self.signature=key
        if not running:
            try:self.set_contract(compile_plan(mon,goal,self.selected,self.root,self.mode) if mon and self.selected else None)
            except ValueError:self.set_contract(None)
        for child in self.cells.winfo_children():child.destroy()
        for i in range(4):
            n=(self.selected or [])[i] if i<len(self.selected or []) else None;cell=tk.Frame(self.cells,bg=CARD,pady=3);cell.grid(row=i//2,column=i%2,sticky='ew',padx=(0 if i%2==0 else 8,0));self.cells.columnconfigure(i%2,weight=1,uniform='moves')
            if n:
                data=move(n,self.root);icon=tk.Canvas(cell,width=22,height=22,bg=CARD,highlightthickness=0);icon.pack(side='left');draw_type(icon,11,11,data['type_id'],size=18)
                text=label(cell,_entity_label(data['name']),10,TEXT,pack=False);text.pack(side='left',fill='x',expand=True);Tooltip(text,data.get('description',''))
                for widget in (cell,icon,text):widget.bind('<Button-1>',lambda _:self.open())
            else:label(cell,'—',10,MUTED)
    def set_contract(self,contract):
        self.contract=contract;reason=self.review_reason()
        self.edit.configure(text='Принять решения' if reason else 'Изменить')
        self.hint.configure(text=('Черновик · '+reason) if reason else 'Решения подтверждены' if contract and contract['id']==self.approved else 'Решения не требуются' if contract else 'План проверяется перед запуском',fg=AMBER if reason else GREEN if contract and contract['id']==self.approved else MUTED)
        text=review_lines(contract,self.root) if contract else 'Ожидание плана'
        self.schedule.configure(height=min(10,max(1,len(text.splitlines()))))
        self.schedule.configure(state='normal');self.schedule.delete('1.0','end');self.schedule.insert('end',review_lines(contract,self.root) if contract else 'Ожидание плана');self.schedule.configure(state='disabled')
    def open(self):
        if not self.target or self.setup.monitor.automation.info()['running']:return
        if self.window and self.window.winfo_exists():self.window.lift();return
        mon=self.target;goal=int(self.setup.target.get())
        try:natural=curriculum(mon,goal,self.root,'natural')
        except ValueError as error:self.hint.configure(text=str(error),fg=AMBER);return
        w=self.window=tk.Toplevel(self.setup.panel.window);w.title('Решения по уровням');w.configure(bg=BG);w.geometry('730x790');w.minsize(600,620)
        draft=list(self.selected or []);mode=tk.StringVar(value=self.mode)
        label(w,f"{mon['nickname']} · Lv {mon['level']} → {goal}",18,bold=True).pack_configure(padx=16,pady=12)
        row=tk.Frame(w,bg=BG);row.pack(fill='x',padx=16);buttons=[]
        modes=[('natural','Эволюции по уровню'),('stay','Сохранить вид')]+[('stop_at:'+str(n),'До '+_entity_label(species(n,self.root)['name'])) for n in natural['forms'][1:-1]]
        for key,title in modes:
            b=Button(row,title,lambda value=key:mode.set(value));b.pack(side='left',fill='x',expand=True,padx=2);buttons.append((key,b))
        form_info=label(w,'',11,BLUE,wraplength=670);form_info.pack_configure(padx=16,pady=8)
        label(w,'Итоговый набор: отметь до четырёх приёмов.',11,MUTED).pack_configure(padx=16)
        tree=Table(w,columns=('level','type','power'),show='tree headings',style='Trainer.Treeview',selectmode='browse',height=7)
        tree.heading('#0',text='Приём');tree.heading('level',text='Когда');tree.heading('type',text='Тип');tree.heading('power',text='Сила');tree.column('#0',width=280,minwidth=180);tree.column('level',width=70,minwidth=55);tree.column('type',width=95,minwidth=70);tree.column('power',width=55,minwidth=45);tree.pack(fill='both',expand=True,padx=16,pady=8)
        detail=label(w,'',10,MUTED,wraplength=670);detail.pack_configure(padx=16,pady=4)
        label(w,'Все решения, которые выполнит бот',12,bold=True).pack_configure(padx=16,pady=(8,4))
        review=tk.Text(w,height=6,wrap='word',bg=CARD,fg=TEXT,bd=0,padx=10,pady=8,font=('Helvetica',11),state='disabled');review.pack(fill='x',padx=16)
        notice=label(w,'',10,AMBER,wraplength=670);notice.pack_configure(padx=16,pady=5);rows={};proposed=None
        def fill(*_):
            nonlocal draft,rows,proposed
            proposed=None
            try:
                data=curriculum(mon,goal,self.root,mode.get());rows={str(r['id']):r for r in data['available']};draft=[n for n in draft if str(n) in rows]
                for key,b in buttons:b.configure(variant='selected' if key==mode.get() else 'secondary')
                form_info.configure(text=' → '.join(_entity_label(species(n,self.root)['name']) for n in data['forms']));tree.delete(*tree.get_children())
                for r in rows.values():
                    m=move(r['id'],self.root);tree.insert('','end',iid=str(r['id']),text=('✓  ' if r['id'] in draft else '○  ')+_entity_label(m['name']),values=('Сейчас' if r['source']=='Сейчас' else 'Lv '+str(r['level']),TYPE_INFO[m['type_id']][1],m['power'] or '—'))
                proposed=compile_plan(mon,goal,draft,self.root,mode.get())
                text=review_lines(proposed,self.root);notice.configure(text='\n'.join(proposed['warnings']));apply.configure(state='normal')
            except ValueError as e:text=str(e);notice.configure(text='Измени итоговый набор или эволюцию');apply.configure(state='disabled')
            review.configure(state='normal');review.delete('1.0','end');review.insert('end',text);review.configure(state='disabled')
        def toggle(_=None):
            selected=tree.selection()
            if not selected:return
            n=int(selected[0])
            if n in draft:draft.remove(n)
            elif len(draft)<4:draft.append(n)
            else:notice.configure(text='Сначала убери один из четырёх выбранных приёмов');return
            fill();tree.selection_set(str(n))
        def inspect(_=None):
            if tree.selection():
                r=rows[tree.selection()[0]];m=move(r['id'],self.root);detail.configure(text=f"{_entity_label(m['name'])} · PP {m['pp']} · точность {m['accuracy'] or '—'}\n"+m.get('description',''))
        def click(event):
            item=tree.identify_row(event.y)
            if item:tree.selection_set(item);toggle();inspect()
        def save():
            if self.setup.monitor.automation.info()['running'] or not proposed:return
            if self.setup.trainee.get()!=mon['uid'] or int(self.setup.target.get())!=goal:notice.configure(text='Цель изменилась: открой решения заново');return
            fresh=self.setup.monitor.inventory_snapshot();current=next((m for m in fresh['party']+fresh['boxes'] if m['uid']==mon['uid']),None)
            try:
                checked=compile_plan(current,goal,draft,self.root,mode.get()) if current else None
                if not checked or checked['id']!=proposed['id']:raise ValueError('Pokémon изменился: открой решения заново')
            except ValueError as e:notice.configure(text=str(e));return
            self.selected=list(draft);self.mode=mode.get();self.approved=proposed['id'];self.custom=True;self.signature=None;w.destroy();self.setup.signature=None;self.setup.changed()
        footer=tk.Frame(w,bg=BG);footer.pack(fill='x',padx=16,pady=12);Button(footer,'Отмена',w.destroy,variant='ghost').pack(side='left');apply=Button(footer,'Подтверждаю перечисленные решения',save,variant='primary');apply.pack(side='right')
        tree.bind('<ButtonRelease-1>',click);tree.bind('<space>',toggle);tree.bind('<<TreeviewSelect>>',inspect);mode.trace_add('write',fill);fill()
