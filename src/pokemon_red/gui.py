"""Native windows consume detached snapshots; the UI never steps or reads a core."""
from __future__ import annotations
from concurrent.futures import CancelledError
from copy import deepcopy
from pathlib import Path
import signal,time,traceback,queue,threading
from . import localized_tk as tk
from .localized_tk import messagebox
from .engine import BUTTONS,ROM_SHA1
from .i18n import configure as configure_i18n,set_locale,get_locale,LOCALE_NAMES,t
from .editions import edition
from .game_adapters import adapter
from .engine_runtime import EngineRuntime
from .runtime_views import NativeInput,AutomationView,HistoryView,OperationView,DeliveryView
from .settings import Settings
from .ai_overlay import AIOverlay,tint_video
from .slots import Slots
from .diagnostics import Diagnostics
from .event_loop import EventPump
from .speeds import normalize_speed
from .keyboard import COMMAND_MASK,MAC_KEYS,event_key

class Monitor:
    def __init__(self,root,folder,*,paused,runtime_factory=EngineRuntime):
        self.window=root;self.folder=Path(folder);self.settings=Settings(self.folder);self.slots=Slots(self.folder)
        configure_i18n(self.folder,self.settings['language'])
        self.diagnostics=Diagnostics(self.folder);self.input=NativeInput(self.folder)
        self.ready=False;self.closed=False;self.closing=False;self.paused=paused;self.close_requested=False
        self.model=None;self.status={};self.last_state={'ready':False,'frame':0,'party':[]};self.last_inventory={}
        self.panel=None;self.battle_panel=None;self.prologue_marker=None;self._context_key=None;self.keys=set();self._held_keys={};self.notice='Загружаем сессию…';self.safety_notice=None
        self.pending_takeover=0;self.pending_start=False;self.pending_writes=[];self.callbacks=[]
        self.last_panel=0.;self.last_video=0.;self.last_metadata=0.;self._model_sequence=0;self._inventory_request=None
        self._bag_request=None;self._navigation_request=None;self._navigation_at=0.;self._navigation_revision=None
        self._render_key=None;self._preferences_pending=False;self._preferences_version=0
        self.automation=AutomationView(self);self.history=HistoryView(self);self.operation=OperationView(self);self.delivery=DeliveryView(self)
        root._scroll_delta_reader=self.input.current_scroll_delta
        root.title('PokéDesk · '+edition(self.folder).name);root.configure(bg='black');root.resizable(False,False)
        root.protocol('WM_DELETE_WINDOW',self.close);root.createcommand('::tk::mac::Quit',self.close)
        root.report_callback_exception=self.callback_error
        self.canvas=tk.Canvas(root,bg='black',highlightthickness=0,takefocus=True);self.canvas.pack()
        self.canvas.bind('<Expose>',lambda _:setattr(self,'_render_key',None))
        self.canvas_image=self.canvas.create_image(0,0,anchor='nw')
        self.ai_overlay=AIOverlay(self.canvas)
        self.pause_shade=self.canvas.create_rectangle(0,0,0,0,fill='#101820',outline='',state='hidden')
        self.pause_title=self.canvas.create_text(0,0,text='Загрузка…',fill='white',state='hidden')
        self.pause_hint=self.canvas.create_text(0,0,text='',fill='#b9ccd5',state='hidden',justify='center')
        self.canvas.tag_bind(self.pause_hint,'<Button-1>',lambda _:self.show_saved_encounters() if getattr(self,'_capture_saved_available',False) else None)
        self.canvas.bind('<Button-1>',lambda _:self.canvas.focus_set())
        root.bind('<KeyPress>',self.key_down);root.bind('<KeyRelease>',self.key_up)
        root.bind_all('<KeyRelease>',self.key_up,add='+');root.bind_all('<KeyPress>',self.shortcut_down)
        root.bind('<FocusOut>',self.focus_out);root.bind('<FocusIn>',self.focus_in)
        root.bind('<space>',self.toggle_pause);root.bind('<Escape>',self.emergency_stop)
        self.build_menu();self.set_scale(self.settings['scale'],persist=False)
        self.event_pump=EventPump(root,self.pump_background,fallback_ms=8)
        self.runtime=runtime_factory(self.folder,paused=paused,notify=self.event_pump.notify)
        self._last_preferences_sent=deepcopy(self.settings.values);self.settings.save_hook=self._settings_changed
        root.after(8,self.tick);root.after(100,self.canvas.focus_set)
    @property
    def frame(self):return self.model.frame if self.model else 0
    @property
    def generation(self):return self.model.generation if self.model else 0
    @property
    def simulation_speed(self):return self.status.get('speed',self.settings['speed'])
    @property
    def automatic_speed_info(self):return self.status.get('automatic_speed',dict(enabled=False,speed=None,phase='Ручная скорость'))
    @property
    def measured_fps(self):return self.status.get('fps',0.)
    @property
    def session_transition(self):return self.status.get('transition',False)
    @property
    def save_failed(self):return self.status.get('save_failed',False)
    @property
    def last_saved_frame(self):return self.status.get('last_saved_frame',0)
    @property
    def last_saved_at(self):return self.status.get('last_saved_at')
    def watch(self,future,success=None,failure=None):self.callbacks.append((future,success,failure));return future
    def command(self,method,*args):
        if self.closed:return None
        return self.watch(self.runtime.submit(method,*args),None,lambda error:self.error('Ошибка действия',error))
    def _poll_callbacks(self):
        callbacks,self.callbacks=self.callbacks,[]
        for future,success,failure in callbacks:
            if not future.done():self.callbacks.append((future,success,failure));continue
            try:value=future.result()
            except CancelledError:pass
            except Exception as error:
                if failure:failure(error)
            else:
                if success:success(value)
    def _adopt(self):
        snapshot=self.runtime.latest
        if snapshot is None or snapshot.sequence==self._model_sequence:return False
        if self.model and self.model.generation!=snapshot.generation:self._navigation_revision=None
        self._model_sequence=snapshot.sequence;self.model=snapshot;self.status=snapshot.status
        self.last_state=snapshot.state;self.last_inventory=snapshot.inventory
        self.paused=self.status['paused'];self.closing=self.status['closing'];self.notice=self.status['notice']
        self.safety_notice=self.status['safety_notice'];self.pending_start=self.status['pending_start']
        self.pending_writes=[True] if self.status['saving'] else []
        if snapshot.epoch>=self.pending_takeover:self.pending_takeover=0
        self._preferences_pending=self.status.get('preferences_version',0)<self._preferences_version
        if not self._preferences_pending:
            self.settings.values['speed']=self.status['settings']['speed'];self._last_preferences_sent['speed']=self.settings['speed']
        return True
    def pump_background(self):
        if self.closed:return
        if not self.ready and self.runtime.ready.done():
            try:self.runtime.ready.result()
            except BaseException as error:
                self.closed=True;self.event_pump.close();messagebox.showerror('Pokémon',str(error),parent=self.window);self.window.destroy();return
            self.ready=True;self._adopt()
            def starter(marker):
                self.prologue_marker=marker
                if marker.get('status')!='complete':self.show_battle_panel()
            self.watch(self.runtime.submit('prologue_config'),starter,lambda error:None)
            if self.settings['panel_on_start']:
                self.show_panel()
                self.show_battle_panel()
                self.arrange_windows()
        self._adopt();self._poll_callbacks()
        while True:
            try:kind,data=self.runtime.events.get_nowait()
            except queue.Empty:break
            if kind=='show_panel':
                # Engine attention changes context, never the user's trainer route.
                if self.panel is None:self.show_panel()
                self.show_battle_panel()
            elif kind=='battle':self.show_battle_panel()
            elif kind=='focus_game':self.window.after_idle(self.focus_game)
            elif kind=='slots_changed' and self.panel and getattr(self.panel,'slot_tree',None) and self.panel.slot_tree.winfo_viewable():self.panel.refresh_slots(select=data['identifier'])
            elif kind=='error':messagebox.showerror(data['title'],data['message'],parent=self.panel.window if self.panel else self.window)
            elif kind=='close_failed':
                self.close_requested=False;self.closing=False
                if messagebox.askretrycancel('Не удалось сохранить',data['message']+'\n\nПовторить запись? При отмене игра останется открытой на паузе.',parent=self.window):self.close()
            elif kind=='fatal':self.notice='Ошибка ядра: '+data['message']
        if self.runtime.finished.done() and not self.closed:
            try:self.runtime.finished.result()
            except BaseException as error:self.diagnostics.record('engine_failed',error=str(error))
            self.finish_close()
    def tick(self):
        if self.closed:return
        started=time.perf_counter()
        try:
            self.pump_background()
            if self.closed:return
            now=time.monotonic()
            if now-self.last_video>=1/30:
                self.render();self.last_video=max(now-1/30,self.last_video+1/30)
            if now-self.last_panel>=.2:self.refresh_state();self.last_panel=now
            if now-self.last_metadata>=.2:self.runtime.ui_metadata=self._focus_status();self.last_metadata=now
        except Exception as error:self.error('Ошибка интерфейса',error,modal=False)
        finally:
            self.diagnostics.measure('ui_tick',(time.perf_counter()-started)*1000)
            if not self.closed:self.window.after(8,self.tick)
    def refresh_state(self):
        op=self.operation.data;auto=self.automation.info();key=op.get('job') if op.get('active') else auto.get('script') if auto.get('running') else 'battle-auto' if self.status.get('battle_auto',{}).get('active') else None
        if key and key!=self._context_key:
            self.show_battle_panel()
            if self.panel and hasattr(self.panel,'automation_windows'):
                tool=self.panel.automation_windows.tools.get('training')
                if tool and auto.get('running') and not tool.get('embedded'):tool['window'].withdraw()
        self._context_key=key
        if self.battle_panel is not None and self.battle_panel.window.winfo_viewable():self.battle_panel.update(self.last_state)
        self.update_panel()
    def ai_controlled(self):
        return bool(self.automation.running or self.pending_start or self.operation.active)

    def reclaim_on_key(self,event):
        if event.widget.winfo_toplevel()!=self.window:return False
        key=self.physical_key(event)
        if key is None:return False
        held=getattr(self,'_reclaim_keys',set())
        if key in held:return True  # OS repeat must not become game input.
        if not self.ai_controlled() or self.pending_takeover:return False
        held.add(key);self._reclaim_keys=held
        if key=='Escape':self.emergency_stop()
        else:self.take_control(focus=False)
        self.render()
        return True

    def render(self):
        video=self.model.video if self.model else None;scale=getattr(self,'display_scale',self.settings['scale']);shiny=self.safety_notice
        controlled=self.ai_controlled();overlay=bool(controlled and self.ready and not shiny and self.settings['ai_control_overlay'])
        returning=bool(self.pending_takeover);speed=(self.operation.data.get('speed_limit') if self.operation.active else 0 if self.paused else self.simulation_speed)
        capture_result=getattr(self.operation,'result',None) or {};self._capture_saved_available=bool(self.paused and not controlled and capture_result.get('kind')=='local' and (capture_result.get('search') or {}).get('candidates'))
        progress=getattr(self.operation,'data',{}).get('progress') or {};capture_mode=('candidate' if progress.get('candidate_phase') else 'search' if progress.get('search') else None) if self.operation.active and getattr(self.operation,'kind',None)=='local' else None
        key=(getattr(self.model,'generation',None),self.model.video_revision if self.model else None,scale,self.paused,repr(shiny),self.ready,overlay,speed if overlay else None,returning,capture_mode,self._capture_saved_available)
        if key==self._render_key:return
        self._render_key=key
        video_key=(getattr(self.model,'generation',None),self.model.video_revision if self.model else None,scale,overlay)
        if video and video_key!=getattr(self,'_video_render_key',None):
            self._video_render_key=video_key
            image=tk.PhotoImage(data=tint_video(video) if overlay else video,format='PPM',master=self.window);self.image=image.zoom(scale)
            self.canvas.itemconfigure(self.canvas_image,image=self.image)
        self.ai_overlay.update(overlay,scale,speed,returning=returning,limited=self.operation.active,capture_mode=capture_mode)
        state='normal' if shiny or not self.ready or self.paused and not overlay else 'hidden'
        self.canvas.itemconfigure(self.pause_title,text=('SHINY · '+shiny['species']) if shiny else 'ПАУЗА' if self.ready else 'Загрузка…',fill='#ffda73' if shiny else 'white')
        self.canvas.itemconfigure(self.pause_hint,text='Игра остановлена\nF9 — взять управление\nЗатем Space — продолжить' if shiny else 'Space — продолжить игру\nВозврат управления не запускает бота' if self.ready else 'Подготавливаем игровую сессию')
        if self._capture_saved_available and not shiny:
            self.canvas.itemconfigure(self.pause_title,text=t('capture.search_paused_title'))
            self.canvas.itemconfigure(self.pause_hint,text=t('capture.overlay_saved'))
        self.canvas.coords(self.pause_shade,12*scale,37*scale,228*scale,123*scale)
        self.canvas.coords(self.pause_title,120*scale,62*scale);self.canvas.coords(self.pause_hint,120*scale,91*scale)
        self.canvas.itemconfigure(self.pause_title,font=('Helvetica',max(12,scale*8),'bold'),state=state)
        self.canvas.itemconfigure(self.pause_hint,font=('Helvetica',max(8,scale*4)),state=state)
        self.canvas.itemconfigure(self.pause_shade,state=state)
    def clear_local_keys(self):
        self.keys.clear()
        self._held_keys = {}

    def release_manual_keys(self):
        """Release old physical assignments before editing or opening a capture."""
        self.clear_local_keys()
        self.command('clear_keys')

    def key_down(self,event):
        if self.reclaim_on_key(event):return 'break'
        if self.operation.active:return 'break'
        if event.widget.winfo_toplevel()!=self.window or event.state&COMMAND_MASK:return
        key=self.physical_key(event);self.diagnostics.record('key_down',physical_key=key,paused=self.paused,bot=self.automation.running)
        if key in self.settings['speed_bindings']:
            self.set_speed(self.settings['speed_bindings'][key]);return 'break'
        button=next((button for button,assigned in self.settings['bindings'].items() if key in assigned),None)
        if button is None:return
        held=getattr(self,'_held_keys',{})
        if key in held:return 'break'  # Ignore OS key repeat; owner holds the button.
        if self.automation.running or self.pending_start:self.take_control(focus=False)
        if self.paused:
            self.notice='Игра на паузе · Space — продолжить';self.update_panel();return 'break'
        # Keep each physical source until its own release: Up + W must remain
        # pressed when either alias is released. Release ignores later rebinding.
        held=getattr(self,'_held_keys',{})
        held[key]=button;self._held_keys=held
        if button not in self.keys:self.keys.add(button);self.command('manual',button,True)
        return 'break'

    def key_up(self,event):
        key=self.physical_key(event)
        getattr(self,'_reclaim_keys',set()).discard(key)
        held=getattr(self,'_held_keys',{})
        button=held.pop(key,None)
        if button is not None and button not in held.values() and button in self.keys:
            self.keys.discard(button);self.command('manual',button,False)

    def focus_out(self,_):self._reclaim_keys=set();self.clear_local_keys();self.command('clear_keys');self.window.after_idle(self.check_focus)
    def _focus_status(self):
        try:focused=self.window.focus_get();grab=self.window.grab_current()
        except (tk.TclError,KeyError):focused=grab=None
        return dict(ui_thread_id=threading.get_ident(),focus='вне приложения' if focused is None else 'игра' if focused.winfo_toplevel()==self.window else 'панель / справочник',focus_widget=str(focused) if focused else None,grab_widget=str(grab) if grab else None,last_input=self.diagnostics.last_input)
    def input_status(self):
        return dict(self._focus_status(),automatic_speed=self.automatic_speed_info,fps=self.measured_fps,paused=self.paused,speed=0 if self.paused else self.simulation_speed,manual_buttons=sorted(self.keys),bot=self.automation.info(),saving=bool(self.pending_writes),performance=self.status.get('performance',{}))
    def take_control(self,_=None,*,focus=True):
        self.clear_local_keys();self.pending_start=False;self.safety_notice=None;self.pending_takeover=self.runtime.take_control();self.notice='Возвращаем управление…'
        if focus:self.window.after_idle(self.focus_game)
        self.update_panel();return 'break'
    def emergency_stop(self,_=None):
        self.clear_local_keys();self.pending_start=False;self.pending_takeover=self.runtime.take_control(pause=True);self.paused=True;self.window.after_idle(self.focus_game);self.render();self.update_panel();return 'break'
    def recover_input(self):self.take_control(focus=False);self.command('recover_input');self.window.after_idle(self.focus_game)
    def pause(self,_=None,*,save=True):self.paused=True;self.clear_local_keys();self.command('pause',save);self.render();return 'break'
    def toggle_pause(self,_=None):
        if _ is not None and self.reclaim_on_key(_):return 'break'
        self.clear_local_keys();self.command('toggle_pause');self.canvas.focus_set();return 'break'
    def set_speed(self,speed):
        speed=normalize_speed(speed)
        if self.operation.active:return 'break'
        if speed==0:return self.pause()
        if self.safety_notice:self.notice='Встречен shiny · сначала F9, затем выбери скорость';self.update_panel();return 'break'
        self.settings.set('speed',speed);self.sync_audio();self.paused=False;self.release_manual_keys();self.command('set_speed',speed);return 'break'
    def _settings_changed(self,*,persist=True):
        previous=getattr(self,'_last_preferences_sent',{})
        patch={key:deepcopy(value) for key,value in self.settings.values.items() if value!=previous.get(key)}
        self._last_preferences_sent=deepcopy(self.settings.values)
        self._preferences_pending=bool(patch) or persist or self._preferences_pending
        self._preferences_version=self.runtime.set_preferences(patch,persist=persist)
    def sync_audio(self,*,clear=False):self._settings_changed(persist=False)
    def save(self,*,manual=False):return self.command('save',manual)
    def save_if_changed(self):
        if self.ready and not self.save_failed and self.settings['autosave_enabled'] and self.frame!=self.last_saved_frame:self.save()
    def create_slot(self,name,slot_id=None,*,on_saved=None):
        future=self.command('create_slot',name,slot_id)
        if on_saved:self.watch(future,on_saved)
        return future
    def load_slot(self,slot_id):self.take_control(focus=False);return self.command('load_slot',slot_id)
    def load_backup(self,directory):self.take_control(focus=False);return self.command('load_backup',Path(directory))
    def new_game(self):
        if messagebox.askyesno('Новая игра',f'Начать {edition(self.folder).name} с самого начала?\n\nТекущий прогресс будет сохранён в резервную копию. Именованные слоты останутся доступны.',parent=self.panel.window if self.panel else self.window):self.take_control(focus=False);return self.command('new_game')
    def start_bot(self,path):self.pending_start=True;future=self.command('start_bot',Path(path));self.update_panel();return future
    def start_training(self,config):
        self.pending_start=True;future=self.command('start_training',deepcopy(config));self.update_panel();return future
    def start_party_change(self,config):
        self.pending_start=True;self.party_change_error=''
        future=self.runtime.submit('start_party_change',deepcopy(config))
        def denied(error):
            # A stale click must not take control away from a newer task.
            self.pending_start=False;self.party_change_error=str(error);self.notice=str(error)
        self.watch(future,None,denied);self.update_panel();return future
    def session_state(self):return self.last_state
    def bot_snapshot(self):return dict(self.last_state,session=self.input_status())
    def inventory_snapshot(self):
        if self.ready and (self._inventory_request is None or self._inventory_request.done()):
            generation=self.generation;future=self._inventory_request=self.runtime.submit('inventory');self.watch(future,lambda value:setattr(self,'last_inventory',value) if self.generation==generation else None)
        return self.last_inventory
    def bag_snapshot(self):
        if self.ready and (self._bag_request is None or self._bag_request.done()):self._bag_request=self.runtime.submit('bag')
        return self.status.get('bag') or {'ready':False,'items':[]}
    def planning_revision(self):
        if self.ready and time.monotonic()-self._navigation_at>.2 and (self._navigation_request is None or self._navigation_request.done()):
            self._navigation_at=time.monotonic();generation=self.generation;future=self._navigation_request=self.runtime.submit('navigation_revision');self.watch(future,lambda revision:setattr(self,'_navigation_revision',revision) if self.generation==generation else None)
        return self._navigation_revision
    def location_info(self,name):return self.runtime.submit('location_info',name)
    def travel_snapshot(self):return self.runtime.submit('travel_snapshot')
    def planning_map(self,name,revision):return self.runtime.submit('map_snapshot',name,revision)
    def planning_end(self):self._navigation_revision=None;self.command('planning_end')
    def error(self,title,error,*,modal=True):
        if self.closed:return
        self.pending_takeover=self.runtime.take_control(pause=True);self.paused=True;self.clear_local_keys();self.notice=f'{title}: {error}'
        self.diagnostics.record('ui_error',title=title,error=str(error));self.update_panel()
        if modal:messagebox.showerror(title,str(error),parent=self.panel.window if self.panel else self.window)
    def callback_error(self,kind,value,tb):self.diagnostics.record('tk_callback_error',error=str(value),traceback=''.join(traceback.format_exception(kind,value,tb))[-6000:]);self.error('Ошибка интерфейса',value,modal=False)
    def close(self):
        if self.closed or self.close_requested:return
        self.close_requested=True;self._settings_changed(persist=False);self.pending_takeover=self.runtime.take_control(close=True);self.clear_local_keys();self.notice='Сохраняем игру перед закрытием';self.update_panel()
    def finish_close(self):
        if self.closed:return
        self.closed=True;self.event_pump.close()
        if self.panel and hasattr(self.panel,'details'):self.panel.details.close()
        if self.panel and hasattr(self.panel,'tasks_view'):self.panel.tasks_view.close()
        if self.panel and hasattr(self.panel,'automation_windows'):self.panel.automation_windows.close()
        self.window.destroy()

    def set_language(self,language):
        self.settings.set('language',language)
        if getattr(self,'application_folder',None):self.command('application_language',str(self.application_folder),self.settings['language'])
        set_locale(self.settings['language'])
        self._render_key=None
        self.build_menu()
        if self.panel:
            self.panel.window.configure(menu=self.window.cget('menu'))
            view=self.panel.collection_view
            view.signatures.clear()
            if view.dex:view.dex.signature=None
            self.panel.refresh()
        self.render()

    def build_menu(self):
        menu = tk.Menu(self.window)
        session = tk.Menu(menu, tearoff=False)
        session.add_command(label="Пауза / продолжить", command=self.toggle_pause, accelerator="Space")
        session.add_command(label="Сохранить сессию", command=lambda: self.save(manual=True), accelerator="⌘S")
        session.add_command(label="Слоты сохранений…", command=lambda: self.show_panel("slots"), accelerator="F8")
        session.add_command(label="Автоматизация…", command=lambda: self.show_panel("automation"),state='normal' if adapter(self.folder).supports('training') else 'disabled')
        session.add_command(label="Взять управление у бота", command=self.take_control, accelerator="F9")
        session.add_separator()
        session.add_command(label="Начать новую игру…", command=self.new_game)
        menu.add_cascade(label="Сессия", menu=session)
        window_menu = tk.Menu(menu, tearoff=False)
        window_menu.add_command(label="Панель тренера", command=self.show_panel, accelerator="F1")
        window_menu.add_command(label=t('party_edit.title'),command=self.show_party_editor)
        window_menu.add_command(label="Настройки…", command=lambda: self.show_panel("settings"))
        window_menu.add_command(label=t('search.context_panel'),command=self.show_battle_panel,state='normal' if adapter(self.folder).supports('battle') else 'disabled')
        window_menu.add_command(label=t('capture.saved_title'),command=self.show_saved_encounters,state='normal' if adapter(self.folder).supports('capture') else 'disabled')
        window_menu.add_command(label='Расположить окна вокруг игры',command=self.arrange_windows)
        menu.add_cascade(label="Окно", menu=window_menu)
        language_menu=tk.Menu(menu,tearoff=False)
        for code,name in LOCALE_NAMES.items():
            language_menu.add_command(label=name,command=lambda value=code:self.set_language(value))
        menu.add_cascade(label=t('settings.language'),menu=language_menu)
        self.window.configure(menu=menu)
        if getattr(self,'menu_hook',None):self.menu_hook(self)


    def show_panel(self, tab=None):
        from .panel import TrainerPanel
        if self.panel is None or not self.panel.window.winfo_exists():
            self.panel = TrainerPanel(self)
            self.arrange_windows()
        self.panel.show(tab)
        return "break"


    def show_party_editor(self):
        self.show_panel('overview');return self.panel.open_party_editor()

    def physical_key(self,event):
        key=event_key(event)
        if key is None and not getattr(event,'send_event',False) and getattr(event,'time',0):
            game=getattr(self,'input',None)
            if game:
                virtual=game.current_keycode(str(getattr(event,'type','2'))!='3')
                if 0<=virtual<128:key=MAC_KEYS.get(virtual)
        return key


    def shortcut_down(self, event):
        key = self.physical_key(event)
        if key == "F1":
            return self.show_panel()
        if key == "F8":
            return self.show_panel("slots")
        if key == "F9":
            return self.take_control()
        if key == "F5" or (key == "s" and event.state & COMMAND_MASK):
            return self.save(manual=True)


    def focus_in(self, event):
        if getattr(self,'diagnostics',None):self.diagnostics.record('focus_in',frame=self.frame)
        if (self.settings['auto_focus_game'] and not self.closed and event.widget.winfo_toplevel() == self.window
                and self.window.focus_get() != self.canvas):
            self.canvas.focus_set()


    def focus_game(self):
        if self.closed:return
        # A user action requests this. Never focus_force or activate the macOS app.
        try:grab=self.window.grab_current()
        except (tk.TclError,KeyError):grab=None
        if grab is not None and not grab.winfo_viewable():grab.grab_release()
        elif grab is not None:
            grab.focus_set();return  # Respect a real modal choice that is still open.
        self.window.deiconify();self.window.lift();self.canvas.focus_set()


    def check_focus(self):
        try:focused=self.window.focus_get()
        except (tk.TclError,KeyError):focused=None
        if not self.closed and focused is None:
            self.save_if_changed()


    def arrange_windows(self):
        from .window_layout import display_bounds,layout,place
        if not hasattr(self,'desktop_bounds'):self.desktop_bounds=display_bounds(self.window)
        plan=layout(self.desktop_bounds,self.settings['scale']);self.display_scale=plan.scale
        self.canvas.configure(width=240*plan.scale,height=160*plan.scale);place(self.window,plan.game)
        if self.panel is not None and self.panel.window.winfo_exists():place(self.panel.window,plan.trainer)
        if self.battle_panel is not None and self.battle_panel.window.winfo_exists():place(self.battle_panel.window,plan.battle)
        self.render()

    def set_scale(self, scale: int, *, persist=True):
        if persist:self.settings.set('scale',scale)
        self.arrange_windows()

    def show_saved_encounters(self):
        if not self.ready:return
        self.show_battle_panel()
        if self.panel is None:self.show_panel()
        return self.battle_panel.open_saved_encounters(self.panel)
    def show_battle_panel(self):
        if not adapter(self.folder).supports('battle'):return
        from .battle_panel import BattlePanel
        try:previous=self.window.focus_get()
        except (tk.TclError,KeyError):previous=None
        if self.battle_panel is None or not self.battle_panel.window.winfo_exists():
            self.battle_panel=BattlePanel(self);self.arrange_windows()
        self.battle_panel.update(self.last_state or {})
        self.battle_panel.window.deiconify()
        # Opening an observer must not redirect the keyboard away from the game.
        if previous is not None:self.window.after_idle(previous.focus_set)


    def update_panel(self):
        if self.panel is not None and self.panel.window.winfo_exists():
            if self.panel.window.winfo_viewable():self.panel.refresh()
            if hasattr(self.panel,'automation_windows'):self.panel.automation_windows.refresh()


def run(folder:Path,*,paused=False):
    root=tk.Tk();monitor=Monitor(root,folder.resolve(),paused=paused)
    signal.signal(signal.SIGTERM,lambda *_:root.after_idle(monitor.close));signal.signal(signal.SIGINT,lambda *_:root.after_idle(monitor.close));root.mainloop()
