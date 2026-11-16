"""Playthrough picker before creating a live emulator session."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import base64,fcntl,signal
from . import localized_tk as tk
import gc
from .localized_tk import messagebox,simpledialog
from .profiles import Profiles
from .editions import EDITIONS
from .ui import BG,CARD,TEXT,MUTED,GREEN,AMBER,Button,Segments,Toggle,label,theme
from .scrolling import Scrollbar
from .settings import Settings
from .i18n import configure as configure_i18n,set_locale,t,LOCALE_NAMES,literal
from .ui import Select
from .save_history_ui import summary_text,date_text
from types import SimpleNamespace
from .profile_restore import restore_profile

def read_profiles(store,deleted=False):
    from .profile_trade import recover_all
    recover_all(store.root)
    result=[]
    for row in store.list(deleted=deleted):
        try:
            item=store.summary(row)
            from .acquisition import read_json
            item['prologue']=read_json(store.folder(row)/'Data/new-game.json',{})
            result.append(item)
        except Exception as e:result.append(dict(row,error=str(e),busy=False))
    return result

class StartupHome:
    def __init__(self,root,folder,choose):
        self.root=root;self.folder=Path(folder);self.store=Profiles(folder);self.choose=choose;self.closed=False;self.images=[];self.future=None;self.dialogs=[];self.history=None;self.management_future=None;self.notice='';self.notice_error=False;self.mode=tk.StringVar(value='active')
        self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='save-previews');self.settings=Settings(folder)
        configure_i18n(folder,self.settings['language'])
        root.title('PokéDesk');root.configure(bg=BG);root.resizable(True,True);root.geometry('780x650');root.minsize(700,470);theme(root)
        self.shell=tk.Frame(root,bg=BG);self.shell.pack(fill='both',expand=True)
        head=tk.Frame(self.shell,bg=BG,padx=20,pady=14);head.pack(fill='x');label(head,'PokéDesk',20,bold=True,pack=False).pack(side='left');Button(head,'Настройки',self.preferences,variant='ghost').pack(side='right')
        self.heading=label(self.shell,'Выбери прохождение',14,MUTED);self.heading.pack_configure(padx=20,pady=(0,10))
        Segments(self.shell,[('active',t('sessions.active')),('deleted',t('sessions.deleted'))],self.mode,lambda _:self.refresh()).pack(fill='x',padx=20,pady=(0,10))
        self.content=tk.Frame(self.shell,bg=BG);self.content.pack(fill='both',expand=True,padx=16)
        self.canvas=tk.Canvas(self.content,bg=BG,highlightthickness=0,yscrollincrement=1);scroll=Scrollbar(self.content,command=self.canvas.yview);self.canvas.configure(yscrollcommand=scroll.set);scroll.pack(side='right',fill='y');self.canvas.pack(side='left',fill='both',expand=True)
        self.body=tk.Frame(self.canvas,bg=BG);item=self.canvas.create_window(0,0,window=self.body,anchor='nw');self.body.bind('<Configure>',lambda _:self.canvas.configure(scrollregion=self.canvas.bbox('all')));self.canvas.bind('<Configure>',lambda e:self.canvas.itemconfigure(item,width=e.width));root._scroll_fallback=lambda:self.canvas
        bottom=self.bottom=tk.Frame(self.shell,bg=BG,padx=20,pady=12);bottom.pack(fill='x');Button(bottom,'+ Новое прохождение',self.create,variant='primary').pack(side='left');Button(bottom,'Обновить',self.refresh,variant='ghost').pack(side='right')
        Button(bottom,'Обмен Pokémon…',self.exchange,variant='ghost').pack(side='left',padx=(8,0))
        self.status=label(self.shell,'Читаем сохранения…',11,MUTED);self.status.pack_configure(padx=20,pady=(0,12));self.refresh();self.after=root.after(100,self.poll)
    def exchange(self):
        from .profile_trade_ui import ProfileTradeDialog
        if getattr(self,'management_future',None):return
        dialog=getattr(self,'trade_dialog',None)
        if dialog is not None and not dialog.closed:
            dialog.window.lift();return
        if not getattr(self,'trade_busy',False):self.trade_dialog=ProfileTradeDialog(self)
    def refresh(self,*,keep_notice=False):
        if self.future or self.management_future:return
        if not keep_notice:self.notice='';self.notice_error=False
        # Dispose closed Tk object cycles on the UI thread before a preview
        # worker allocates objects and potentially triggers Python's collector.
        gc.collect()
        self.status.configure(text='Читаем сохранения…',fg=MUTED)
        self.future_mode=self.mode.get();self.future=self.pool.submit(read_profiles,self.store,self.future_mode=='deleted')
    def poll(self):
        if self.closed:return
        if self.management_future and self.management_future.done():
            future=self.management_future;self.management_future=None
            try:future.result();self.notice=self.management_message;self.notice_error=False
            except Exception as error:self.notice=str(error);self.notice_error=True
            self.refresh(keep_notice=True)
        if self.future and self.future.done():
            future=self.future;self.future=None
            try:
                rows=future.result()
                if self.future_mode==self.mode.get():self.fill(rows)
                else:self.refresh(keep_notice=True)
            except Exception as e:self.status.configure(text=str(e),fg=AMBER)
        self.after=self.root.after(100,self.poll)
    def fill(self,rows):
        if self.history is not None:return
        for w in self.body.winfo_children():w.destroy()
        self.images=[];self.rows=rows;self.cards=[];deleted=self.mode.get()=='deleted';busy=self.management_future is not None
        if not rows:label(self.body,t('sessions.empty_deleted') if deleted else t('sessions.empty'),12,MUTED,wraplength=600).pack_configure(padx=4,pady=20)
        for row in rows:
            box=tk.Frame(self.body,bg=CARD,padx=12,pady=12);box.pack(fill='x',pady=(0,10));preview=tk.Frame(box,bg='#05080c',width=240,height=160);preview.pack(side='left',padx=(0,16));preview.pack_propagate(False)
            image=row.get('preview');photo=None
            if image:
                try:photo=tk.PhotoImage(master=self.root,data=base64.b64encode(image),format='png');self.images.append(photo)
                except tk.TclError:pass
            tk.Label(preview,image=photo or '',text='' if photo else 'Новое прохождение' if not row.get('error') else 'Нет предпросмотра',fg=MUTED,bg='#05080c',font=('Helvetica',11)).pack(expand=True)
            info=tk.Frame(box,bg=CARD);info.pack(side='left',fill='both',expand=True);label(info,literal(EDITIONS[row.get('game','firered')].name+' · '+row['name']),15,bold=True,wraplength=380).pack_configure(pady=(0,7));metadata=row.get('metadata') or {};summary=metadata.get('summary')
            def wrap(event,frame=info):
                for child in frame.winfo_children():
                    if isinstance(child,tk.Label) and int(child.cget('wraplength') or 0):child.configure(wraplength=max(180,event.width-4))
            info.bind('<Configure>',wrap)
            text=summary_text(summary) if not row.get('error') else 'Не удалось прочитать сохранение: '+row['error'];label(info,text,11,TEXT,wraplength=380).pack_configure(pady=(0,6))
            label(info,date_text(metadata) if metadata.get('captured_at') else 'Сохранение появится после начала игры',10,MUTED).pack_configure(pady=(0,8))
            if not deleted and row.get('prologue') and row['prologue'].get('status')!='complete':
                resume=Button(info,t('prologue.resume'),lambda r=row:self.choose(r,start_prologue=True),height=30)
                resume.pack(fill='x',side='bottom',pady=(5,0));resume.configure(state='disabled' if busy or row.get('busy') else 'normal')
            actions=tk.Frame(info,bg=CARD);actions.pack(fill='x',side='bottom')
            if deleted:
                button=Button(actions,t('sessions.restore'),lambda r=row:self.restore(r),variant='primary',height=32);button.pack(side='left');button.configure(state='disabled' if busy or row.get('busy') else 'normal');history=None
                label(info,t('sessions.deleted_date',date=row.get('deleted_at','')[:10]),10,MUTED).pack_configure(pady=(0,5))
            else:
                button=Button(actions,'Уже открыто' if row.get('busy') else 'Продолжить' if metadata.get('captured_at') else 'Начать',lambda r=row:self.choose(r),variant='primary',height=32);button.configure(state='disabled' if busy or row.get('busy') or row.get('error') else 'normal');button.pack(side='left')
                history=Button(actions,'История',lambda r=row:self.open_history(r),height=32);history.pack(side='left',padx=(6,0));history.configure(state='disabled' if busy or row.get('busy') else 'normal')
                from .session_ui import profile_actions
                more=Button(actions,'⋯',width=34,height=32,variant='ghost');more.configure(command=lambda r=row,b=more:profile_actions(self,r,b),state='disabled' if busy else 'normal');more.pack(side='right')
                from .tooltips import Tooltip
                Tooltip(more,t('sessions.actions'))
            self.cards.append(dict(row=row,button=button,history=history,preview=preview))
        self.status.configure(text=self.notice,fg=AMBER if self.notice_error else MUTED)
    def open_history(self,row):
        if self.history is not None or self.store.busy(row):return
        from .save_history_ui import SaveHistoryView
        for child in self.body.winfo_children():child.destroy()
        self.images.clear();self.bottom.pack_forget();self.heading.configure(text='История · '+row['name']);self.canvas.yview_moveto(0)
        self.history_body=tk.Frame(self.body,bg=BG);self.history_body.pack(fill='x',padx=4)
        context=SimpleNamespace(folder=self.store.folder(row),return_to_menu=self.close_history,error=self.history_error)
        panel=SimpleNamespace(monitor=context,window=self.root,page_containers={'slots':self.content},page_canvases={str(self.content):self.canvas})
        self.history=SaveHistoryView(panel,self.history_body,on_load=lambda record:self.choose(row,record))
        self.status.configure(text='Выбери сохранение. Перед откатом актуальная версия будет сохранена отдельно.',fg=MUTED)
    def close_history(self):
        if self.history is None or self.history.loading:return
        self.history.actions.destroy();self.history_body.destroy();self.history=None
        self.heading.configure(text='Выбери прохождение');self.bottom.pack(fill='x',before=self.status);self.canvas.yview_moveto(0);self.refresh()
    def history_error(self,title,error):
        text=title+': '+str(error);self.status.configure(text=text,fg=AMBER)
        if self.history is not None:self.history.status.configure(text=text,fg=AMBER)
    def create(self):
        if self.management_future or getattr(self,'trade_busy',False):return
        from .game_selection import NewGameDialog
        dialog=NewGameDialog(self);self.dialogs.append(dialog.window)
    def manage(self,command,*args,message):
        if self.management_future or self.future or getattr(self,'trade_busy',False):
            self.status.configure(text=t('sessions.wait'),fg=AMBER);return
        self.management_message=message;self.management_future=self.pool.submit(command,*args)
        self.fill(getattr(self,'rows',[]));self.status.configure(text=t('sessions.working'),fg=MUTED)
    def rename(self,row):
        if self.management_future:return
        name=simpledialog.askstring(t('design.rename'),t('sessions.name'),parent=self.root,initialvalue=row['name'])
        if name:self.manage(self.store.rename,row['id'],name,message=t('sessions.renamed'))
    def duplicate(self,row):
        if self.management_future or row.get('busy'):return
        name=simpledialog.askstring(t('sessions.duplicate'),t('sessions.name'),parent=self.root,initialvalue=str(t('sessions.copy_name',name=row['name'][:48])))
        if name:self.manage(self.store.duplicate,row['id'],name,message=t('sessions.copied'))
    def delete(self,row):
        if self.management_future or row.get('busy'):return
        from .session_ui import Confirmation
        dialog=Confirmation(self.root,title=t('sessions.delete_question',name=row['name']),message=t('sessions.delete_message'),confirm=t('sessions.delete'),danger=True,on_confirm=lambda:self.manage(self.store.archive,row['id'],message=t('sessions.removed')))
        self.dialogs.append(dialog.window)
        return dialog
    def restore(self,row):
        self.manage(self.store.restore,row['id'],message=t('sessions.restored'))
    def preferences(self):
        window=tk.Toplevel(self.root);window.title('Настройки приложения');window.configure(bg=BG);window.resizable(False,False);window.transient(self.root);body=tk.Frame(window,bg=BG,padx=20,pady=16);body.pack(fill='both',expand=True)
        self.dialogs.append(window)
        language=tk.StringVar(value=self.settings['language'])
        label(body,t('settings.language'),14,bold=True)
        def change_language(code):
            self.settings.set('language',code);set_locale(code);self.fill(getattr(self,'rows',[]))
        Segments(body,list(LOCALE_NAMES.items()),language,change_language).pack(fill='x',pady=(8,15))
        label(body,'Размер игрового окна',14,bold=True);scale=tk.IntVar(value=self.settings['scale']);Segments(body,[(i,str(i)+'×') for i in range(1,6)],scale,lambda v:self.settings.set('scale',v)).pack(fill='x',pady=(8,15))
        sound=tk.BooleanVar(value=self.settings['sound_enabled']);Toggle(body,'Звук игры',sound,lambda:self.settings.set('sound_enabled',sound.get())).pack(fill='x')
        overlay=tk.BooleanVar(value=self.settings['ai_control_overlay']);Toggle(body,'Показывать режим управления ИИ',overlay,lambda:self.settings.set('ai_control_overlay',overlay.get())).pack(fill='x',pady=(8,0))
        label(body,'Лёгкий фильтр, подсказка и скорость во время работы ИИ.',10,MUTED,wraplength=400).pack_configure(pady=(3,0))
        label(body,'Превью сохранений всегда показано в исходных 240×160. Автосохранение — каждые 5 секунд игры; глубина истории — до 30 минут.',11,MUTED,wraplength=400).pack_configure(pady=(12,0));Button(body,'Готово',window.destroy,variant='primary').pack(fill='x',pady=(16,0))
    def close(self):
        self.closed=True;self.root.after_cancel(self.after);self.pool.shutdown(wait=False,cancel_futures=True)
        self.images.clear()
        for dialog in self.dialogs:
            if dialog.winfo_exists():dialog.destroy()

class SessionWindow(tk.Toplevel):
    """The monitor's Tk API, hosted inside the launcher's single interpreter."""
    def __getattr__(self,name):return getattr(self.tk,name)

class Application:
    def __init__(self,root,folder,*,paused=False):
        self.root=root;self.folder=Path(folder);self.paused=paused;self.store=Profiles(folder);self.monitor=None;self.home=None;self.quitting=False;self.session_window=None;self.restore_future=None
        self.root.protocol('WM_DELETE_WINDOW',self.quit);self.show_home()
    def show_home(self):
        if self.quitting:self.root.destroy();return
        self.root.deiconify();self.root.configure(menu='');self.root._scroll_delta_reader=None
        self.home=StartupHome(self.root,self.folder,self.choose);self.root.createcommand('::tk::mac::Quit',self.quit)
        self.root.report_callback_exception=self.menu_error
    def menu_error(self,kind,error,tb):messagebox.showerror('Pokémon',str(error),parent=self.root)
    def choose(self,row,checkpoint=None,*,start_paused=None,start_prologue=False):
        if self.monitor is not None or self.restore_future is not None:return
        if self.home and (getattr(self.home,'trade_busy',False) or getattr(self.home,'management_future',None) is not None):self.home.status.configure(text=t('sessions.wait'),fg=AMBER);return
        try:row=self.store.get(row['id'])
        except ValueError as error:self.home.status.configure(text=str(error),fg=AMBER);return
        if self.store.busy(row):self.home.status.configure(text='Это прохождение уже открыто.',fg=AMBER);return
        if checkpoint is not None and not checkpoint.get('is_current'):
            self.home.history.set_loading(True)
            self.restore_future=self.home.pool.submit(restore_profile,self.store.folder(row),checkpoint)
            self.root.after(50,lambda:self.poll_restore(row));return
        destination=self.store.folder(row);settings=Settings(destination);global_settings=Settings(self.folder)
        for key in ('scale','sound_enabled','volume','ai_control_overlay','language'):settings.values[key]=global_settings[key]
        settings.values.update(autosave_seconds=5,autosave_enabled=True,panel_on_start=True);settings.save()
        self.home.close();self.home.shell.destroy();self.root.withdraw()
        gc.collect()
        self.bindings={seq:self.root.tk.call('bind','all',seq) for seq in ('<KeyPress>','<KeyRelease>')}
        before_commands=set(self.root._tclCommands or [])
        self.before_timers=set(self.root.tk.call('after','info'))
        window=self.session_window=SessionWindow(self.root)
        try:
            from .gui import Monitor
            self.monitor=Monitor(window,destination,paused=self.paused if start_paused is None else start_paused)
        except Exception as error:
            window.destroy();self.monitor=None;messagebox.showerror('Не удалось открыть прохождение',str(error),parent=self.root);self.show_home();return
        monitor=self.monitor;monitor.application_folder=self.folder;monitor.menu_hook=self.install_menu;monitor.return_to_menu=self.request_back;monitor.profile_name=row['name'];monitor.new_game=self.request_back
        window.title(literal('PokéDesk · '+EDITIONS[row.get('game','firered')].name+' · '+row['name']))
        self.global_commands=set(self.root._tclCommands or [])-before_commands
        native_input=getattr(monitor,'input',None) or getattr(monitor,'game',None)
        self.root._scroll_delta_reader=native_input.current_scroll_delta;self.root.report_callback_exception=monitor.callback_error
        window.protocol('WM_DELETE_WINDOW',self.request_back);window.createcommand('::tk::mac::Quit',self.quit)
        window.bind('<Destroy>',self.destroyed,add='+')
        self.install_menu(monitor)
        if start_prologue:
            def begin():
                if self.monitor is not monitor or monitor.closed:return
                if not monitor.ready:window.after(30,begin);return
                monitor.operation.begin('prologue',{})
            window.after(30,begin)
    def poll_restore(self,row):
        if not self.restore_future.done():self.root.after(50,lambda:self.poll_restore(row));return
        future=self.restore_future;self.restore_future=None
        self.home.history.set_loading(False)
        try:future.result()
        except Exception as error:
            self.home.history_error('Не удалось загрузить точку',error)
            if self.quitting:self.quit()
            return
        if self.quitting:self.quit()
        else:self.choose(row,start_paused=True)
    def install_menu(self,monitor):
        root=monitor.window;menu=tk.Menu(root,tearoff=False);menu.add_command(label='Выбрать прохождение…',command=self.request_back);menu.add_command(label='Сохранить',command=lambda:monitor.save(manual=True));menu.add_command(label='Завершить приложение',command=self.quit)
        existing=root.nametowidget(root.cget('menu'));existing.insert_cascade(0,label='Прохождение',menu=menu)
        for i in range((existing.index('end') or 0)+1):
            if existing.type(i)!='cascade' or getattr(existing,'source_label',lambda index:existing.entrycget(index,'label'))(i) not in ('Сессия','Session'):continue
            session=root.nametowidget(existing.entrycget(i,'menu'))
            for j in range((session.index('end') or 0)+1):
                if session.type(j)!='command':continue
                title=getattr(session,'source_label',lambda index:session.entrycget(index,'label'))(j)
                if title.startswith('Начать новую игру'):session.entryconfigure(j,label='Новое прохождение…',command=self.request_back)
                if title.startswith('Слоты сохранений'):session.entryconfigure(j,label='История сохранений…')
    def request_back(self):
        if self.monitor:
            from .session_ui import confirm_return_to_menu
            return confirm_return_to_menu(self.monitor,self.back)
    def back(self):
        self.quitting=False
        if self.monitor:self.monitor.close()
    def quit(self):
        if self.home and getattr(self.home,'trade_busy',False):self.home.status.configure(text='Завершаем обмен перед закрытием…',fg=AMBER);return
        self.quitting=True
        if self.home and getattr(self.home,'management_future',None) is not None:
            self.home.status.configure(text=t('sessions.finishing'),fg=MUTED);self.root.after(100,self.quit);return
        if self.restore_future is not None:
            self.home.status.configure(text='Завершаем сохранение перед закрытием…',fg=MUTED);return
        if self.monitor:self.monitor.close()
        else:
            if self.home and not self.home.closed:self.home.close()
            self.root.destroy()
    def destroyed(self,event):
        if event.widget is self.session_window:self.root.after_idle(self.session_finished)
    def session_finished(self):
        # Toplevel destruction does not discard Tcl's pending `after` queue.
        # Cancel session callbacks and restore global keyboard bindings before
        # opening another profile in the same application interpreter.
        for timer in set(self.root.tk.call('after','info'))-self.before_timers:
            try:self.root.after_cancel(timer)
            except tk.TclError:pass
        for seq,script in self.bindings.items():self.root.tk.call('bind','all',seq,script)
        for command in self.global_commands:
            if command in (self.root._tclCommands or []):self.root.deletecommand(command)
        self.monitor=None;self.session_window=None;self.root._scroll_delta_reader=None;self.root.report_callback_exception=self.menu_error
        gc.collect()  # Dispose closed Tk variables/images on their UI thread.
        self.show_home()

def run(folder:Path,*,paused=False):
    folder=Path(folder).resolve();(folder/'Data').mkdir(parents=True,exist_ok=True)
    with (folder/'Data/.application.lock').open('a') as app_lock:
        try:fcntl.flock(app_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            root=tk.Tk();root.withdraw();messagebox.showinfo('Pokémon','Приложение уже открыто.',parent=root);root.destroy();return
        root=tk.Tk();application=Application(root,folder,paused=paused)
        signal.signal(signal.SIGTERM,lambda *_:root.after_idle(application.quit));signal.signal(signal.SIGINT,lambda *_:root.after_idle(application.quit))
        root.mainloop()

