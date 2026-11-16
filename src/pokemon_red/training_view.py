from .i18n import t
from .i18n import search_matches
from .entity_names import entity_aliases
from .table import Table
"""Training setup, measured progress and asynchronous route-specific roster preview."""
import json
import time
from . import localized_tk as tk
from tkinter import ttk

from .scrolling import Scrollbar
from .zones import zone_spec
from .planning_service import PlanningService
from .run_context import RunConfig,planning_key,build_context,comparison_key
from .presentation import present,RunState
from .grind import validate_start
from .catalog import catalog,species
from .sprites import sprite
from .tooltips import Tooltip
from .ui import BG,CARD,TEXT,MUTED,GREEN,BLUE,AMBER,Button,Stepper,Meter,Select,Collapse,Segments,label,card

def duration(seconds):
    if seconds is None:return '—'
    minutes=max(1,round(seconds/60))
    return f'{minutes//60} ч {minutes%60} мин' if minutes>=60 else f'{minutes} мин'

def starter_training(inventory,uid,state):
    owned=inventory.get('party',[])+inventory.get('boxes',[])
    target=next((m for m in owned if m.get('uid')==uid),None)
    name=(state.get('map') or {}).get('name','')
    return bool(target and len(owned)==1 and target.get('species_id') in (1,4,7) and target.get('level',100)<=10 and name in ('Route1','PalletTown','ViridianCity','ViridianCity_PokemonCenter_1F'))

