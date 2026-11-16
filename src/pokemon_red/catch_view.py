from math import log,ceil
from pathlib import Path
from .table import Table
"""One local-capture setup shared by Location cards and Pokémon species pages."""
from . import localized_tk as tk
from tkinter import ttk

from .ui import BG,CARD,TEXT,MUTED,BLUE,GREEN,AMBER,Button,Toggle,Stepper,Select,Segments,Collapse,label
from .scrolling import Scrollbar
from .capture_target import CaptureTarget,hunt_atlas,genders,candidates
from .hunt_service import HuntService
from .models import STAT_KEYS
from .catalog import species
from .locations import location_name
from .location_reference import METHODS
from .encounters import level_label
from .catch_preferences_ui import CatchPreferences,SearchTime
from .search_odds import wild_odds,summary,hunt_estimates
from .i18n import t,literal
from .entity_names import species_name
from .iv_preferences_ui import IVPreferences
from .tooltips import Tooltip

GENDERS={'female':'Самка ♀','male':'Самец ♂','genderless':'Бесполый','any':'Любой пол'}
STATS={'hp':'HP','attack':'Атака','defense':'Защита','speed':'Скорость','special_attack':'Спец. атака','special_defense':'Спец. защита'}


def open_autocatch(panel,species_id,*,route=None,method=None,preset=None):
    from .capture_target import catchable_species
    if species_id not in catchable_species(panel.monitor.folder):raise ValueError(t('capture.not_in_game'))
    panel.monitor.show_battle_panel()
    observer=panel.monitor.battle_panel
    view=observer.open_catch(panel,species_id,route=route,method=method,preset=preset)
    panel.catch_setup=view
    return view

