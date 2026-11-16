from .i18n import t
from .tooltips import Tooltip
from .i18n import format_datetime,format_number
"""Slot-local restore points. Filesystem scans run outside Tk's event loop."""
import time
from . import localized_tk as tk
from tkinter import ttk
from .localized_tk import simpledialog
from .table import Table
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from .ui import BG,CARD,TEXT,MUTED,GREEN,AMBER,Button,Toggle,label
from .scrolling import Scrollbar
from .save_timeline import SaveTimeline,LABELS
from .slots import Slots

def summary_text(summary):
    if not summary or not summary.get('ready'):return 'Новое прохождение · персонаж ещё не создан'
    from .locations import location_name
    dex=summary.get('pokedex') or {};place=location_name((summary.get('map') or {}).get('name',''))
    return f"{summary.get('player','—')} · {place}\n₽ {summary.get('money',0):,} · Покедекс {dex.get('caught',0)} / 386".replace(',',' ')

def date_text(row):
    try:return format_datetime(row['created_at'])
    except (KeyError,ValueError,TypeError):return '—'

def read_history(folder,legacy):
    timeline=SaveTimeline(folder/'Data');current=timeline.current();rows=[('current','Актуальное автосохранение',current)]
    if current is None and (timeline.data/'FireRed.state').is_file():
        stamp=(timeline.data/'FireRed.state').stat().st_mtime
        rows[0]=('current','Актуальное автосохранение',dict(directory=timeline.data,is_current=True,summary=None,captured_at=stamp,created_at=datetime.fromtimestamp(stamp).astimezone().isoformat()))
    rows.extend(('age-'+str(age),'До него · ≈ '+LABELS[age],record) for age,record in timeline.anchors())
    if legacy:
        slots=Slots(folder)
        for row in slots.list()+slots.backups():
            if current and row.get('sha256')==current.get('sha256'):continue
            if current and row.get('history_time') is not None and current.get('history_time',0)>=row['history_time']:
                row=dict(row,age_seconds=current['history_time']-row['history_time'])
            rows.append((row['id'],row['name'],row))
    return rows

