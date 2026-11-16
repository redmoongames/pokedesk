from .i18n import literal
"""Asynchronous picker for a real exchange between two closed playthroughs."""
from concurrent.futures import ThreadPoolExecutor
from queue import SimpleQueue,Empty
from . import localized_tk as tk
from .ui import BG,MUTED,AMBER,GREEN,Button,Select,Toggle,label
from . import profile_trade
from .editions import EDITIONS

class ProfileTradeDialog:
    def __init__(self,home):
        self.home=home;self.future=None;self.mode=None;self.closed=False;self.preview=None;self.progress=SimpleQueue();self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='profile-exchange')
        self.window=tk.Toplevel(home.root);self.window.title('Обмен между прохождениями');self.window.configure(bg=BG);self.window.geometry('640x600');self.window.minsize(560,560);self.window.protocol('WM_DELETE_WINDOW',self.close);home.dialogs.append(self.window)
        body=tk.Frame(self.window,bg=BG,padx=20,pady=16);body.pack(fill='both',expand=True)
        label(body,'Настоящий link-обмен',20,bold=True)
        label(body,'Выберите два закрытых прохождения и Pokémon с каждой стороны. Перед обменом сохраняются обе резервные копии. Открытые игры недоступны.',11,MUTED,wraplength=590).pack_configure(pady=(6,12))
        rows=getattr(home,'rows',[]);self.profiles={literal(EDITIONS[r.get('game','firered')].name+' · '+r['name']+' · '+r['id'][-6:]):r['id'] for r in rows if not r.get('busy') and not r.get('error')};choices=list(self.profiles)
        self.games=[];self.mons=[];self.game_pickers=[];self.mon_pickers=[];self.mon_maps=[{},{}]
        for i,title in enumerate(('Первое прохождение','Второе прохождение')):
            label(body,title,13,bold=True).pack_configure(pady=(8,4));game=tk.StringVar(value=choices[min(i,len(choices)-1)] if choices else '');mon=tk.StringVar()
            pick=Select(body,game,values=choices,command=lambda _:self.invalidate());pick.pack(fill='x');pokemon=Select(body,mon,values=[]);pokemon.pack(fill='x',pady=(6,0));pokemon.configure(state='disabled')
            self.games.append(game);self.mons.append(mon);self.game_pickers.append(pick);self.mon_pickers.append(pokemon)
        self.load=Button(body,'Прочитать Pokémon',self.inspect,variant='ghost');self.load.pack(fill='x',pady=(14,8))
        self.roundtrip=tk.BooleanVar(value=False);self.roundtrip_toggle=Toggle(body,'Обменять туда и обратно · для эволюции',self.roundtrip);self.roundtrip_toggle.pack(fill='x')
        self.status=label(body,'Для обмена нужны минимум два Pokémon на каждой стороне. Сюжетные ограничения игры сохраняются.',11,MUTED,wraplength=590);self.status.pack_configure(pady=(10,10))
        self.start=Button(body,'Начать обмен',self.exchange,variant='primary');self.start.pack(fill='x',side='bottom');self.start.configure(state='disabled')
        if len(choices)<2:self.load.configure(state='disabled');self.status.configure(text='Нужны два закрытых прохождения. Вернитесь в меню из открытых игровых окон.',fg=AMBER)
        self.timer=self.window.after(100,self.poll)
        self.window.bind('<Destroy>',self.destroyed,add='+')
    def destroyed(self,event):
        if event.widget is not self.window or self.closed:return
        self.closed=True
        try:self.window.after_cancel(self.timer)
        except tk.TclError:pass
        self.pool.shutdown(wait=False,cancel_futures=True)
    def identifiers(self):return [self.profiles[v.get()] for v in self.games]
    def invalidate(self):self.preview=None;self.start.configure(state='disabled')
    def busy(self,value):
        for widget in [*self.game_pickers,self.load]:widget.configure(state='disabled' if value else 'normal')
        for widget in self.mon_pickers:widget.configure(state='disabled' if value or not self.preview else 'normal')
        self.start.configure(state='normal' if not value and self.preview else 'disabled')
    def inspect(self):
        if self.future:return
        try:
            ids=self.identifiers()
            if ids[0]==ids[1]:raise ValueError('Выберите два разных прохождения')
            self.invalidate();self.busy(True);self.status.configure(text='Читаем отдельные копии сохранений…',fg=MUTED);self.mode='preview';self.future=self.pool.submit(profile_trade.inspect,self.home.folder,ids)
        except Exception as error:self.status.configure(text=str(error),fg=AMBER);self.busy(False)
    def exchange(self):
        if self.future or not self.preview:return
        try:
            uids=[self.mon_maps[i][v.get()] for i,v in enumerate(self.mons)]
            self.busy(True);self.home.trade_busy=True;self.mode='exchange';self.status.configure(text='Создаём резервные копии и готовим команды…',fg=MUTED)
            self.future=self.pool.submit(profile_trade.exchange,self.home.folder,self.identifiers(),uids,[p['fingerprint'] for p in self.preview],roundtrip=self.roundtrip.get(),progress=self.progress.put)
        except Exception as error:self.home.trade_busy=False;self.status.configure(text=str(error),fg=AMBER);self.busy(False)
    def poll(self):
        if self.closed:return
        try:
            while True:self.status.configure(text=self.progress.get_nowait(),fg=MUTED)
        except Empty:pass
        if self.future and self.future.done():
            future=self.future;self.future=None
            try:
                result=future.result()
                if self.mode=='preview':
                    self.preview=result
                    for i,row in enumerate(result):
                        self.mon_maps[i]={m['nickname']+' · '+m['species']+' · Lv '+str(m['level'])+(' ★' if m['shiny'] else '')+(' · отряд' if m['location']=='party' else ' · PC '+str(m['box']+1))+ ' · '+m['uid'][-6:]:m['uid'] for m in row['inventory']['party']+row['inventory']['boxes'] if not m.get('is_egg')}
                        self.mon_pickers[i].configure(values=list(self.mon_maps[i]));self.mons[i].set(next(iter(self.mon_maps[i]),''))
                    if all(self.mon_maps):self.status.configure(text='Выберите Pokémon и режим обмена. Подготовка и публикация выполнятся на отдельных копиях.',fg=MUTED)
                    else:self.preview=None;self.status.configure(text='На каждой стороне должен быть хотя бы один Pokémon для выбора.',fg=AMBER)
                else:
                    self.preview=None;self.status.configure(text='Обмен завершён. Оба сохранения записаны; резервные копии находятся в Data/backups/actions/profile-trade-'+result['id'],fg=GREEN);self.home.refresh()
            except Exception as error:
                self.preview=None;self.status.configure(text=str(error),fg=AMBER);self.home.refresh()
            finally:self.home.trade_busy=False;self.busy(False)
        self.timer=self.window.after(100,self.poll)
    def close(self):
        if self.future:
            self.status.configure(text='Дождитесь завершения текущей операции. Результат будет проверен с обеих сторон.',fg=AMBER);return
        self.window.destroy()
