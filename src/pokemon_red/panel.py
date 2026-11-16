
from .paths import resource
from .editions import edition
from .text_values import SelectableLabel
from .i18n import t,LOCALE_NAMES,subscribe,unsubscribe,format_number
from .table import Table
"""Compact trainer dashboard with custom controls and offline pixel portraits."""
from datetime import datetime
import time
from . import localized_tk as tk
from .scrolling import Scrollbar
from tkinter import ttk
from .localized_tk import filedialog,messagebox,simpledialog
from .speeds import SPEEDS,parse_speed,speed_text
from .ui import BG,CARD,TEXT,MUTED,GREEN,BLUE,AMBER,Button,IconButton,Tabs,Toggle,Slider,Segments,Select,theme
from .presentation import present,RunState
from .sprites import PokemonCard

class TrainerPanel:
    def __init__(self,monitor):
        from .tooltips import Tooltip
        self.workspace=True;self.monitor=monitor;self.active_section='collection';self.window=tk.Toplevel(monitor.window);self.window.title(edition(monitor.folder).name+' · Тренер');self.window.configure(bg=BG,menu=monitor.window.cget('menu'));self.window.minsize(480,540)
        self.window.protocol('WM_DELETE_WINDOW',self.window.withdraw);self.window.bind('<FocusOut>',monitor.focus_out);self.window.bind('<Escape>',monitor.emergency_stop);theme(self.window)
        header=tk.Frame(self.window,bg=BG,padx=16,pady=5);header.pack(fill='x');self.header=header
        from .session_ui import ExitButton,confirm_return_to_menu
        def leave():
            callback=getattr(monitor,'return_to_menu',None)
            return callback() if callback else confirm_return_to_menu(monitor,monitor.close)
        self.exit_button=ExitButton(header,leave);self.exit_button.pack(side='right',padx=(4,0))
        self.settings_button=IconButton(header,'Настройки',lambda:self.show('settings'),width=34,height=32,variant='ghost');self.settings_button.pack(side='right',padx=(10,0));Tooltip(self.settings_button,'Настройки')
        self.money=self.label(header,'',size=12,color=MUTED,pack=False);self.money.pack(side='right')
        self.profile_button=self.button(header,t('workspace.profile'),lambda:self.show('slots'),variant='ghost',height=30,font=('Helvetica',10));self.profile_button.pack(side='left',padx=(0,8))
        self.location=self.label(header,'',size=11,color=MUTED,pack=False,height=1);self.location.pack(side='left',fill='x',expand=True);self.location_hint=Tooltip(self.location);self.header_text=edition(monitor.folder).name
        self.location.bind('<Configure>',lambda _:self.fit_header())
        tk.Frame(self.window,bg='#2a3b4d',height=1).pack(fill='x')
        self.footer=tk.Frame(self.window,bg=BG,padx=12,pady=7);self.footer.pack(side='bottom',fill='x');self.main_buttons={}
        for key,title in [('collection',t('workspace.pokemon')),('inventory',t('workspace.items')),('location',t('workspace.world')),('tasks',t('workspace.tasks'))]:
            button=self.button(self.footer,title,lambda k=key:self.show(k),height=38,font=('Helvetica',10,'bold'));button.pack(side='left',fill='x',expand=True,padx=2);self.main_buttons[key]=button
        self.content=tk.Frame(self.window,bg=BG);self.content.pack(fill='both',expand=True,padx=14);self.tabs=Tabs(self.content);self.tabs.pack(fill='both',expand=True);self.tabs.nav.pack_forget()
        self.settings_shell=tk.Frame(self.content,bg=BG);settings_head=tk.Frame(self.settings_shell,bg=BG,pady=6);settings_head.pack(fill='x');self.label(settings_head,'Настройки',size=19,bold=True,pack=False).pack(side='left');self.button(settings_head,'Сохранить сейчас',lambda:monitor.save(manual=True),height=32).pack(side='right')
        self.settings_tabs=Tabs(self.settings_shell);self.settings_tabs.pack(fill='both',expand=True);self.pages={};self.page_containers={};self.page_canvases={}
        for notebook,key,title in ((self.tabs,'overview','Отряд'),(self.tabs,'collection','Покемоны'),(self.tabs,'inventory','Инвентарь'),(self.tabs,'location','Локация'),(self.tabs,'tasks',t('workspace.tasks')),(self.settings_tabs,'settings','Игра'),(self.settings_tabs,'hotkeys','Клавиши'),(self.settings_tabs,'slots','Сохранения'),(self.settings_tabs,'journal',t('design.journal')),(self.settings_tabs,'scripts','Скрипты')):
            container=tk.Frame(notebook,bg=BG);canvas=tk.Canvas(container,bg=BG,highlightthickness=0,yscrollincrement=1);scroll=Scrollbar(container,command=canvas.yview);canvas.configure(yscrollcommand=scroll.set);scroll.pack(side='right',fill='y');canvas.pack(side='left',fill='both',expand=True)
            frame=tk.Frame(canvas,bg=BG,padx=4,pady=8);item=canvas.create_window(0,0,anchor='nw',window=frame);frame.bind('<Configure>',lambda _,c=canvas:c.configure(scrollregion=c.bbox('all')));canvas.bind('<Configure>',lambda e,c=canvas,i=item:c.itemconfigure(i,width=e.width))
            notebook.add(container,text=title);self.pages[key]=frame;self.page_containers[key]=container;self.page_canvases[str(container)]=canvas
        # Overview is a compatibility route; the party lives inside Pokémon.
        from .collection_view import CollectionView
        self.collection_view=CollectionView(self,self.pages['collection'])
        from .inventory_view import InventoryView
        self.inventory_view=InventoryView(self,self.pages['inventory'])
        from .location_view import LocationView
        self.location_view=LocationView(self,self.pages['location'])
        self.window.bind('<Control-e>',lambda _:self.open_party_editor())
        self.window.bind('<Control-l>',lambda _:self.show('location'))
        self.window.bind('<Control-t>',lambda _:self.location_view.open_travel())
        from .automation_windows import AutomationWindows
        self.automation_windows=AutomationWindows(self)
        from .hotkey_settings import HotkeySettings
        self.hotkey_settings=HotkeySettings(self,self.pages['hotkeys'])
        self.build_slots(self.pages['slots']);self.build_settings(self.pages['settings']);self.build_journal(self.pages['journal']);self.build_scripts(self.pages['scripts'])
        from .trainer_navigation import TrainerDetails
        self.details=TrainerDetails(self,self.content)
        from .workspace import TasksView
        self.tasks_view=TasksView(self,self.pages['tasks'])
        self.window._scroll_fallback=lambda:self.details.current_canvas if self.details.active else self.page_canvases.get(self.settings_tabs.select() if self.active_section=='settings' else self.tabs.select())
        self.tabs.bind('<<NotebookTabChanged>>',self.tab_changed);self.settings_tabs.bind('<<NotebookTabChanged>>',lambda _:self.refresh_slots() if self.settings_tabs.select()==str(self.page_containers['slots']) else None)
        self.window.update_idletasks();monitor.window.update_idletasks();width=580;height=min(850,self.window.winfo_screenheight()-100);x=min(monitor.window.winfo_x()+240*monitor.settings['scale']+24,self.window.winfo_screenwidth()-width-20)
        self.window.geometry(f'{width}x{height}+{max(10,x)}+{max(45,min(monitor.window.winfo_y(),100))}');self.tabs.select(self.page_containers['collection']);self.refresh()

    def fit_header(self):
        from .ui import short
        from tkinter import font
        self.location.configure(text=short(self.header_text,max(60,self.location.winfo_width()-5),font.Font(root=self.location,font=self.location.cget('font'))))
    def scroll_top(self,section):
        canvas=self.page_canvases[str(self.page_containers[section])]
        if getattr(canvas,'_smooth_controller',None):canvas._smooth_controller.cancel()
        canvas.yview_moveto(0)

    def label(self,parent,text='',*,size=12,color=TEXT,bold=False,pack=True,**kw):
        widget=SelectableLabel(parent,text=text,bg=parent.cget('bg'),fg=color,anchor='w',justify='left',font=('Helvetica',size,'bold' if bold else 'normal'),**kw)
        if pack:widget.pack(fill='x')
        return widget
    def button(self,parent,text,command,**kw):return Button(parent,text,command,**kw)
    def primary_action(self):
        self.monitor.recover_input()
    def secondary_action(self):
        if self.monitor.paused and self.monitor.automation.info()['status'] in ('attention','error'):self.monitor.recover_input()
        else:self.monitor.toggle_pause()
    def build_overview(self,parent):
        from .team_view import TeamView
        self.team_view=TeamView(self,parent);self.party_cards=self.team_view.cards
    def build_slots(self,parent):
        from .save_history_ui import SaveHistoryView
        self.save_history=SaveHistoryView(self,parent)
        self.slot_tree=self.save_history.tree
    def build_settings(self,parent):
        self.option_vars={};self.volume_save_after=None
        language=tk.Frame(parent,bg=BG,pady=8);language.pack(fill='x')
        self.language_label=self.label(language,t('settings.language'),size=17,bold=True)
        self.language_var=tk.StringVar(value=self.monitor.settings['language'])
        Segments(language,list(LOCALE_NAMES.items()),self.language_var,self.monitor.set_language).pack(fill='x',pady=(4,0))
        self.language_hint=self.label(language,t('settings.language_hint'),size=10,color=MUTED,wraplength=490);self.language_hint.pack_forget()
        subscribe(self)
        self.window.bind('<Destroy>',lambda e:unsubscribe(self) if e.widget is self.window else None,add='+')
        self.label(parent,'Звук',size=17,bold=True,pady=6);box=tk.Frame(parent,bg=CARD,padx=14,pady=10);box.pack(fill='x',pady=(0,12))
        enabled=tk.BooleanVar(value=self.monitor.settings['sound_enabled']);self.option_vars['sound_enabled']=enabled;Toggle(box,'Звук игры',enabled,lambda:self.set_option('sound_enabled',enabled.get())).pack(fill='x')
        self.volume_label=self.label(box,f"{self.monitor.settings['volume']}%",size=11,color=MUTED);self.volume_var=tk.DoubleVar(value=self.monitor.settings['volume']);self.option_vars['volume']=self.volume_var;Slider(box,self.volume_var,self.volume_changed).pack(fill='x')
        for key,title,values in (('scale','Масштаб',[(n,f'{n}×') for n in (1,2,3,4,5)]),('speed','Скорость',[(n,f'{n}×') for n in SPEEDS])):
            self.label(parent,title,size=10,color=MUTED,pady=6);variable=(tk.DoubleVar if key=='speed' else tk.IntVar)(value=self.monitor.settings[key]);self.option_vars[key]=variable
            groups=[values[:5],values[5:]] if key=='speed' else [values]
            for items in groups:
                if key!='speed':Segments(parent,items,variable,lambda v,k=key:self.set_option(k,v)).pack(fill='x',pady=(0,6))
        custom=tk.Frame(parent,bg=BG);custom.pack(fill='x',pady=(0,10))
        self.custom_speed=tk.StringVar(value=speed_text(self.monitor.settings['speed']))
        self.custom_speed_entry=tk.Entry(custom,textvariable=self.custom_speed,width=9,bg=CARD,fg=TEXT,insertbackground=TEXT,relief='flat',font=('Helvetica',13))
        self.custom_speed_entry.pack(side='left',ipady=6)
        self.custom_speed_entry.bind('<Return>',self.apply_custom_speed)
        self.button(custom,'Применить ×',self.apply_custom_speed).pack(side='left',padx=8)
        self.custom_speed_hint=self.label(parent,'Любая скорость · например 0,5 или 2,75',size=10,color=MUTED)
        self.autosave_state=self.label(parent,'',size=10,color=MUTED,pady=6)
        for key,title in (('autosave_enabled' ,'Автосохранение'),):
            var=tk.BooleanVar(value=self.monitor.settings[key]);self.option_vars[key]=var;Toggle(parent,title,var,lambda k=key,v=var:self.set_option(k,v.get())).pack(fill='x')
        self.label(parent,'Управление ИИ',size=17,bold=True,pady=12)
        overlay=tk.BooleanVar(value=self.monitor.settings['ai_control_overlay']);self.option_vars['ai_control_overlay']=overlay
        Toggle(parent,'Показывать режим управления ИИ',overlay,lambda:self.set_option('ai_control_overlay',overlay.get())).pack(fill='x')
        self.label(parent,'Лёгкий фильтр, подсказка возврата управления и текущая скорость.',size=10,color=MUTED,wraplength=490,pady=4)
        self.label(parent,'Фоновая работа',size=17,bold=True,pady=12);extra=tk.Frame(parent,bg=BG);extra.pack(fill='x')
        for key,title in (('encounters_on_start',t('design.encounters_start')),('auto_focus_game','Возвращать фокус в поле игры'),('prevent_app_nap','Продолжать работу в фоне · App Nap')):
            var=tk.BooleanVar(value=self.monitor.settings[key]);self.option_vars[key]=var;Toggle(extra,title,var,lambda k=key,v=var:self.set_option(k,v.get())).pack(fill='x')
        self.label(parent,'F9 — взять управление · Esc — остановить и поставить игру на паузу',size=10,color=MUTED,pady=10,wraplength=490)
    def locale_changed(self):
        if self.window.winfo_exists():
            self.language_label.configure(text=t('settings.language'))
            self.language_hint.configure(text=t('settings.language_hint'))
            self.language_var.set(self.monitor.settings['language'])
    def open_training(self,uid=None):return self.automation_windows.open_training(uid)
    def open_acquisition(self):return self.details.open_acquisition()
    def open_party_editor(self):return self.details.open_party_editor()
    def build_journal(self,parent):
        self.label(parent,'Журнал',size=17,bold=True,pady=6)
        self.button(parent,'История прокачки и статистика ↗',lambda:__import__('pokemon_red.reference_ui',fromlist=['show_history']).show_history(self),anchor='w').pack(fill='x',pady=(0,12))
        self.saved_status=self.label(parent,'',size=10,color=MUTED,pady=5)
        self.diagnostic_label=self.label(parent,'',color=MUTED,size=10,wraplength=490)
        self.label(parent,'Последний запуск автоматизации',size=12,bold=True,pady=8)
        self.bot_log=tk.Text(parent,height=14,wrap='word',bg=CARD,fg=TEXT,font=('Menlo',10),bd=0,padx=10,pady=10,state='disabled');self.bot_log.pack(fill='x');self.bot_log_revision=-1
    def build_scripts(self,parent):
        self.label(parent,'Свои Python-скрипты',size=17,bold=True,pady=6);self.bot_script=tk.StringVar();self.external_bots={};self.bot_picker=Select(parent,self.bot_script);self.bot_picker.pack(fill='x')
        row=tk.Frame(parent,bg=BG);row.pack(fill='x',pady=8);self.bot_choose_button=self.button(row,'Файл…',self.choose_bot);self.bot_choose_button.pack(side='left');self.button(row,'Обновить',self.refresh_bot_list,variant='ghost').pack(side='left',padx=6);self.bot_start=self.button(row,'Запустить',self.run_bot,variant='primary');self.bot_start.pack(side='right')
        self.bot_stop=self.button(parent,'Забрать управление · F9',self.monitor.take_control);self.bot_stop.pack(fill='x');self.label(parent,t('scripts.sdk_hint'),size=10,color=MUTED,pady=6,wraplength=490);self.refresh_bot_list()

    def refresh_automation(self):
        automation=self.monitor.automation;info=automation.info();running=info['running']
        for button in (self.bot_start,self.bot_choose_button,self.bot_picker):button.configure(state='disabled' if running else 'normal')
        self.bot_stop.configure(state='normal' if running else 'disabled')
        if self.bot_log_revision!=automation.log_revision:
            self.bot_log.configure(state='normal');self.bot_log.delete('1.0','end');self.bot_log.insert('1.0','\n'.join(automation.logs) or 'В этой сессии запусков ещё не было.');self.bot_log.configure(state='disabled');self.bot_log.see('end');self.bot_log_revision=automation.log_revision
    def refresh(self):
        from .locations import location_name
        m=self.monitor;s=m.last_state;running=m.automation.running;attention=m.automation.info()['status'] in ('attention','error')
        speed=0 if m.paused else getattr(m,'simulation_speed',m.settings['speed'])
        if self.option_vars['speed'].get()!=speed:self.option_vars['speed'].set(speed)
        saved=time.strftime('%H:%M:%S',time.localtime(m.last_saved_at)) if m.last_saved_at else '—';self.saved_status.configure(text=f'Последнее сохранение · {saved}');self.autosave_state.configure(text=t('design.save_error') if getattr(m,'save_failed',False) else t('design.saved_at',time=saved),fg=AMBER if getattr(m,'save_failed',False) else MUTED)
        for key,button in self.main_buttons.items():button.configure(variant='selected' if key==self.active_section else 'ghost',fg=TEXT if key==self.active_section else MUTED)
        self.settings_button.configure(variant='selected' if self.active_section=='settings' else 'ghost')
        self.refresh_automation()
        if self.active_section=='collection':self.collection_view.refresh(s)
        if self.active_section=='inventory':self.inventory_view.refresh()
        if self.active_section=='location':self.location_view.refresh(s)
        if self.active_section=='tasks':self.tasks_view.refresh()
        if hasattr(m,'input_status'):
            d=m.input_status();self.diagnostic_label.configure(text=f"{d['fps']:.0f} кадров/с · фокус: {d['focus']}"+(' · открыт диалог' if d['grab_widget'] else ''))
        if not s:return
        ready=s['ready'];p=s.get('position') or {};location=(s.get('map') or {}).get('name','')
        self.header_text=(location_name(location).replace('Pokémon Center','Центр') if ready else edition(m.folder).name)+' · '+('Пауза' if m.paused else speed_text(speed)+'×');self.fit_header();self.location_hint.text=f"Координаты персонажа: X {p.get('x','—')}, Y {p.get('y','—')}\nИгровая карта: {location}"
        self.money.configure(text='₽ '+format_number(s['money']) if ready and s['money'] is not None else '—')
        if self.active_section=='overview' and not self.details.active:self.team_view.refresh(s)
        if hasattr(self,'details'):self.details.refresh(s)

    def show(self,tab=None,*,_detail_return=False):
        if getattr(self,'workspace',False):
            from .workspace import show_section
            return show_section(self,tab,detail_return=_detail_return)
        tab=tab or 'overview'
        if tab=='automation' and hasattr(self,'automation_windows'):return self.open_training()
        if hasattr(self,'details') and not _detail_return:self.details.clear()
        self.window.deiconify()
        if tab in ('settings','hotkeys','slots','journal','scripts'):
            self.active_section='settings';self.tabs.pack_forget();self.settings_shell.pack(fill='both',expand=True);self.settings_tabs.select(self.page_containers[tab])
            if tab=='slots':self.refresh_slots()
        else:
            self.active_section=tab if tab in ('overview','collection','automation','inventory','location') else 'overview';self.settings_shell.pack_forget();self.tabs.pack(fill='both',expand=True);self.tabs.select(self.page_containers[self.active_section])
            if tab=='collection':self.collection_view.refresh(force=True)
            if tab=='inventory':self.inventory_view.refresh(force=True)
            if tab=='location':self.location_view.refresh(force=True)
        self.window.lift();self.refresh()

    def tab_changed(self,_):
        if self.settings_shell.winfo_manager() or getattr(self,'details',None) and self.details.active:return
        self.active_section=next((k for k in ('overview','collection','inventory','automation','location','tasks') if k in self.page_containers and self.tabs.select()==str(self.page_containers[k])),'overview');self.refresh()

    def inspect_party(self,index):self.team_view.inspect_slot(index)

    def inspect_uid(self,uid,mon=None):return self.open_pokemon(uid=uid,mon=mon)

    def open_pokemon(self,mon=None,*,uid=None,species_id=None):return self.details.open_pokemon(mon,uid=uid,species_id=species_id)

    def open_move(self,number):return self.details.open_move(number)

    def inspect_enemy(self,index):
        from .reference_ui import show_species
        enemies=((self.monitor.last_state or {}).get('battle') or {}).get('enemies',[])
        if index<len(enemies):
            live=enemies[index];party=self.monitor.last_state['battle'].get('enemy_party',[])
            mon=next((m for m in party if m['slot']==live['party_slot']),live)
            show_species(self,mon['species_id'],dict(mon,opponent=True))

    def volume_changed(self, value):
        volume = max(0, min(100, round(float(value))))
        self.volume_label.configure(text=f"{volume}%")
        if volume == self.monitor.settings["volume"]:
            return
        self.monitor.settings.set("volume", volume, persist=False)
        self.monitor.sync_audio()
        if self.volume_save_after is not None:
            self.window.after_cancel(self.volume_save_after)
        # Apply audio on every slider movement, batch durable disk writes.
        self.volume_save_after = self.window.after(200, self.persist_volume)

    def persist_volume(self):
        self.volume_save_after = None
        try:
            self.monitor.settings.save()
        except Exception as error:
            self.monitor.error("Не удалось сохранить громкость", error)

    def selected(self):
        selection = self.slot_tree.selection()
        return self.slot_records.get(selection[0]) if selection else None

    def refresh_slots(self, select=None):
        if hasattr(self,'save_history'):return self.save_history.refresh(select=select,force=True)
        current = select or (self.slot_tree.selection()[0] if self.slot_tree.selection() else None)
        self.slot_tree.delete(*self.slot_tree.get_children())
        records = self.monitor.slots.list()
        if self.show_backups.get():
            records += self.monitor.slots.backups()
        self.slot_records = {record["id"]: record for record in records}
        for record in sorted(records, key=lambda record: record["created_at"], reverse=True):
            date = datetime.fromisoformat(record["created_at"]).astimezone().strftime("%d.%m %H:%M")
            name = ("↩ " if record.get("is_backup") else "") + record["name"]
            self.slot_tree.insert("", "end", iid=record["id"], values=(name, date))
        if current in self.slot_records:
            self.slot_tree.selection_set(current)
            self.slot_tree.see(current)
        elif records:
            self.slot_tree.selection_set(records[0]["id"])
        self.slot_selected()

    def slot_selected(self, _=None):
        record = self.selected()
        self.load_button.configure(state="normal" if record else "disabled")
        self.overwrite_button.configure(state="normal" if record and not record.get("is_backup") else "disabled")
        self.preview.configure(image="")
        self.preview_image = None
        if not record:
            self.slot_details.configure(text="Выбери слот или создай новый.")
            return
        state = record["telemetry"]
        location, pos = (state["map"], state["position"]) if state else (None, None)
        detail = f"{state['player']} · {location['name']} · X {pos['x']} / Y {pos['y']}\nДеньги: {state['money']} · Отряд: {len(state['party'])}" if state and state["ready"] else "Точная резервная копия сессии" if state is None else "Новое прохождение · начальный экран"
        self.slot_details.configure(text=record["name"] + "\n" + detail)
        try:
            self.preview_image = tk.PhotoImage(file=str(record["directory"] / "preview.ppm"), master=self.window)
            self.preview.configure(image=self.preview_image)
        except (tk.TclError, OSError):
            pass

    def new_slot(self):
        name = simpledialog.askstring("Новый слот", "Название сохранения:", parent=self.window,
                                      initialvalue="Сохранение " + datetime.now().strftime("%d.%m %H:%M"))
        if name is not None:
            try:
                self.monitor.create_slot(name)
            except Exception as error:
                self.monitor.error("Не удалось сохранить слот", error)

    def overwrite_slot(self):
        record = self.selected()
        if record and not record.get("is_backup") and messagebox.askyesno("Перезаписать слот", f"Обновить «{record['name']}» текущим состоянием?\nПредыдущая версия останется в истории файлов.", parent=self.window):
            try:
                self.monitor.create_slot(record["name"], record["id"])
            except Exception as error:
                self.monitor.error("Не удалось обновить слот", error)

    def load_slot(self):
        record = self.selected()
        if record:
            try:
                if record.get("is_backup"):
                    self.monitor.load_backup(record["directory"])
                else:
                    self.monitor.load_slot(record["id"])
                self.show("overview")
            except Exception as error:
                self.monitor.error("Не удалось загрузить", error)

    def apply_custom_speed(self, _=None):
        try:
            speed=parse_speed(self.custom_speed.get())
            self.monitor.set_speed(speed)
            self.custom_speed.set(speed_text(speed));self.custom_speed_hint.configure(text='Пауза' if speed==0 else speed_text(speed)+'×',fg=MUTED)
            self.refresh()
        except ValueError as error:self.custom_speed_hint.configure(text=str(error),fg=AMBER)
        return 'break'

    def set_option(self, key, value):
        try:
            if key == "scale":
                self.monitor.set_scale(value)
            elif key == "speed":
                self.monitor.set_speed(value)
            else:
                self.monitor.settings.set(key, value)
                if key in ("sound_enabled", "volume",'prevent_app_nap'):
                    self.monitor.sync_audio()
            self.monitor.notice = "Настройки сохранены"
            self.refresh()
        except Exception as error:
            self.monitor.error("Ошибка настроек", error)

    def refresh_bot_list(self, select=None):
        paths = self.monitor.automation.scripts()
        self.bot_paths = {path.name: path for path in paths}
        self.bot_paths.update(self.external_bots)
        self.bot_picker.configure(values=list(self.bot_paths))
        if select is not None:
            self.bot_script.set(select)
        elif self.bot_script.get() not in self.bot_paths:
            self.bot_script.set(next(iter(self.bot_paths), ""))

    def choose_bot(self):
        selected = filedialog.askopenfilename(parent=self.window, title="Выбери Python-скрипт",
                                              initialdir=str(resource(self.monitor.folder,"Bots")),
                                              filetypes=(("Python", "*.py"),))
        if selected:
            from pathlib import Path
            path = Path(selected)
            label = str(path)
            self.external_bots[label] = path
            self.refresh_bot_list(select=label)

    def run_bot(self):
        path = self.bot_paths.get(self.bot_script.get())
        if path is None:
            messagebox.showinfo("Выбери скрипт", "Добавь .py-файл в Bots или нажми «Выбрать файл…».", parent=self.window)
            return
        if path.name in ('route1_xp.py','train_xp.py'):
            self.training.run()
            return
        self.monitor.start_bot(path)