class SaveHistoryView:
    def __init__(self,panel,parent,*,on_load=None):
        self.panel=panel;self.monitor=panel.monitor;self.parent=parent;self.records={};self.future=None;self.closed=False;self.preview_image=None;self.signature=None
        self.on_load=on_load;self.loading=False
        self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='save-history')
        top=tk.Frame(parent,bg=BG);top.pack(fill='x',pady=(0,8));label(top,'История отката',18,bold=True,pack=False).pack(side='left')
        Tooltip(top,'Актуальное состояние и откат до него. Считается время реальной игры: паузы и закрытое приложение не расходуют историю.')
        box=tk.Frame(parent,bg=BG);box.pack(fill='x');self.tree=Table(box,columns=('name','time'),show='headings',height=8,selectmode='browse',style='Trainer.Treeview')
        self.tree.heading('name',text='Точка восстановления');self.tree.heading('time',text='Время сохранения');self.tree.column('name',width=285,minwidth=200);self.tree.column('time',width=185,minwidth=160)
        scroll=Scrollbar(box,command=self.tree.yview,height=1);scroll.pack(side='right',fill='y');self.tree.configure(yscrollcommand=scroll.set);self.tree.pack(fill='x',expand=True)
        self.tree.tag_configure('missing',foreground=MUTED);self.tree.tag_configure('current',foreground=GREEN);self.tree.bind('<<TreeviewSelect>>',self.selected)
        self.status=label(parent,'Загружаем историю…',10,MUTED,wraplength=490);self.status.pack_configure(pady=(8,0))
        self.detail=label(parent,'',11,TEXT,wraplength=490);self.detail.pack_configure(pady=(8,6));self.preview=tk.Label(parent,bg=BG);self.preview.pack(anchor='w')
        container=getattr(panel,'page_containers',{}).get('slots',parent)
        self.actions=tk.Frame(container,bg=BG,padx=4,pady=8)
        canvas=getattr(panel,'page_canvases',{}).get(str(container))
        if canvas:self.actions.pack(side='bottom',fill='x',before=canvas)
        else:self.actions.pack(fill='x')
        self.load=Button(self.actions,'Загрузить точку' if on_load else 'Восстановить',self.restore,variant='primary');self.load.pack(side='left',fill='x',expand=True,padx=(0,6))
        self.legacy=tk.BooleanVar(value=bool(on_load));Toggle(parent,'Все версии и именованные точки',self.legacy,lambda:self.refresh(force=True)).pack(fill='x')
        row=tk.Frame(parent,bg=BG);row.pack(fill='x',pady=8)
        if not on_load:Button(row,'Создать именованную точку…',self.named).pack(side='left')
        Button(row,'Обновить',lambda:self.refresh(force=True),variant='ghost').pack(side='right')
        self.home=Button(self.actions,'← К прохождениям',self.return_home,variant='ghost');self.home.pack(side='right',fill='x',expand=True)
        self.tree.bind('<Double-1>',lambda _:self.restore());parent.bind('<Destroy>',self.destroyed,add='+');parent.bind('<Map>',lambda _:self.refresh(),add='+');self.after=parent.after(250,self.poll);self.refresh()
    def refresh(self,select=None,force=False):
        if select:self.select_after=select
        if self.closed:return
        if self.future is not None:
            self.queued=True
            return
        self.home.configure(state='normal' if not self.loading and callable(getattr(self.monitor,'return_to_menu',None)) else 'disabled')
        self.future=self.pool.submit(read_history,self.monitor.folder,self.legacy.get())
    def poll(self):
        if self.closed:return
        if self.future and self.future.done():
            future=self.future;self.future=None
            try:self.fill(future.result())
            except Exception as e:self.status.configure(text='Не удалось прочитать историю: '+str(e),fg=AMBER)
            self.last_poll=time.monotonic()
            if getattr(self,'queued',False):self.queued=False;self.refresh()
        if self.parent.winfo_ismapped() and time.monotonic()-getattr(self,'last_poll',0)>=5:self.refresh()
        self.after=self.parent.after(250,self.poll)
    def fill(self,rows):
        signature=tuple((key,(r or {}).get('sha256'),(r or {}).get('created_at'),bool(r)) for key,_,r in rows)
        if signature==self.signature:return
        self.signature=signature;selected=self.tree.selection();children=self.tree.get_children()
        if children:self.tree.delete(*children)
        self.records={key:record for key,_,record in rows}
        for key,title,record in rows:
            self.tree.insert('','end',iid=key,values=(title,date_text(record) if record else 'Ещё нет истории'),tags=('current',) if key=='current' else ('missing',) if record is None else ())
        requested=getattr(self,'select_after',None);key=requested if requested in self.records else selected[0] if selected and selected[0] in self.records else 'current';self.select_after=None;self.tree.selection_set(key);self.selected()
        missing=sum(record is None for key,_,record in rows if key.startswith('age-'))
        self.status.configure(text='Более старые точки появятся по мере игры.' if missing else 'Все временные точки доступны. Перед откатом текущее состояние сохраняется отдельно.',fg=MUTED)
    def selected(self,_=None):
        chosen=self.tree.selection();key=chosen[0] if chosen else None;row=self.records.get(key)
        self.load.configure(state='normal' if not self.loading and row and (key!='current' or self.on_load) else 'disabled');self.preview.configure(image='');self.preview_image=None
        if not row:self.detail.configure(text='История на этот срок ещё не накопилась.');return
        summary=row.get('summary',row.get('telemetry'));text=summary_text(summary) if summary else 'Точная копия состояния игры · '+date_text(row)
        if row.get('age_seconds') is not None:text+='\nФактическая глубина отката: '+str(round(row['age_seconds']))+' с'
        self.detail.configure(text=text)
        directory=row['directory'];image=directory/('save-preview.png' if row.get('is_current') else 'preview.png')
        if not image.exists():image=directory/'preview.ppm'
        try:self.preview_image=tk.PhotoImage(master=self.parent,file=str(image));self.preview.configure(image=self.preview_image)
        except (OSError,tk.TclError):pass
    def restore(self):
        selected=self.tree.selection();key=selected[0] if selected else None;record=self.records.get(key)
        if self.loading or not record or key=='current' and not self.on_load:return
        try:
            if self.on_load:return self.on_load(record)
            self.monitor.pause(save=False)
            if record.get('is_backup'):self.monitor.load_backup(record['directory'])
            else:self.monitor.load_slot(record['id'])
            self.panel.show('overview')
        except Exception as error:self.monitor.error('Не удалось восстановить',error)
    def named(self):
        name=simpledialog.askstring('Точка восстановления','Название:',parent=self.panel.window,initialvalue='Перед важным действием')
        if name:
            try:self.legacy.set(True);self.monitor.create_slot(name)
            except Exception as error:self.monitor.error('Не удалось сохранить точку',error)
    def return_home(self):
        if self.loading:return
        callback=getattr(self.monitor,'return_to_menu',None)
        if callback:callback()
    def set_loading(self,value):
        self.loading=value;self.home.configure(state='disabled' if value else 'normal');self.selected()
        if value:self.status.configure(text='Проверяем точку и сохраняем актуальное состояние…',fg=MUTED)
    def destroyed(self,event):
        if event.widget is not self.parent:return
        self.closed=True;self.parent.after_cancel(self.after);self.pool.shutdown(wait=False,cancel_futures=True)
        self.preview_image=None
        del self.legacy
