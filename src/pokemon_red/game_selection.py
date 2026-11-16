"""New playthrough form; imports and prologue execution stay off the UI thread."""
from concurrent.futures import ThreadPoolExecutor
from . import localized_tk as tk
from .localized_tk import filedialog
from .editions import EDITIONS,available,install_rom
from .ui import BG,CARD,TEXT,MUTED,AMBER,GREEN,Button,Segments,Toggle,Select,Stepper,label
from .scrolling import Scrollbar
from .i18n import t,literal,format_number
from .entity_names import species_name,nature_name
from .natures import NATURE_NAMES
from .nature_preferences import NatureFilter
from .iv_preferences_ui import IVPreferences
from .search_odds import starter_odds,summary
from .new_game_config import NewGameConfig,NAME_CHARS,STATS

class NatureOption(str):
    def __new__(cls,label,identifier):
        value=super().__new__(cls,str(label));value.identifier=identifier;return value

class NewGameDialog:
    def __init__(self,home):
        self.home=home;self.closed=False;self.future=None;self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='rom-import')
        self.window=tk.Toplevel(home.root);self.window.title(t('prologue.title'));self.window.configure(bg=BG);self.window.geometry('620x760');self.window.minsize(550,520);self.window.protocol('WM_DELETE_WINDOW',self.close)
        foot=tk.Frame(self.window,bg=BG,padx=20,pady=12);foot.pack(side='bottom',fill='x')
        self.status=label(foot,'',11,MUTED,wraplength=560)
        self.start=Button(foot,'Создать прохождение',self.create,variant='primary');self.start.pack(fill='x',pady=(8,0))
        shell=tk.Frame(self.window,bg=BG);shell.pack(fill='both',expand=True)
        self.canvas=tk.Canvas(shell,bg=BG,highlightthickness=0,yscrollincrement=1);scroll=Scrollbar(shell,command=self.canvas.yview);self.canvas.configure(yscrollcommand=scroll.set);scroll.pack(side='right',fill='y');self.canvas.pack(side='left',fill='both',expand=True)
        body=tk.Frame(self.canvas,bg=BG,padx=20,pady=16);item=self.canvas.create_window(0,0,window=body,anchor='nw');body.bind('<Configure>',lambda _:self.canvas.configure(scrollregion=self.canvas.bbox('all')));self.canvas.bind('<Configure>',lambda e:self.canvas.itemconfigure(item,width=e.width))
        label(body,'Выберите игру',19,bold=True);self.game=tk.StringVar(value='firered')
        for keys in (('firered','leafgreen'),('ruby','sapphire')):
            Segments(body,[(k,EDITIONS[k].name) for k in keys],self.game,lambda _:self.refresh()).pack(fill='x',pady=(8,0))
        label(body,'У каждого прохождения своё сохранение. Выбранная игра закрепляется за ним; имеющиеся прохождения сохраняются.',11,MUTED,wraplength=550).pack_configure(pady=(4,12))
        self.support=label(body,'',11,MUTED,wraplength=550)
        self.import_button=Button(body,'Подключить локальный ROM…',self.import_file,variant='ghost');self.import_button.pack(anchor='w',pady=6)
        self.skip=tk.BooleanVar(value=False);self.skip_toggle=Toggle(body,t('prologue.skip'),self.skip,self.refresh);self.skip_toggle.pack(fill='x',pady=(8,0));self.skip_support=label(body,'',10,MUTED,wraplength=550)
        self.options=tk.Frame(body,bg=BG)
        self.player_name=tk.StringVar(value='ALEX');self.rival_name=tk.StringVar(value='GARY');self.player_gender=tk.IntVar(value=0);self.starter=tk.IntVar(value=1);self.gender=tk.StringVar(value='any');self.shiny=tk.BooleanVar(value=False);self.nature=tk.IntVar(value=-1);self.ivs={key:tk.IntVar(value=0) for key in STATS}
        names=tk.Frame(self.options,bg=BG);names.pack(fill='x',pady=(9,0));names.columnconfigure((0,1),weight=1)
        for col,(title,var) in enumerate((('prologue.player_name',self.player_name),('prologue.rival_name',self.rival_name))):
            box=tk.Frame(names,bg=BG);box.grid(row=0,column=col,sticky='ew',padx=(0,8) if col==0 else (8,0));label(box,t(title),11,MUTED)
            entry=tk.Entry(box,textvariable=var,bg=CARD,fg=TEXT,insertbackground=TEXT,relief='flat',font=('Helvetica',14),validate='key',validatecommand=(self.window.register(lambda value:len(value)<=7 and all(c in NAME_CHARS for c in value)),'%P'));entry.pack(fill='x',ipady=7)
        label(self.options,t('prologue.name_rules'),10,MUTED,wraplength=540).pack_configure(pady=(4,9))
        label(self.options,t('prologue.player_gender'),11,MUTED);Segments(self.options,[(0,t('prologue.boy')),(1,t('prologue.girl'))],self.player_gender).pack(fill='x')
        label(self.options,t('prologue.starter'),13,bold=True).pack_configure(pady=(12,4));Segments(self.options,[(n,species_name(n)) for n in (1,4,7)],self.starter).pack(fill='x')
        label(self.options,t('prologue.gender'),11,MUTED).pack_configure(pady=(9,2));Segments(self.options,[(k,t('prologue.'+k)) for k in ('any','male','female')],self.gender).pack(fill='x')
        Toggle(self.options,t('capture.shiny'),self.shiny).pack(fill='x',pady=(6,0))
        self.nature_filter=NatureFilter(self.options,command=self.refresh_odds,compact=True)
        self.search_workers=tk.IntVar(value=2);workers=tk.Frame(self.options,bg=BG);workers.pack(fill='x',pady=(7,3))
        label(workers,t('capture.workers'),11,pack=False).pack(side='left');Stepper(workers,self.search_workers,1,4).pack(side='right')
        label(self.options,t('odds.workers_help'),10,MUTED,wraplength=540)
        self.iv_editor=IVPreferences(self.options,command=self.refresh_odds);self.ivs=self.iv_editor.values
        odds_box=tk.Frame(self.options,bg=CARD,padx=10,pady=8);odds_box.pack(fill='x',pady=(8,3));label(odds_box,t('odds.title'),12,bold=True)
        self.odds=label(odds_box,'',10,MUTED,wraplength=520)
        odds_box.bind('<Configure>',lambda e:self.odds.configure(wraplength=max(180,e.width-20)))
        self.warning=label(self.options,'',10,AMBER,wraplength=540)
        label(self.options,t('prologue.hint'),10,MUTED,wraplength=540).pack_configure(pady=(10,5))
        self.traces=[(var,var.trace_add('write',lambda *_:self.refresh_odds())) for var in (self.gender,self.shiny,self.nature)]
        self.refresh()
    def config(self):
        try:workers=self.search_workers.get()
        except tk.TclError:raise ValueError(t('odds.invalid_workers')) from None
        try:return NewGameConfig.parse(dict(player_name=self.player_name.get(),rival_name=self.rival_name.get(),player_gender=self.player_gender.get(),species_id=self.starter.get(),gender=self.gender.get(),shiny=self.shiny.get(),nature=None if self.nature.get()==-1 else self.nature.get(),natures=self.nature_filter.selected,search_workers=workers,priority_ivs=self.iv_editor.preferred,min_ivs=[self.ivs[k].get() for k in STATS]),self.game.get())
        except tk.TclError:raise ValueError(t('prologue.invalid_ivs')) from None
    def refresh_odds(self):
        try:attempts=self.config().expected_attempts()
        except (ValueError,tk.TclError) as error:
            self.odds.configure(text=str(error));self.warning.configure(text='');return
        self.odds.configure(text=summary(starter_odds(self.config()),starter=True))
        self.warning.configure(text=t('prologue.rare') if attempts>100000 else '')
    def refresh(self):
        ready=available(self.home.folder,self.game.get());busy=self.future is not None;spec=EDITIONS[self.game.get()]
        supported=self.game.get() in ('firered','leafgreen')
        if not supported:self.skip.set(False)
        self.skip_toggle.configure(state='normal' if supported and not busy else 'disabled')
        self.start.configure(text=t('prologue.create') if self.skip.get() else 'Создать прохождение',state='normal' if ready and not busy else 'disabled');self.import_button.configure(state='normal' if self.game.get()!='firered' and not busy else 'disabled')
        self.support.configure(text='Коллекция, прокачка, ловля, автопутешествия и link-обмен. Доступность маршрутов и обмена зависит от сюжета прохождения.')
        self.skip_support.configure(text='' if supported else t('prologue.kanto_only'))
        if self.skip.get():self.options.pack(fill='x');self.refresh_odds()
        else:self.options.pack_forget()
        if not busy:self.status.configure(text='Готово · '+spec.label if ready else f'Подключите {spec.label}: английский GBA ROM версии 1.{spec.revision}.',fg=GREEN if ready else AMBER)
    def import_file(self):
        path=filedialog.askopenfilename(parent=self.window,title=EDITIONS[self.game.get()].label,filetypes=[('Game Boy Advance ROM','*.gba')])
        if not path:return
        self.future=self.pool.submit(install_rom,self.home.folder,path,self.game.get());self.refresh();self.status.configure(text='Проверяем ROM и подготавливаем справочник…',fg=MUTED);self.window.after(100,self.poll)
    def poll(self):
        if self.closed:return
        if not self.future.done():self.window.after(100,self.poll);return
        future=self.future;self.future=None
        try:future.result();self.refresh()
        except Exception as error:self.refresh();self.status.configure(text=str(error),fg=AMBER)
    def create(self):
        if self.future is not None:return
        try:
            config=self.config().json() if self.skip.get() else None
            row=self.home.store.create(game=self.game.get(),prologue=config);skip=self.skip.get();self.close()
            if skip:self.home.choose(row,start_prologue=True,start_paused=True)
            else:self.home.choose(row)
        except Exception as error:
            if not self.closed:self.status.configure(text=str(error),fg=AMBER)
            else:raise
    def close(self):
        if self.closed:return
        self.closed=True
        for var,token in self.traces:var.trace_remove('write',token)
        self.traces=[];self.pool.shutdown(wait=False,cancel_futures=True);self.window.destroy()