class TrainingSetup:
    def __init__(self,panel,parent,dock=None,*,embedded=False):
        self.panel=panel;self.monitor=panel.monitor;self.path=self.monitor.folder/'Data/training.json'
        try:self.config=json.loads(self.path.read_text())
        except (OSError,ValueError):self.config={}
        self.embedded=embedded;self.policy_chosen=False;self.recommended_uid=None;self.saved_policy='training_policy' in self.config
        self.policy=tk.StringVar(value=self.config.get('training_policy','eta'))
        self.approach=tk.StringVar(value=self.config.get('training_approach','auto') if self.config.get('training_approach')!='legacy' else 'auto');self.egg=tk.BooleanVar(value=self.config.get('equip_lucky_egg',True))
        self.trainee=tk.StringVar(value=self.config.get('trainee',''));self.strategy=tk.StringVar(value='adaptive');self.route=tk.StringVar(value='Auto')
        self.target=tk.IntVar(value=self.config.get('target',15));self.threshold=tk.IntVar(value=self.config.get('heal_percent',40))
        self.max_auto_speed=tk.IntVar(value=self.config.get('max_auto_speed',12));self.auto_speed=tk.BooleanVar(value=self.config.get('auto_speed',False));self.allow_two_hits=tk.BooleanVar(value=self.config.get('allow_two_hits',True))
        self.inventory={};self.inventory_at=0;self.signature=None;self.display_key=None;self.plan=None;self.error='';self.chooser=None;self.start_xp=None;self.planner=PlanningService(map_provider=self.read_planning_map);self.closed=False
        self.world=None;self.world_revision=None;self.collecting=False;self.world_after=None;self.change_after=None
        self.header=tk.Frame(parent,bg=BG);self.header.pack(fill='x',pady=(0,8))
        label(self.header,t('design.training'),21,bold=True,pack=False).pack(side='left')
        self.phase_label=label(self.header,t('design.preparation'),11,MUTED,pack=False);self.phase_label.pack(side='right')
        self.measured=label(parent,'',12,GREEN,wraplength=505);self.measured.pack_configure(pady=(0,8));self.measured_hint=Tooltip(self.measured)
        self.prediction=label(parent,'Выбери Pokémon и целевой уровень',12,BLUE,wraplength=505);self.prediction.pack_configure(pady=(0,6))
        self.cycle_result=label(parent,'',11,MUTED,wraplength=505);self.cycle_result.pack_configure(pady=(0,8))
        self.cycle_result.pack_forget()
        self.progress_detail=label(parent,'',11,MUTED);self.progress_detail.pack_configure(pady=(0,5));self.progress=Meter(parent,color=BLUE);self.progress.pack(fill='x',pady=(0,10))
        self.setup=tk.Frame(parent,bg=BG);self.setup.pack(fill='x',pady=(0,10));form=self.setup
        self.choose_button=Button(form,t('design.choose_pokemon'),self.choose_target,anchor='w',height=40);self.choose_button.pack(fill='x',pady=(0,8))
        options=card(form);options.pack(fill='x');options.columnconfigure(0,weight=1);options.columnconfigure(1,weight=2)
        self.route_labels={'Auto':'Авто · по силе команды',**{r:z['label'] for r,z in zone_spec(self.monitor.folder)['zones'].items()}}
        label(options,'До уровня',10,MUTED,pack=False).grid(row=0,column=0,sticky='w')
        self.target_widget=Stepper(options,self.target,2,100);self.target_widget.grid(row=1,column=0,sticky='ew',pady=(5,0),padx=(0,10))
        label(options,'Маршрут',10,MUTED,pack=False).grid(row=0,column=1,sticky='w')
        self.route_text=tk.StringVar(value=self.route_labels['Auto'])
        self.route_control=Select(options,self.route_text,values=list(self.route_labels.values()),command=lambda text:self.route.set(next(k for k,v in self.route_labels.items() if v==text)));self.route_control.grid(row=1,column=1,sticky='ew',pady=(5,0))
        label(form,t('training.approach'),10,MUTED).pack_configure(pady=(8,3))
        self.approach_labels={k:t('training.approach_'+k) for k in ('auto','careful','mentor','fast','local')}
        self.approach_text=tk.StringVar(value=self.approach_labels[self.approach.get()])
        self.approach_control=Select(form,self.approach_text,values=list(self.approach_labels.values()),command=lambda value:self.approach.set(next(k for k,v in self.approach_labels.items() if v==value)));self.approach_control.pack(fill='x')
        self.policy_hint=label(form,'',10,MUTED,wraplength=505)
        from .ui import Toggle
        advanced=Collapse(form,t('design.advanced'));advanced.pack(fill='x',pady=(8,0))
        pacing=tk.Frame(advanced.body,bg=BG);pacing.pack(fill='x')
        self.two_hit_toggle=Toggle(pacing,'Разрешать ученику побеждать за два удара',self.allow_two_hits);self.two_hit_toggle.pack(fill='x',pady=(0,4))
        Tooltip(self.two_hit_toggle,'Включено: ученик побеждает за 1–2 попадания. Выключено: только за одно. Нужно покрывать не менее 80% встреч. Когда подходящие PP заканчиваются, возвращаемся лечиться. Промахи учитываются отдельно в прогнозе времени.')
        self.two_hit_toggle.pack_forget()
        self.egg_toggle=Toggle(form,t('training.use_egg'),self.egg);self.egg_toggle.pack(fill='x')
        Tooltip(self.egg_toggle,t('training.egg_hint'))
        self.speed_toggle=Toggle(form,'Управлять скоростью',self.auto_speed)
        self.speed_toggle.pack(fill='x')
        Tooltip(self.speed_toggle,'Бег 4×, ходьба 8×, меню 4×, анимации до 12× — в пределах выбранного лимита. Цифры возвращают ручную скорость.')
        cap=tk.Frame(pacing,bg=BG);cap.pack(fill='x',pady=(6,0));label(cap,'Максимальная скорость ИИ',11,pack=False).pack(side='left');self.speed_cap_widget=Stepper(cap,self.max_auto_speed,1,16);self.speed_cap_widget.pack(side='right')
        from .move_plan_ui import MoveSetup
        self.move_ui=MoveSetup(self,form)
        if embedded:self.explanation=tk.Frame(parent,bg=CARD)
        else:
            self.explanation=tk.Toplevel(parent.winfo_toplevel());self.explanation.title(t('training.route_details'));self.explanation.geometry('620x600');self.explanation.configure(bg=BG);self.explanation.withdraw();self.explanation.protocol('WM_DELETE_WINDOW',self.explanation.withdraw)
        explanation_body=tk.Frame(self.explanation,bg=BG,padx=16,pady=14);explanation_body.pack(fill='both',expand=True)
        label(explanation_body,'Маршрут и противники',18,bold=True);Button(explanation_body,'Встречи выбранного маршрута ↗',self.show_encounters,variant='ghost').pack(fill='x',pady=8)
        self.alternative_text=label(explanation_body,'',11,MUTED,wraplength=570)
        self.matchups=tk.Text(explanation_body,height=12,wrap='word',bg=CARD,fg=TEXT,bd=0,padx=10,pady=10,font=('Helvetica',11),state='disabled');self.matchups.pack(fill='both',expand=True,pady=10)
        self.explanation_button=Button(parent,t('design.prediction_details'),self.show_explanation,variant='ghost',anchor='w');self.explanation_button.pack(fill='x',pady=(0,8))
        self.team_head=label(parent,'Отряд',12,bold=True);self.team_head.pack_configure(pady=(0,8))
        self.team_frame=tk.Frame(parent,bg=BG);self.team_frame.pack(fill='x');self.team_cards=[];self.team_cells=[];self.columns=0;self.team_frame.bind('<Configure>',lambda _:self.layout_team())
        self.estimate=label(parent,'',11,BLUE,wraplength=505);self.estimate.pack_configure(pady=(4,5));self.warning=label(parent,'',10,AMBER,wraplength=505);self.warning.pack_configure(pady=(0,8))
        self.header.bind('<Configure>',lambda e:[w.configure(wraplength=max(160,e.width-8)) for w in (self.measured,self.warning,self.estimate,self.progress_detail,self.prediction,self.cycle_result,self.alternative_text)])
        self.actions=tk.Frame(dock or parent,bg=BG,padx=4,pady=8)
        if dock is not None:
            existing=list(dock.pack_slaves())
            for widget in existing:widget.pack_forget()
            self.actions.pack(side='bottom',fill='x')
            for widget in existing:widget.pack(side='right' if isinstance(widget,Scrollbar) else 'left',fill='y' if isinstance(widget,Scrollbar) else 'both',expand=not isinstance(widget,Scrollbar))
        else:self.actions.pack(fill='x')
        self.start=Button(self.actions,t('design.start_training'),self.run,variant='primary',height=42);self.start.pack(fill='x')
        self.status=label(self.actions,'',11,MUTED,wraplength=505);self.status.pack_configure(pady=(6,0));self.stage_label=self.status
        self.actions.bind('<Configure>',lambda e:self.status.configure(wraplength=max(240,e.width-16)))
        self.traces=[(v,v.trace_add('write',lambda *_:self.changed())) for v in (self.trainee,self.strategy,self.route,self.policy,self.approach,self.egg,self.target,self.threshold,self.auto_speed,self.max_auto_speed,self.allow_two_hits)]
        parent.bind('<Destroy>',lambda e:self.close() if e.widget is parent else None,add='+')
        self._form_layouts=[(w,w.pack_info()) for w in form.winfo_children() if w.winfo_manager()=='pack']
        self.show_plan_details(False);self.show_team_preview(False)
        self.poll_after=self.header.after(40,self.poll_plan)
    def choose_policy(self,value):self.policy_chosen=True;self.changed()
    def show_explanation(self):
        if not self.embedded:self.explanation.deiconify();self.explanation.lift();return
        if self.explanation.winfo_manager():self.explanation.pack_forget()
        else:self.explanation.pack(fill='both',expand=True,before=self.explanation_button,pady=(0,8))
    def close(self):
        if self.closed:return
        self.closed=True
        if not self.embedded and self.explanation.winfo_exists():self.explanation.destroy()
        if self.chooser and self.chooser.winfo_exists():self.chooser.destroy()
        self.planner.close()
        try:self.header.after_cancel(self.poll_after)
        except tk.TclError:pass
        if self.world_after:
            try:self.header.after_cancel(self.world_after)
            except tk.TclError:pass
        if self.change_after:
            try:self.header.after_cancel(self.change_after)
            except tk.TclError:pass
            self.change_after=None

    def visible(self):return not self.closed and bool(self.header.winfo_viewable())
    def suspend(self):
        self.planner.suspend();self.signature=None;self.display_key=None;self.monitor.planning_end()
    def collect_world(self):
        if not self.visible() or not hasattr(self.monitor,'planning_revision'):return
        generation=getattr(self.monitor,'generation',None)
        if generation!=getattr(self,'session_generation',None):
            self.session_generation=generation;self.suspend();self.world=None;self.world_revision=None;self.preview_origin=None
        revision=self.monitor.planning_revision()
        if revision is None:return
        if self.world is None or revision!=self.world_revision:
            self.world=dict(grids={},canonical_navigation=True,map_revision=revision)
            self.world_revision=revision;self.preview_origin=None
    def read_planning_map(self,name,*,revision=None):
        from .planning_state import PlanningSnapshotExpired
        if not self.visible():raise PlanningSnapshotExpired('Окно прокачки закрыто')
        expected=self.world_revision if revision is None else revision
        future=self.monitor.planning_map(name,expected)
        def invalid(error):
            if isinstance(error,PlanningSnapshotExpired) and self.visible() and expected==self.world_revision:
                self.planner.suspend();self.world=None;self.signature=None;self.display_key=None
        self.monitor.watch(future,None,invalid)
        return future

    def planning_input(self,inventory=None,state=None,*,fresh_origin=False):
        inventory=inventory if inventory is not None else self.inventory
        state=state if state is not None else self.monitor.last_state
        if not self.world or not state or not state.get('position'):return inventory
        if fresh_origin or getattr(self,'preview_origin',None) is None:
            self.preview_origin=dict(map=dict(state['map']),position=dict(state['position']))
        # Preview is a proposal from the point where the tool was opened. A
        # walking player must not trigger graph search for every tile. Start
        # revalidates the exact current origin before a prepared plan is used.
        return dict(inventory,_planning=dict(self.world,state=self.preview_origin,revision=self.monitor.history.completed_revision,speed=self.monitor.settings['speed']))
    def poll_plan(self):
        if self.closed:return
        if self.visible() and time.monotonic()-getattr(self,'last_preview_refresh',0)>.2:
            self.last_preview_refresh=time.monotonic();self.refresh(self.monitor.last_state)
        result=self.planner.poll() if self.visible() else None
        if result is not None and not self.monitor.automation.info()['running'] and self.planner.desired==self.signature and self.display_key!=self.signature:
            self.display_key=self.signature;self.plan,self.error=result;self.error=self.error or '';self.render_plan();self.refresh(self.monitor.last_state)
        self.poll_after=self.header.after(5 if self.visible() and self.planner.active else 200,self.poll_plan)
    def changed(self):
        if not self.closed and not getattr(self,'syncing',False):
            # The entry updates immediately. Recompute once after a burst of
            # clicks/typing, and revoke the old start button synchronously.
            self.preview_origin=None;self.signature=None
            self.start.configure(state='disabled')
            if self.change_after:self.header.after_cancel(self.change_after)
            self.change_after=self.header.after(180,self.apply_changes)
    def apply_changes(self):
        self.change_after=None
        if not self.closed:self.refresh(self.monitor.last_state)
    def current_config(self):
        return dict(auto_team=True,**RunConfig.parse(dict(allow_two_hits=self.allow_two_hits.get(),auto_speed=self.auto_speed.get(),max_auto_speed=self.max_auto_speed.get(),training_policy=self.policy.get(),training_approach=self.approach.get(),equip_lucky_egg=self.egg.get(),strategy=self.strategy.get(),route=self.route.get(),trainee=self.trainee.get(),target=self.target.get(),heal_percent=self.threshold.get(),target_ohko_threshold=self.config.get('target_ohko_threshold',.9),final_moves=self.move_ui.selected,evolution_mode=self.move_ui.mode,approved_plan_id=self.move_ui.approved)).as_dict())
    def inspect(self,uid):
        mon=next((m for m in self.inventory.get('party',[])+self.inventory.get('boxes',[]) if m['uid']==uid),None)
        if mon:
            if self.chooser is not None and self.chooser.winfo_exists():self.chooser.withdraw()
            self.panel.inspect_uid(uid,mon)
    def refresh(self,state):
        if self.closed or not self.visible():return
        info=self.monitor.automation.info();running=info['running'] or getattr(self.monitor,'pending_start',False)
        if self.change_after is not None and not running:return
        try:int(self.target.get())
        except (ValueError,tk.TclError):
            self.signature=None;self.start.configure(state='disabled');self.status.configure(text=t('training.valid_level'));return
        run=getattr(self.monitor.history,'run',None)
        if running and run and run.get('id')!=getattr(self,'active_run_id',None) and run.get('context'):
            self.active_run_id=run['id'];cfg=run['context']['config'];self.config.update(cfg);self.syncing=True;self.policy.set(cfg.get('training_policy','eta'));self.approach.set(cfg.get('training_approach','auto'));self.egg.set(cfg.get('equip_lucky_egg',True))
            self.move_ui.adopt(cfg)
            try:
                for key,var in [('trainee',self.trainee),('route',self.route),('target',self.target),('heal_percent',self.threshold),('auto_speed',self.auto_speed),('max_auto_speed',self.max_auto_speed),('allow_two_hits',self.allow_two_hits)]:var.set((run.get('selection') or {}).get('mode',cfg[key]) if key=='route' else cfg.get(key,key=='allow_two_hits') if key in ('auto_speed','allow_two_hits') else cfg.get(key,12) if key=='max_auto_speed' else cfg[key])
            finally:self.syncing=False
            self.start_xp=next((m['experience'] for m in self.inventory.get('party',[])+self.inventory.get('boxes',[]) if m['uid']==cfg['trainee']),None)
            if run.get('preview'):self.plan=run['preview'];self.render_plan()
        if time.monotonic()-self.inventory_at>3:
            self.inventory=getattr(self.monitor,'last_inventory',None) or self.monitor.inventory_snapshot();self.inventory_at=time.monotonic()
        if not running:self.collect_world()
        owned=self.inventory.get('party',[])+self.inventory.get('boxes',[])
        target=next((m for m in owned if m['uid']==self.trainee.get()),None)
        if state:
            target=next((m for m in state.get('party',[]) if m['uid']==self.trainee.get()),target)
        self.choose_button.configure(text=f"{target['nickname']} · Lv {target['level']}  ⌄" if target else t('design.choose_pokemon'))
        if target and not running and self.recommended_uid!=target['uid'] and any(m.get('uid')==target['uid'] for m in owned):
            self.recommended_uid=target['uid']
            if self.target.get()<=target['level']:self.target.set(min(100,target['level']+1))
        self.policy_hint.configure(text=t('training.approach_hint_'+self.approach.get()))
        self.approach_control.configure(state='disabled' if running else 'normal');self.egg_toggle.configure(state='disabled' if running else 'normal')
        self.approach_text.set(self.approach_labels[self.approach.get()])
        self.move_ui.update(target,running)
        has_details=bool(self.plan or self.error and self.planner.availability.get(self.signature))
        self.explanation_button.configure(state='normal' if has_details else 'disabled')
        self.show_plan_details(has_details)
        for widget,pady in ((self.measured,(0,8)),(self.prediction,(0,6)),(self.progress_detail,(0,5)),(self.progress,(0,10))):
            if target:
                if not widget.winfo_manager():widget.pack(fill='x',before=self.setup,pady=pady)
            else:widget.pack_forget()
        if target:
            self.move_ui.frame.pack(fill='x',pady=(8,0));self.warning.pack(fill='x',pady=(0,8))
        else:self.move_ui.frame.pack_forget();self.warning.pack_forget()
        self.two_hit_toggle.configure(state='disabled' if running or self.policy.get()=='eta' else 'normal')
        self.speed_toggle.configure(state='disabled' if running else 'normal')
        self.speed_cap_widget.configure(state='disabled' if running else 'normal')
        self.route_control.configure(state='disabled' if running or self.approach.get()=='local' else 'normal')
        route_label=self.route_labels.get(self.route.get(),self.route.get())
        if self.route_text.get()!=route_label:self.route_text.set(route_label)
        reason='';pending=False
        try:
            config=self.current_config();snapshot=self.planning_input(state=state);key=planning_key(snapshot,config)
            completion=getattr(self.monitor.history,'completed_write',None)
            ready=('_planning' in snapshot or config['route']!='Auto') and (completion is None or completion.done())
            if target and not running and ready and key!=self.signature:
                self.signature=key;self.error='';self.planner.request(key,snapshot,config,self.monitor.folder)
            pending=bool(target) and not running and (not ready or self.display_key!=self.signature)
            reason=('Проверяем доступность карты…' if not ready else 'Подбираем команду…') if pending else self.error or self.move_ui.review_reason(self.plan)
            if not running and not reason:
                try:validate_start(state or {},self.monitor.folder)
                except ValueError as error:reason=str(error)
        except (tk.TclError,ValueError) as error:
            self.signature=None;self.plan=None;reason=str(error) if isinstance(error,ValueError) else 'Введи корректный уровень и % HP'
        self.start.configure(state='disabled' if running or reason or not self.plan else 'normal',text='Подбираем команду…' if pending else t('design.start_training'))
        self.choose_button.configure(state='disabled' if running else 'normal')
        self.target_widget.configure(state='disabled' if running else 'normal')
        view=present(info,self.monitor.paused,self.monitor.settings['speed'],reason)
        pacing=getattr(self.monitor,'automatic_speed_info',{})
        message=view.message
        if running and pacing.get('enabled') and not self.monitor.paused:message+=f"\n{self.monitor.simulation_speed}× · {pacing['phase']}"
        elif running and self.auto_speed.get() and not pacing.get('enabled'):message+='\nРучная скорость до следующего запуска'
        self.status.configure(text=message,fg=AMBER if view.state in (RunState.ATTENTION,RunState.ERROR) else MUTED)
        metric_key=(self.monitor.history.stats_revision,getattr(self.monitor.history,'local_revision',0),self.route.get(),self.trainee.get(),self.display_key)
        if getattr(self,'measured_revision',None)!=metric_key:
            self.measured_revision=metric_key;self.refresh_measurement()
            self.refresh_cycle_result()
        self.refresh_prediction(state)
        if target:
            try:
                curve=catalog(self.monitor.folder)['growth'][species(target['species_id'],self.monitor.folder)['growth']];goal=curve[int(self.target.get())];baseline=self.start_xp if self.start_xp is not None else target['experience']
                self.progress.set(1 if target['level']>=int(self.target.get()) else (target['experience']-baseline)/max(1,goal-baseline));self.progress_detail.configure(text=f"{target['nickname']} · Lv {target['level']} → {self.target.get()} · осталось {max(0,goal-target['experience']):,} XP".replace(',',' '))
            except (ValueError,IndexError,tk.TclError):pass
        else:self.progress_detail.configure(text='');self.progress.set(0)
        self.phase_label.configure(text=t('design.attention') if view.state in (RunState.ATTENTION,RunState.ERROR) else t('design.running') if running else t('design.preparation'),fg=AMBER if view.state in (RunState.ATTENTION,RunState.ERROR) else MUTED)
        for widget,options in self._form_layouts:
            if running:
                if widget.winfo_manager():widget.pack_forget()
            elif not widget.winfo_manager() and (widget is not self.move_ui.frame or target):widget.pack(**options)
        if running:
            self.start.pack_forget();self.team_frame.pack_forget();self.team_head.pack_forget()
        else:
            if not self.start.winfo_manager():self.start.pack(fill='x',before=self.status)
            self.show_team_preview(bool(self.plan))
    def show_plan_details(self,visible):
        if visible:
            if not self.explanation_button.winfo_manager():self.explanation_button.pack(fill='x',before=self.estimate,pady=(0,8))
        else:self.explanation_button.pack_forget()
    def show_team_preview(self,visible):
        # Pack the anchor first: the empty preview is deliberately unmanaged.
        if visible:
            if not self.team_frame.winfo_manager():self.team_frame.pack(fill='x',before=self.estimate)
            if not self.team_head.winfo_manager():self.team_head.pack(fill='x',before=self.team_frame,pady=(0,8))
        else:self.team_head.pack_forget();self.team_frame.pack_forget()
    def refresh_measurement(self):
        route=self.plan['route'] if self.plan else self.route.get()
        records=[r for r in self.monitor.history.comparisons() if r['route']==route and r['target_uid']==self.trainee.get() and r['strategy']=='adaptive']
        if not records:self.measured.configure(text='XP/мин: пока нет полных циклов');return
        exact=[]
        if self.plan:
            context=build_context(self.monitor.folder,self.current_config(),self.plan)
            for r in records:
                expected=comparison_key(self.plan['team_fingerprint'],context,r['clinic'],r['area'])
                if r['context_complete'] and expected==r['team_fingerprint']:exact.append(r)
        r=max(exact or records,key=lambda r:(r['last_sample_at'],r['latest_id']))
        from datetime import datetime
        date=datetime.fromisoformat(r['last_sample_at']).astimezone().strftime('%d.%m %H:%M')
        context_label='текущий состав и условия' if exact else 'другие условия' if r['context_complete'] else 'старые данные · неполный контекст'
        self.measured.configure(text=t('design.real_xp',xp=f"{r['xp_active_minute']:.1f}"));self.measured_hint.text=f"{r['cycles']} полных циклов · {date} · {context_label} · {r['speed_note']}"

    def refresh_prediction(self,state):
        forecast=(getattr(self.monitor.history,'cycle',None) or {}).get('forecast') if self.monitor.automation.info()['running'] else None
        forecast=forecast or (self.plan or {}).get('forecast')
        if not forecast:
            self.prediction.configure(text='Расчёт времени появится после проверки карт' if self.trainee.get() else 'Выбери Pokémon и целевой уровень');return
        speed=max(.000001,self.monitor.settings['speed']);running=self.monitor.automation.info()['running']
        seconds=forecast.get('remaining_game_seconds') if running else forecast.get('eta_game_seconds')
        if running and state and (getattr(self.monitor.history,'cycle',None) or {}).get('forecast'):
            from .optimizer import remaining_xp
            target=next((m for m in state.get('party',[]) if m['uid']==self.trainee.get()),None)
            if target:seconds=remaining_xp(target,self.target.get(),self.monitor.folder)*60/max(.01,forecast['xp_game_minute'])
        text=f"≈ {duration(seconds)} игры до цели · ≈ {duration(seconds/speed) if seconds is not None else '—'} при {speed}×\n{self.route_labels.get(forecast['route'],forecast['route'])} · прогноз {forecast['xp_game_minute']:.1f} XP/мин игры"
        if self.auto_speed.get():
            text=f"≈ {duration(seconds)} игры до цели · автоскорость до {self.max_auto_speed.get()}×\n{self.route_labels.get(forecast['route'],forecast['route'])} · прогноз {forecast['xp_game_minute']:.1f} XP/мин игры"
        if not running:text+=' · с переходом и подготовкой' 
        if seconds==0:text='Целевой уровень достигнут'
        self.prediction.configure(text=text)

    def refresh_cycle_result(self):
        reader=getattr(self.monitor.history,'forecast_results',None)
        rows=reader(self.trainee.get(),limit=8) if reader else []
        if not rows:self.cycle_result.configure(text='');self.cycle_result.pack_forget();return
        self.cycle_result.pack(fill='x',before=self.progress_detail,pady=(0,8))
        row=next((r for r in rows if r['body']['evaluation']['kind']=='complete'),rows[0]);body=row['body'];f=body['forecast'];e=body['evaluation']
        text=f"Последний цикл · {self.route_labels.get(row['route'],row['route'])}: "
        if e['kind']=='complete':
            text+=f"прогноз {f['target_xp']:.0f} XP / {duration(f['game_seconds'])} → факт {e['actual_target_xp']} XP / {duration(e['actual_game_seconds'])}\nВремя: {e['time_error_percent']:+.0f}% · XP/мин: {f['xp_game_minute']:.1f} → {e['actual_xp_game_minute']:.1f}"
        else:
            reason=e['reason'].removeprefix('partial:');reason={'target_reached':'целевой уровень достигнут','script_stopped':'ручная остановка','move_choice_required':'нужен выбор приёма','timeline_loaded':'загружено сохранение'}.get(reason,reason)
            text+=f"неполный · {e['actual_target_xp']} XP · {reason} · отдельно от полных циклов"
        self.cycle_result.configure(text=text)
    def layout_team(self):
        columns=6 if self.team_frame.winfo_width()>=760 else 3
        if self.columns==columns:return
        self.columns=columns
        for i in range(6):self.team_frame.columnconfigure(i,weight=1 if i<columns else 0,uniform='team' if i<columns else '')
        for i,frame in enumerate(self.team_cells):frame.grid(row=i//columns,column=i%columns,sticky='nsew',padx=(0 if i%columns==0 else 4,0),pady=(0,6))
    def render_plan(self):
        for child in self.team_frame.winfo_children():child.destroy()
        self.team_cards=[];self.team_cells=[];self.columns=0
        if not self.plan:
            self.team_head.pack_forget()
            self.team_head.configure(text='Отряд');self.estimate.configure(text='');self.warning.configure(text=self.error);self.alternative_text.configure(text='\n'.join(self.route_labels.get(r['route'],r['route'])+': '+r['reason'] for r in self.planner.availability.get(self.signature,[])));return
        self.show_team_preview(True)
        plan=self.plan;self.team_head.configure(text=f"Отряд · {len(plan['team'])}/6 · "+self.route_labels.get(plan['route'],plan['route']))
        self.move_ui.set_contract(plan.get('move_plan'))
        for mon in plan['team']:
            uid=mon['uid'];role='Цель · Побег' if uid==plan['trainee']==plan['runner'] else 'Цель · Cut' if uid==plan['trainee'] and uid in plan.get('utility_uids',[]) else 'Цель' if uid==plan['trainee'] else 'Побег · Cut' if uid==plan['runner'] and uid in plan.get('utility_uids',[]) else 'Побег' if uid==plan['runner'] else 'Cut' if uid in plan.get('utility_uids',[]) else 'Резерв'
            if uid==plan.get('primary_mentor'):role='Учитель'
            source='Отряд' if mon['location']=='party' else f"PC · {mon.get('box_name','BOX')}"
            frame=tk.Frame(self.team_frame,bg=CARD,padx=5,pady=5,cursor='hand2');self.team_cells.append(frame)
            label(frame,role,10,GREEN if uid==plan['trainee'] else MUTED).configure(anchor='center')
            image=sprite(frame,self.monitor.folder,mon['species_id'],shiny=mon.get('shiny',False),gray=mon['hp']<=0);portrait=tk.Label(frame,image=image,bg=CARD);portrait.image=image;portrait.pack();self.team_cards.append(portrait)
            name=label(frame,mon['nickname'],10,bold=True);name.configure(anchor='center',wraplength=145);origin=label(frame,f"Lv {mon['level']} · {source}",9,MUTED);origin.configure(anchor='center')
            frame.bind('<Configure>',lambda e,n=name,o=origin:[w.configure(wraplength=max(60,e.width-10)) for w in (n,o)])
            Tooltip(name,f"{mon['nickname']} · Lv {mon['level']} · {source}")
            for widget in [frame,*frame.winfo_children()]:widget.bind('<Button-1>',lambda _,u=uid:self.inspect(u))
        self.layout_team();self.estimate.configure(text=(f"Ученик: {plan['coverage']['target']:.0%} встреч · помощники: {plan['coverage']['supports']:.0%}\nУченик: до {plan.get('learner_max_hits',1)} попаданий · помощник: одно" if plan.get('coverage') else f"Прогноз команды: {plan['ohko_chance']:.0%} побед одной атакой"));self.warning.configure(text='\n'.join(plan['warnings']))
        selection=plan.get('selection');forecast=plan.get('forecast')
        if selection and forecast:
            evidence=forecast['evidence'];lines=[selection['reason'],f"Сопоставимых циклов: {evidence['exact_cycles']} · исторических боёв в других условиях: {evidence['transferred_battles']}",f"Подготовка и переход: ≈ {duration(forecast.get('preparation_seconds',0))}"]
            seen=set()
            for a in selection['alternatives']:
                if a['route'] in seen:continue
                seen.add(a['route'])
                if 'target_coverage' in a:lines.append(f"{self.route_labels.get(a['route'],a['route'])}: ученик {a['target_coverage']:.0%} встреч · средний Lv {a['difficulty']['mean_level']:.1f}")
                else:lines.append(f"{self.route_labels.get(a['route'],a['route'])}: ≈ {duration(a['eta_game_seconds'])} до цели · {a['xp_game_minute']:.1f} XP/мин")
            for a in selection.get('roster_exclusions',[]):lines.append(f"{self.route_labels.get(a['route'],a['route'])}: {a['reason']}")
            for a in selection['excluded']:lines.append(f"{self.route_labels.get(a['route'],a['route'])} недоступен: {a['reason']}")
            lines.append(forecast['assumptions']);self.alternative_text.configure(text='\n'.join(lines))
        groups={}
        for row in plan['matchups']:
            key=(row['species'],row['level'],row['move']);entry=groups.setdefault(key,dict(row,weight=0));entry['weight']+=row['weight']
        text='\n'.join(f"{r['species']} Lv {r['level']} · {r['weight']:g}%"+(f" · до {r['hp']} HP" if r.get('hp') else '')+f" → {r['attacker']}: {r['move']}"+(f" · до {r['certified_hits']} попаданий" if r.get('certified_hits') else f" · KO при попадании {r.get('ohko_on_hit',r['ohko']):.0%}") for r in groups.values())+'\n\n'+plan['assumptions']
        self.matchups.configure(state='normal');self.matchups.delete('1.0','end');self.matchups.insert('end',text);self.matchups.configure(state='disabled')
    def show_encounters(self):
        from .route_ui import show_zone
        route=self.plan['route'] if self.plan else self.route.get()
        if route!='Auto':show_zone(self.panel,route)

    def choose_target(self):
        if self.monitor.automation.running:return
        if self.chooser and self.chooser.winfo_exists():self.chooser.lift();return
        window=self.chooser=tk.Toplevel(self.panel.window);window.title('Выбрать Pokémon');window.configure(bg=BG);window.geometry('570x580');window.minsize(480,380)
        label(window,'Отряд и PC',19,bold=True).pack_configure(padx=16,pady=14)
        search=tk.StringVar();entry=tk.Entry(window,textvariable=search,bg=CARD,fg=TEXT,insertbackground=TEXT,bd=0,font=('Helvetica',13));entry.pack(fill='x',padx=16,ipady=8)
        tree=Table(window,columns=('level','source'),style='Sprite.Treeview',show='tree headings',selectmode='browse');tree.heading('#0',text='Pokémon');tree.heading('level',text='Уровень');tree.heading('source',text='Где');tree.column('#0',width=270);tree.column('level',width=65,anchor='center');tree.column('source',width=140)
        scroll=Scrollbar(window,command=tree.yview);tree.configure(yscrollcommand=scroll.set)
        mons=self.inventory.get('party',[])+self.inventory.get('boxes',[]);images=[]
        def fill(*_):
            previous=tree.selection();tree.delete(*tree.get_children());images.clear()
            for mon in mons:
                if not search_matches(search.get(),mon.get('nickname',''),entity_aliases('species',mon['species_id'],mon['species'])):continue
                image=sprite(tree,self.monitor.folder,mon['species_id'],shiny=mon.get('shiny',False),gray=mon['hp']<=0);images.append(image)
                tree.insert('','end',iid=mon['uid'],text=('✦ ' if mon.get('shiny') else '')+mon['nickname'],image=image,values=(mon['level'],'Отряд' if mon['location']=='party' else 'PC · '+mon['box_name']))
            children=tree.get_children()
            if children:
                uid=previous[0] if previous and previous[0] in children else children[0];tree.selection_set(uid);tree.focus(uid)
        def selected():
            ids=tree.selection()
            if ids:self.trainee.set(ids[0]);window.destroy()
        footer=tk.Frame(window,bg=BG);footer.pack(side='bottom',fill='x',padx=16,pady=(0,14))
        Button(footer,'Подробнее',lambda:self.inspect(tree.selection()[0]) if tree.selection() else None).pack(side='left')
        Button(footer,'Выбрать цель',selected,variant='primary').pack(side='right')
        scroll.pack(side='right',fill='y',padx=(0,7),pady=12);tree.pack(fill='both',expand=True,padx=(16,4),pady=12)
        search.trace_add('write',fill);tree.bind('<Double-1>',lambda _:selected());tree.bind('<Return>',lambda _:selected());fill();entry.focus_set()
    def run(self):
        try:
            state=self.monitor.bot_snapshot();validate_start(state,self.monitor.folder);inventory=self.monitor.inventory_snapshot();config=self.current_config()
            if not self.plan or self.display_key!=self.signature or planning_key(self.planning_input(inventory,state,fresh_origin=True),config)!=self.signature:
                self.inventory=inventory;self.signature=None;self.refresh(state);return
            plan=self.plan
            from .move_plan import require_approval
            if plan.get('move_plan'):require_approval(plan['move_plan'],config.get('approved_plan_id'))
            config.update(fighters=plan['fighters'],runner=plan['runner'],team_uids=plan['team_uids'])
            from .prepared_plan import prepare_packet
            packet=prepare_packet(plan,self.planning_input(inventory,state),config,self.monitor.folder)
            if packet is not None:config['_prepared_plan']=packet
            self.config=config;self.start_xp=next(m['experience'] for m in inventory['party']+inventory['boxes'] if m['uid']==config['trainee']);self.monitor.start_training(config)
        except Exception as error:self.status.configure(text=str(error))