class CatchSetup:
    def __init__(self,panel,number,*,route=None,method=None,preset=None,parent=None):
        preset=preset or {}
        self.panel=panel;self.m=panel.monitor;self.root=self.m.folder;self.number=number;self.fixed_route=route;self.fixed_method=method;self.closed=False;self.service=HuntService();self.request_id=0;self.loading=False;self.rows={};self.result=None;self.autoselect=route is None;self.selected=None;self.after=None;self.debounce=None;self.filters_valid=True;self.service_request=None;self.preview_generation=None;self.own_operation=False;self.suspended=False;self.choose_after_stop=False;self.show_filters=True;self.results_shown=False;self.form_dirty=False;self.ready_form=False
        self.window=parent.winfo_toplevel() if parent is not None else panel.window
        self.frame=tk.Frame(parent if parent is not None else panel.content,bg=BG);self.frame.pack(fill='both',expand=True)
        self.frame.bind('<Destroy>',lambda e:self.close() if e.widget is self.frame else None,add='+')
        footer=tk.Frame(self.frame,bg=BG,padx=8,pady=8);footer.pack(side='bottom',fill='x')
        self.detail=label(footer,'',10,MUTED,wraplength=480);self.activity=label(footer,'',11,BLUE,wraplength=480)
        buttons=tk.Frame(footer,bg=BG);buttons.pack(fill='x',pady=(7,0))
        self.start=Button(buttons,t('capture.start'),self.run,variant='primary');self.start.pack(fill='x')
        self.finish_button=Button(buttons,t('capture.finish_search'),lambda:self.m.operation.command('finish_search'),variant='ghost');self.finish_button.pack(fill='x',pady=(3,0))
        self.running_controls=tk.Frame(buttons,bg=BG)
        self.cancel=Button(self.running_controls,t('capture.stop_search'),lambda:self.m.take_control(focus=False),variant='primary');self.cancel.pack(side='left',fill='x',expand=True)
        self.pause=Button(self.running_controls,t('capture.stop_choose'),self.stop_and_choose);self.pause.pack(side='right',padx=(6,0))
        canvas=tk.Canvas(self.frame,bg=BG,highlightthickness=0,yscrollincrement=1);self.canvas=canvas;scroll=Scrollbar(self.frame,command=canvas.yview);canvas.configure(yscrollcommand=scroll.set);scroll.pack(side='right',fill='y');canvas.pack(fill='both',expand=True)
        body=tk.Frame(canvas,bg=BG,padx=8,pady=8);item=canvas.create_window(0,0,anchor='nw',window=body);body.bind('<Configure>',lambda _:canvas.configure(scrollregion=canvas.bbox('all')));canvas.bind('<Configure>',lambda e:canvas.itemconfigure(item,width=e.width))
        self.title=label(body,t('capture.setup_for',name=species_name(number)),17,bold=True,wraplength=300)
        self.best_frame=tk.Frame(body,bg=BG)
        self.saved_link=Button(footer,t('capture.saved_title'),self.open_saved,variant='ghost');self.saved_link.pack(fill='x')
        self.guidance=label(footer,'',10,MUTED,wraplength=480)
        self.form=tk.Frame(body,bg=BG);self.form.pack(fill='x')
        self.shiny=tk.BooleanVar(value=preset.get('shiny',False));Toggle(self.form,t('capture.shiny'),self.shiny,self.filters_changed).pack(fill='x',pady=(5,3))
        options=genders(number,self.root);self.gender=tk.StringVar(value=preset.get('gender','any'))
        Segments(self.form,[(k,t('capture.gender_'+k)) for k in ('any',*options)],self.gender,lambda _:self.filters_changed()).pack(fill='x',pady=(0,3))
        roles=preset.get('stat_preferences') or {k:'positive' if k in preset.get('priority_ivs',()) else 'neutral' for k in STAT_KEYS}
        self.stat_editor=CatchPreferences(self.form,initial=roles,command=self.filters_changed)
        self.search_seconds=tk.IntVar(value=preset.get('search_seconds') or 60);self.time_control=SearchTime(self.form,self.search_seconds)
        self.exact_ivs=tk.BooleanVar(value=preset.get('exact_ivs',bool(preset.get('min_ivs'))))
        self.iv_toggle=Toggle(self.form,t('capture.set_exact_ivs'),self.exact_ivs,self.exact_iv_changed);self.iv_toggle.pack(fill='x',pady=(5,0))
        self.iv_host=tk.Frame(self.form,bg=BG)
        self.iv_editor=IVPreferences(self.iv_host,minimums=[preset.get('min_ivs',{}).get(k,0) for k in STAT_KEYS],command=self.filters_changed,show_priorities=False,help_text=t('capture.exact_ivs_help'),title=t('capture.minimum_ivs_title'));self.ivs=self.iv_editor.values
        if self.exact_ivs.get():self.iv_host.pack(fill='x')
        advanced=Collapse(self.form,t('capture.advanced'));advanced.pack(fill='x',pady=(3,0))
        self.workers=tk.IntVar(value=preset.get('search_workers',2));row=tk.Frame(advanced.body,bg=BG);row.pack(fill='x',pady=4)
        self.workers_label=label(row,t('capture.workers'),11,pack=False);self.workers_label.pack(side='left');self.workers_control=Stepper(row,self.workers,1,6);self.workers_control.pack(side='right');Tooltip(row,t('capture.workers_help'))
        self.exact=tk.BooleanVar(value=preset.get('min_level',1)==preset.get('max_level',100));default=min((int(lv) for r in hunt_atlas(self.root)['entries'].get(str(number),[]) for lv in r['levels']),default=1);self.level=tk.IntVar(value=preset.get('min_level',default) if self.exact.get() else default)
        row=tk.Frame(advanced.body,bg=BG);row.pack(fill='x',pady=4);Toggle(row,t('capture.exact_level'),self.exact,self.changed).pack(side='left',fill='x',expand=True);self.level_control=Stepper(row,self.level,1,100);self.level_control.pack(side='right')
        self.maximum=tk.IntVar(value=preset.get('max_auto_speed',12));row=tk.Frame(advanced.body,bg=BG);row.pack(fill='x',pady=4);label(row,t('capture.max_speed'),11,pack=False).pack(side='left');Stepper(row,self.maximum,1,16).pack(side='right');Tooltip(row,t('capture.phase_speed_help'))
        self.locations=Collapse(self.form,t('capture.locations'));self.locations.pack(fill='x',pady=(3,0))
        actions=tk.Frame(self.locations.body,bg=BG);actions.pack(fill='x');self.auto_button=Button(actions,t('capture.auto_location'),self.choose_auto,variant='ghost');self.auto_button.pack(side='left');Button(actions,'↻',self.refresh,width=32,variant='ghost').pack(side='right')
        treebox=tk.Frame(self.locations.body,bg=BG);treebox.pack(fill='x',pady=5);self.tree=Table(treebox,columns=('map','level','chance'),show='headings',height=4,selectmode='browse',style='Trainer.Treeview');self.tree.heading('map',text=t('capture.location'));self.tree.heading('level',text=t('capture.levels'));self.tree.heading('chance',text=t('capture.chance'));self.tree.column('map',width=180);self.tree.column('level',width=65,stretch=False);self.tree.column('chance',width=55,stretch=False)
        sb=Scrollbar(treebox,command=self.tree.yview);self.tree.configure(yscrollcommand=sb.set);sb.pack(side='right',fill='y');self.tree.pack(fill='x',expand=True);self.tree.bind('<<TreeviewSelect>>',lambda _:self.select());self.tree.bind('<Down>',lambda _:self.move_selection(1));self.tree.bind('<Up>',lambda _:self.move_selection(-1))
        self.odds_label=label(self.form,'',10,BLUE,wraplength=480);Tooltip(self.odds_label,t('capture.odds_help'))
        self.estimate_label=label(self.form,'',10,MUTED,wraplength=480);Tooltip(self.estimate_label,t('capture.estimates_help'))
        self.metrics=label(self.best_frame,'',11,BLUE,wraplength=480);self.metrics_hint=Tooltip(self.metrics,'')
        self.wait_estimate=label(self.best_frame,'',10,MUTED,wraplength=480)
        label(self.best_frame,t('capture.encounters_explanation'),10,MUTED,wraplength=480)
        from .search_candidates_ui import SearchCandidatesView
        self.candidate_view=SearchCandidatesView(self.best_frame,self.root,lambda sha:self.open_saved());self.best=None
        self.candidate_view.action.configure(text=t('capture.review_candidate'))
        self.filters_button=Button(self.best_frame,t('capture.edit_search'),self.toggle_filters,variant='ghost');self.filters_button.pack(fill='x')
        self.traces=[(self.level,self.level.trace_add('write',lambda *_:self.changed()))]+[(var,var.trace_add('write',lambda *_:self.filters_changed())) for var in (self.workers,self.maximum,self.search_seconds)]
        self.tree.bind('<ButtonRelease-1>',lambda _:self.choose_manual(),add='+')
        body.bind('<Configure>',lambda e:[widget.configure(wraplength=max(220,e.width-16)) for widget in (self.title,self.odds_label,self.estimate_label,self.metrics,self.wait_estimate,self.guidance,self.detail,self.activity)],add='+')
        self.frame.bind('<Map>',lambda _:self.wake(),add='+')
        self.frame.bind('<Unmap>',lambda _:self.suspend(),add='+')
        self.ready_form=True;self.refresh();self.poll()
    def visible(self):return not self.closed and bool(self.frame.winfo_viewable())
    def suspend(self):
        if not self.closed and not self.suspended:
            self.suspended=True;self.service.close();self.request_id+=1;self.loading=False
    def wake(self):
        if self.suspended and self.visible():
            self.suspended=False;self.service=HuntService();self.preview_generation=None;self.refresh()
    def open_saved(self):
        data=self.m.operation.data
        identifier=(data.get('catch_context') or {}).get('id') or (Path(data.get('job')).name if data.get('active') and data.get('job') else (self.m.operation.result or {}).get('operation_id') if self.own_operation else None)
        return self.m.battle_panel.open_saved_encounters(self.panel,identifier,self.candidate_view.selected)
    def stop_and_choose(self):
        self.choose_after_stop=True;self.m.operation.command('pause');self.activity.configure(text=t('capture.stopping'))
    def toggle_filters(self):self.show_filters=not self.show_filters;self.update_actions()
    def use_best(self):self.open_saved()
    def exact_iv_changed(self):
        if self.exact_ivs.get():self.iv_host.pack(fill='x',after=self.iv_toggle)
        else:self.iv_host.pack_forget()
        self.filters_changed()
    def target(self):
        gender=self.gender.get();level=self.level.get()
        return CaptureTarget.parse(dict(species_id=self.number,shiny=self.shiny.get(),gender=gender,min_ivs={k:v.get() for k,v in self.ivs.items()},stat_preferences=self.stat_editor.preferences,exact_ivs=self.exact_ivs.get(),search_seconds=self.search_seconds.get(),min_level=level if self.exact.get() else 1,max_level=level if self.exact.get() else 100,route=self.fixed_route,method=self.fixed_method,search_workers=self.workers.get()),self.root)
    def refresh_odds(self,row=None):
        if not hasattr(self,'odds_label'):return
        try:
            chance=row['probability']/100 if row else 1.
            odds=wild_odds(self.target(),self.root,encounter=chance);from .search_odds import percent
            self.odds_label.configure(text=t('capture.odds',chance=percent(odds['target'])))
            self.odds_label._tooltip.text=summary(odds,location=row is not None)
            self.estimate_label.configure(text=hunt_estimates(odds)['text'] if row else t('capture.estimates_choose_location'))
        except (ValueError,tk.TclError) as error:self.odds_label.configure(text=str(error));self.estimate_label.configure(text='')
    def filters_changed(self):
        if self.closed:return
        if self.ready_form:self.form_dirty=True
        try:self.target();self.filters_valid=True;self.select()
        except Exception as error:self.filters_valid=False;self.activity.configure(text=str(error));self.start.configure(state='disabled')
    def choose_manual(self):self.autoselect=False;self.select()
    def changed(self):
        if self.closed:return
        if self.ready_form:self.form_dirty=True
        self.loading=True;self.start.configure(state='disabled')
        if self.debounce:self.window.after_cancel(self.debounce)
        self.debounce=self.window.after(250,self.refresh)
    def refresh(self):
        self.debounce=None
        if self.closed or self.suspended:return
        self.request_id+=1;request=self.request_id;generation=self.m.generation
        try:
            target=self.target();self.filters_valid=True;self.preview_generation=generation;self.level_control.configure(state='normal' if self.exact.get() else 'disabled');self.auto_button.configure(state='disabled' if self.fixed_route else 'normal')
            if not candidates(target,self.root):self.result=dict(rows=[]);self.loading=False;self.fill();self.activity.configure(text='Нет обычных диких встреч с этими параметрами уровня и способа.');return
            self.loading=True;self.activity.configure(text='Проверяем путь к месту встреч, отряд и возврат в Center…')
            def accept(snapshot):
                if self.closed or request!=self.request_id or generation!=self.m.generation or snapshot['generation']!=generation:return
                self.service_request=request;self.service.request(self.root,snapshot['state'],target.as_dict())
            self.m.watch(self.m.runtime.submit('travel_snapshot'),accept,lambda e:self.fail(request,e))
        except Exception as error:self.fail(request,error)
    def fail(self,request,error):
        if self.closed or request!=self.request_id:return
        self.loading=False;self.result=None;self.fill();self.activity.configure(text=str(error));self.start.configure(state='disabled')
    def fill(self):
        self.tree.delete(*self.tree.get_children());self.rows={}
        for i,row in enumerate((self.result or {}).get('rows',[])):
            key=str(i);self.rows[key]=row;levels=level_label(dict(levels=row['levels'],min_level=min(map(int,row['levels'])),max_level=max(map(int,row['levels']))))
            self.tree.insert('','end',iid=key,values=(('✓ ' if row['available'] else '— ')+row['label']+' · '+METHODS.get(row['method'],row['method']),levels,f"{row['probability']:g}%"))
        key=next((k for k,v in self.rows.items() if v['available']),next(iter(self.rows),None))
        if key:self.tree.selection_set(key);self.tree.focus(key)
        self.select()
    def choose_auto(self):self.autoselect=True;self.select()
    def move_selection(self,delta):
        keys=list(self.rows);selection=self.tree.selection()
        if keys:
            index=max(0,min(len(keys)-1,keys.index(selection[0])+delta if selection else 0));self.tree.selection_set(keys[index]);self.tree.focus(keys[index]);self.tree.see(keys[index]);self.autoselect=False;self.select()
        return 'break'
    def select(self):
        selected=self.tree.selection();self.selected=selected[0] if selected else None;row=self.rows.get(self.selected)
        self.refresh_odds(row)
        if not row:self.detail.configure(text='Выберите параметры и доступную локацию.');self.start.configure(state='disabled');return
        self.detail.configure(text=t('capture.selected_location',name=row['label'],hunter=row.get('hunter_name','—')) if row['available'] else row['reason'])
        Tooltip(self.detail,('Удочка и берег проверены' if row['method'] in ('old_rod','good_rod','super_rod') else 'Участок '+str(row['farm']['pair'])) if row['available'] else row['reason'])
        self.update_actions()
    def update_actions(self):
        state=self.m.last_state or {};controls=state.get('controls',{});free=state.get('ready') and not state.get('in_battle') and controls.get('callback')=='CB2_Overworld' and not controls.get('field_locked') and not controls.get('moving')
        row=self.rows.get(self.selected);busy=self.m.operation.active or self.m.automation.running
        context=self.m.operation.data.get('catch_context') or {};retained=not self.m.operation.active and context.get('state')=='paused' and context.get('config',{}).get('species_id')==self.number
        self.start.configure(state='normal' if row and row['available'] and self.filters_valid and not self.loading and free and not busy else 'disabled')
        if retained and not self.form_dirty and not busy:self.start.configure(state='normal' if not self.m.status.get('saving') else 'disabled')
        if retained or self.m.operation.active and self.m.operation.kind=='local':
            if not self.finish_button.winfo_manager():self.finish_button.pack(fill='x',pady=(3,0))
        else:self.finish_button.pack_forget()
        local=self.m.operation.active and self.m.operation.kind=='local'
        if local:
            self.form_dirty=False;self.start.pack_forget();self.form.pack_forget();self.running_controls.pack(fill='x');self.best_frame.pack(fill='x',pady=8)
        else:
            self.running_controls.pack_forget()
            if not self.start.winfo_manager():self.start.pack(fill='x')
            if self.show_filters and not self.form.winfo_manager():self.form.pack(fill='x')
        progress=self.m.operation.data.get('progress',{}) if local else (self.m.operation.result or {}) if self.own_operation and retained else {}
        search=(context.get('search') if retained else progress.get('search')) or {};self.best=search.get('best')
        if search:
            self.best_frame.pack(fill='x',before=self.form,pady=8) if self.form.winfo_manager() else self.best_frame.pack(fill='x',pady=8);self.metrics.configure(text=t('capture.metrics',count=search.get('attempts',0),workers=search.get('workers',1),rate=f"{search.get('rate',0):.2f}"))
        if search:
            elapsed=max(0,int(search.get('seconds',0)));self.wait_estimate.configure(text=t('capture.elapsed',time=literal(f'{elapsed//60}:{elapsed%60:02d}')))
            try:
                cfg=progress.get('target') or (self.m.operation.result or {}).get('config');target=CaptureTarget.parse(cfg,self.root) if cfg else self.target();row=self.rows.get(self.selected);probability=wild_odds(target,self.root,encounter=(row['probability']/100 if row else 1.))['target'];rate=search.get('rate',0)
                if search.get('search_seconds') is not None:
                    self.wait_estimate.configure(text=t('capture.budget_finished') if search.get('finish_reason') else t('capture.time_left',seconds=ceil(search['remaining'])) if search.get('budget_started') and search.get('remaining') is not None else t('capture.budget_preparing'))
                elif probability>0 and rate>0:
                    minutes=1/(probability*rate*60);estimate=t('capture.very_rare') if minutes>1440 else t('capture.expected_full',mean=max(1,round(minutes)),p95=max(1,round(-log(.05)*minutes)))
                    self.wait_estimate.configure(text=t('capture.elapsed',time=literal(f'{elapsed//60}:{elapsed%60:02d}'))+'\n'+estimate)
            except (ValueError,TypeError,KeyError,tk.TclError):pass
            lanes=search.get('lanes',[])
            self.metrics_hint.text=((t('capture.transport_used',mode=t('capture.mode_'+search['transport']))+'\n') if search.get('transport') else '')+'\n'.join(t('capture.worker_metrics',lane=v['lane'],pid=v.get('pid') or '—',count=v.get('attempts',0),cpu=f"{v.get('cpu_seconds',0):.1f}") for v in lanes)
        completed=(self.m.operation.result or {}).get('status')=='ready' and (self.m.operation.result or {}).get('applied')
        if completed and not local and not retained:search={};self.best=None;self.best_frame.pack_forget()
        if not search:self.best_frame.pack_forget()
        rows=search.get('candidates') or ([self.best] if self.best else [])
        if rows and not self.results_shown:self.results_shown=True;self.show_filters=False
        if local or not self.show_filters:self.form.pack_forget()
        elif not self.form.winfo_manager():self.form.pack(fill='x')
        self.candidate_view.update(rows,not busy and bool(rows))
        self.guidance.configure(text=t('capture.running_hint') if local else t('capture.saved_ready') if rows else t('capture.start_hint'))
        self.start.configure(text=t('capture.resume_search') if retained and not self.form_dirty else t('capture.search_again') if rows else t('capture.start'))
        if local:self.filters_button.pack_forget()
        elif rows:self.filters_button.pack(fill='x')
        else:self.filters_button.pack_forget()
    def run(self):
        context=self.m.operation.data.get('catch_context') or {}
        if context.get('state')=='paused' and context.get('config',{}).get('species_id')==self.number and not self.form_dirty:
            return self.open_saved()
        try:
            target=self.target();row=self.rows.get(self.selected)
            if not row or not row['available']:return
            config=target.as_dict()
            if not self.autoselect or self.fixed_route:config.update(route=row['map'],method=row['method'])
            config.update(schema_version=2,max_auto_speed=self.maximum.get());self.m.operation.begin('local',config);self.own_operation=True;self.activity.configure(text='Сохраняем резервную копию и начинаем автопоимку…');self.update_actions()
        except Exception as error:self.activity.configure(text=str(error))
    def poll(self):
        if self.closed:return
        if self.suspended or not self.visible():
            self.after=self.window.after(200,self.poll);return
        ready=self.service.poll()
        if ready and self.service_request==self.request_id and self.preview_generation==self.m.generation:
            result,error=ready;self.loading=False
            if error:self.result=None;self.fill();self.activity.configure(text=error)
            elif result:self.result=result;self.fill();self.activity.configure(text=f"Проверено · доступных мест: {sum(r['available'] for r in result['rows'])}")
        if self.m.operation.active:self.activity.configure(text=self.m.notice)
        elif self.own_operation and self.m.operation.result and self.m.operation.result.get('kind')=='local':self.activity.configure(text=self.m.operation.result.get('stage',''))
        if self.preview_generation is not None and self.preview_generation!=self.m.generation and not self.m.operation.active:self.refresh()
        if self.choose_after_stop and not self.m.operation.active and not self.m.status.get('saving'):
            self.choose_after_stop=False;self.open_saved();return
        self.update_actions();self.after=self.window.after(150,self.poll)
    def close(self):
        if self.closed:return
        self.closed=True;self.service.close()
        try:
            if self.after:self.window.after_cancel(self.after)
            if self.debounce:self.window.after_cancel(self.debounce)
            for var,token in self.traces:var.trace_remove('write',token)
            self.frame.destroy()
        except tk.TclError:pass
