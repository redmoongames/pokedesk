"""Execution and starter recovery inside the existing left context panel."""
from math import log
from . import localized_tk as tk
from .ui import BG,CARD,MUTED,TEXT,GREEN,AMBER,BLUE,Button,Segments,Toggle,Stepper,label
from .scrolling import Scrollbar
from .i18n import t,literal,format_number
from .entity_names import nature_name,pokemon_name
from .models import STAT_KEYS
from .new_game_config import NewGameConfig
from .nature_preferences import NatureFilter
from .iv_preferences_ui import IVPreferences
from .search_odds import starter_odds,summary

def duration(seconds):
    seconds=max(0,int(seconds));return f'{seconds//60}:{seconds%60:02d}'

def candidate_text(best):
    if not best:return str(t('search.wait_candidate'))
    mon=best['pokemon'];ivs=mon['ivs'];values='\n'.join(f'{a} {ivs[x]}  /  {b} {ivs[y]}' for a,x,b,y in (('HP','hp','ATK','attack'),('DEF','defense','SPEED','speed'),('SP ATK','special_attack','SP DEF','special_defense')))
    missing=[]
    for v in best['missing']:
        if v['kind']=='iv':missing.append(t('search.iv_short',stat=('HP' if v['stat']=='hp' else t('nature_filter.stat_'+v['stat'])),actual=v['actual'],required=v['required']))
        else:missing.append(t('search.missing_'+v['kind']))
    return str(t('search.best_card',name=pokemon_name(mon),nature=str(nature_name(mon['nature']))+' '+('♀' if mon['personality']&255<31 else '♂')+(' ★' if mon.get('shiny') else ''),ivs=values,missing='; '.join(map(str,missing)) or t('search.all_match')))

class AutomationContext:
    def __init__(self,panel):
        self.panel=panel;self.m=panel.monitor;self.frame=tk.Frame(panel.window,bg=BG);self.marker=None;self.loading=False;self.pending=None;self.editor=None;self.last_job=None;self.best=None;self.retained=False;self.confirming=False;self.selected_sha=None;self.candidate_signature=None;self.resume_after_confirm=False
        canvas=tk.Canvas(self.frame,bg=BG,highlightthickness=0,yscrollincrement=1);scroll=Scrollbar(self.frame,command=canvas.yview);canvas.configure(yscrollcommand=scroll.set);scroll.pack(side='right',fill='y');canvas.pack(fill='both',expand=True)
        self.body=tk.Frame(canvas,bg=BG,padx=12,pady=12);item=canvas.create_window(0,0,anchor='nw',window=self.body);self.body.bind('<Configure>',lambda _:canvas.configure(scrollregion=canvas.bbox('all')));canvas.bind('<Configure>',lambda e:canvas.itemconfigure(item,width=e.width));self.canvas=canvas
        self.title=label(self.body,t('search.context_title'),16,bold=True);self.stage=label(self.body,'',11,BLUE,wraplength=285)
        self.metrics=label(self.body,'',12,TEXT,wraplength=285);self.lanes=label(self.body,'',10,MUTED,wraplength=285);self.estimate=label(self.body,'',10,MUTED,wraplength=285)
        self.candidate_tabs=tk.Frame(self.body,bg=BG);self.candidate_tabs.pack(fill='x');self.candidate_index=tk.IntVar(value=0)
        self.coverage=label(self.body,'',10,BLUE,wraplength=285)
        self.best_label=label(self.body,'',11,GREEN,wraplength=285);self.note=label(self.body,'',10,MUTED,wraplength=285)
        self.controls=tk.Frame(self.body,bg=BG);self.controls.pack(fill='x',pady=(8,0))
        self.pause_button=Button(self.controls,t('search.pause'),self.pause,height=32);self.pause_button.pack(fill='x',pady=2)
        self.finish_button=Button(self.controls,t('capture.finish_search'),lambda:self.m.operation.command('finish_search'),height=32,variant='ghost')
        self.saved_button=Button(self.controls,t('capture.saved_title'),self.open_saved,height=32)
        self.restart_button=Button(self.controls,t('search.restart'),self.restart,height=32);self.restart_button.pack(fill='x',pady=2)
        self.edit_button=Button(self.controls,t('search.edit'),self.edit,height=32);self.edit_button.pack(fill='x',pady=2)
        self.best_button=Button(self.controls,t('search.use_best'),self.ask_best,height=32);self.best_button.pack(fill='x',pady=2)
        self.confirm=tk.Frame(self.body,bg=CARD,padx=8,pady=8);label(self.confirm,t('search.confirm_best'),10,AMBER,wraplength=260);Button(self.confirm,t('search.confirm_use'),self.use_best,variant='primary',height=32).pack(fill='x',pady=3);Button(self.confirm,t('search.keep_search'),self.keep_search,height=30).pack(fill='x')
        self.retry_save=Button(self.controls,t('workspace.retry_save'),lambda:self.m.save(manual=True),height=32)
        self.body.bind('<Configure>',self.resize,add='+')
    def resize(self,event):
        for widget in (self.stage,self.metrics,self.lanes,self.estimate,self.coverage,self.best_label,self.note):widget.configure(wraplength=max(230,event.width-24))
    def load(self,callback=None):
        if self.loading:return
        self.loading=True
        def done(marker):
            self.loading=False;self.marker=marker;self.m.prologue_marker=marker
            if callback:callback()
        def failed(error):self.loading=False;self.note.configure(text=str(error),fg=AMBER)
        self.m.watch(self.m.runtime.submit('prologue_config'),done,failed)
    def wants(self):
        from .workspace import task_summary
        if task_summary(self.m).attention:return True
        if (self.marker or {}).get('status')=='complete' and self.m.last_state.get('in_battle'):self.retained=False
        op=getattr(getattr(self.m,'operation',None),'data',{});auto=self.m.automation.info() if hasattr(self.m,'automation') else {};marker=getattr(self.m,'prologue_marker',None)
        return bool(op.get('active') or auto.get('running') or getattr(self.m,'pending_start',False) or self.m.status.get('battle_auto',{}).get('active') or op.get('catch_context') or self.retained or marker and marker.get('status')!='complete')
    def update(self,state):
        from .workspace import task_summary
        summary=task_summary(self.m)
        if summary.attention:
            self.title.configure(text=summary.title);self.stage.configure(text=summary.stage)
            for widget in (self.metrics,self.lanes,self.estimate,self.coverage,self.best_label):widget.configure(text='')
            self.note.configure(text=t('workspace.save_failed') if summary.kind=='save_error' else t('search.takeover_hint'))
            for widget in (self.restart_button,self.edit_button,self.best_button,self.saved_button,self.finish_button):widget.pack_forget()
            self.candidate_tabs.pack_forget();self.dismiss_confirm()
            if summary.kind=='save_error':self.retry_save.pack(fill='x',pady=2);self.pause_button.configure(state='disabled')
            else:self.retry_save.pack_forget();self.pause_button.configure(text=t('workspace.return_game'),state='normal')
            return
        self.retry_save.pack_forget()
        op=getattr(getattr(self.m,'operation',None),'data',{});active=op.get('active',False);data=op.get('progress',{}) if active else op.get('result') or {};starter=(op.get('kind')=='prologue' if active else data.get('kind')=='prologue' and self.retained and not self.m.automation.running) or bool(getattr(self.m,'prologue_marker',None) and self.m.prologue_marker.get('status')!='complete')
        if starter:
            self.saved_button.pack_forget();self.finish_button.pack_forget()
            if not self.editor and not self.candidate_tabs.winfo_manager():self.candidate_tabs.pack(fill='x',before=self.coverage)
            self.retained=True
            if op.get('job')!=self.last_job or self.marker is None:
                self.last_job=op.get('job');self.load()
            search=data.get('search',{});progress=data.get('prologue') or (self.marker or {}).get('progress',{});best=(search.get('best') or progress.get('best')) if active else (self.marker or {}).get('best') or progress.get('best');candidates=(search.get('candidates') or progress.get('candidates')) if active else (self.marker or {}).get('candidates') or progress.get('candidates')
            candidates=candidates or ([best] if best else []);self.candidates=candidates
            signature=tuple(v['sha256'] for v in candidates if 'sha256' in v)
            if signature!=self.candidate_signature:
                self.candidate_signature=signature
                for w in self.candidate_tabs.winfo_children():w.destroy()
                if self.selected_sha not in signature:self.selected_sha=signature[0] if signature else None
                index=signature.index(self.selected_sha) if self.selected_sha in signature else 0;self.candidate_index.set(index)
                if len(candidates)>1:Segments(self.candidate_tabs,[(i,t('search.candidate_tab',number=i+1,score=v['score'])) for i,v in enumerate(candidates)],self.candidate_index,self.select_candidate).pack(fill='x')
            best=next((v for v in candidates if v.get('sha256')==self.selected_sha),best);self.best=best
            self.coverage.configure(text=t('search.coverage',score=best['score'],target=best['target_score']) if best else '')
            self.title.configure(text=t('search.starter_title'));self.stage.configure(text=data.get('stage') or t('prologue.paused'))
            self.metrics.configure(text=t('search.metrics',count=format_number(progress.get('attempts',search.get('attempts',0))),elapsed=duration(search.get('total_seconds',progress.get('search_seconds',0))),rate=format_number(search.get('rate',0),decimals=1)))
            self.lanes.configure(text='\n'.join(str(t('search.lane',lane=v['lane'],count=format_number(v['attempts']))) for v in search.get('lanes',[])))
            cfg=(self.marker or {}).get('config');rate=search.get('rate',0)
            if cfg and rate:
                expected=NewGameConfig.parse(cfg).expected_attempts()/rate;self.estimate.configure(text=t('search.estimate',mean=duration(expected),p95=duration(expected*log(20))))
            else:self.estimate.configure(text='')
            self.best_label.configure(text=candidate_text(best));self.note.configure(text=t('search.static_screen') if active else t('search.saved_best'),fg=MUTED)
            self.pause_button.configure(text=t('search.pause') if active else t('search.resume'),state='normal' if self.pending is None else 'disabled')
            for button in (self.restart_button,self.edit_button,self.best_button):
                if not button.winfo_manager():button.pack(fill='x',pady=2)
            editable=progress.get('phase',(self.marker or {}).get('progress',{}).get('phase','intro')) in ('intro','laboratory','choice','search')
            self.edit_button.configure(state='normal' if editable and self.pending is None else 'disabled');self.best_button.configure(state='normal' if best and editable and self.pending is None else 'disabled')
            self.restart_button.configure(state='normal' if editable and self.pending is None else 'disabled')
            if not active and (self.marker or {}).get('status')=='complete':
                self.title.configure(text=t('search.complete_title'));self.estimate.configure(text='');self.note.configure(text=t('search.complete_note'));self.pause_button.configure(text=t('search.done'))
                for button in (self.restart_button,self.edit_button,self.best_button):button.pack_forget()
            if self.pending=='choose' and not active and not self.m.status.get('saving'):
                self.pending=None;self.load(self.ask_best)
            if self.pending=='edit' and not active and not self.m.status.get('saving'):
                self.pending=None;self.load(self.show_editor)
        else:
            self.retained=False;self.candidate_tabs.pack_forget()
            context=op.get('catch_context') or {}
            if active and op.get('kind')=='local' or context and not active:
                self.saved_button.pack(fill='x',pady=2);self.finish_button.pack(fill='x',pady=2)
            else:self.saved_button.pack_forget();self.finish_button.pack_forget()
            auto=self.m.automation.info();self.title.configure(text=summary.title);self.stage.configure(text=(data.get('stage') if active else auto.get('reason') if auto.get('running') else self.m.status.get('battle_auto',{}).get('reason')) or t('search.working'))
            action=auto.get('stage') or '';
            if isinstance(action,dict):action=action.get('label') or action.get('name') or t('search.working')
            self.metrics.configure(text=str(action));self.lanes.configure(text='');self.estimate.configure(text='');self.best_label.configure(text='');self.coverage.configure(text='');self.note.configure(text=t('search.takeover_hint'));self.pause_button.configure(text=t('search.resume') if auto.get('running') and getattr(self.m,'paused',False) else t('search.pause'),state='normal')
            for button in (self.restart_button,self.edit_button,self.best_button):button.pack_forget()
            run=self.m.history.meta.get('run') or {};config=(run.get('context') or {}).get('config',{});mon=next((m for m in state.get('party',[]) if m.get('uid')==config.get('trainee')),None)
            if context and not active:
                self.stage.configure(text=t('capture.search_paused'));self.note.configure(text=t('capture.paused_lifetime'));self.pause_button.configure(text=t('capture.resume_search'))
            if mon and summary.kind=='training':self.best_label.configure(text=t('search.training_progress',name=pokemon_name(mon),level=mon['level'],target=config.get('target','—'),xp=format_number(mon.get('experience',0))))
    def open_saved(self):
        if self.m.panel is None:self.m.show_panel()
        return self.panel.open_saved_encounters(self.m.panel)
    def pause(self):
        if self.m.automation.info().get('status') in ('attention','error') and not self.m.automation.running:return self.m.recover_input()
        if self.marker and self.marker.get('status')=='complete':self.retained=False;self.m.prologue_marker=None;self.marker=None;return
        if self.m.operation.active:self.m.operation.command('pause')
        elif self.m.automation.running:self.m.toggle_pause()
        elif self.marker and self.marker.get('status')!='complete':self.m.operation.begin('prologue',{})
        elif self.m.operation.data.get('catch_context'):self.open_saved()
        else:self.m.take_control(focus=False)
    def restart(self):
        self.dismiss_confirm()
        if self.m.operation.active:self.m.operation.command('restart_search')
        else:self.m.operation.begin('prologue',{})
    def edit(self):
        self.dismiss_confirm()
        if self.m.operation.active:self.pending='edit';self.m.operation.command('pause');self.note.configure(text=t('search.stopping'))
        else:self.load(self.show_editor)
    def select_candidate(self,index):
        if 0<=index<len(self.candidates):self.selected_sha=self.candidates[index]['sha256'];self.update(self.m.last_state)
    def ask_best(self):
        if not self.best:return
        if self.m.operation.active:self.resume_after_confirm=True;self.pending='choose';self.m.operation.command('pause');return
        self.confirm.pack(fill='x',pady=8);self.confirming=True
    def dismiss_confirm(self):self.confirm.pack_forget();self.confirming=False
    def keep_search(self):
        resume=self.resume_after_confirm;self.resume_after_confirm=False;self.dismiss_confirm()
        if resume and not self.m.operation.active:self.m.operation.begin('prologue',{})
    def use_best(self):
        self.dismiss_confirm();self.resume_after_confirm=False
        sha=(self.best or {}).get('sha256')
        if not sha:return
        if self.m.operation.active:self.m.operation.command('use_candidate:'+sha)
        else:self.m.operation.begin('prologue',dict(use_best=True,candidate_sha=sha))
    def show_editor(self):
        if not self.marker or self.m.operation.active:return
        if self.editor:self.editor.destroy()
        cfg=NewGameConfig.parse(self.marker['config']);self.controls.pack_forget();self.editor=tk.Frame(self.body,bg=BG);self.editor.pack(fill='x')
        for widget in (self.title,self.stage,self.metrics,self.lanes,self.estimate,self.candidate_tabs,self.coverage,self.best_label,self.note):widget.pack_forget()
        label(self.editor,t('search.edit'),14,bold=True);self.gender=tk.StringVar(value=cfg.gender);Segments(self.editor,[(k,t('prologue.'+k)) for k in ('any','male','female')],self.gender).pack(fill='x');self.shiny=tk.BooleanVar(value=cfg.shiny);Toggle(self.editor,t('capture.shiny'),self.shiny,self.editor_odds).pack(fill='x')
        self.natures=NatureFilter(self.editor,initial=cfg.natures,command=self.editor_odds,compact=True)
        self.iv_editor=IVPreferences(self.editor,minimums=cfg.min_ivs,preferred=cfg.priority_ivs,command=self.editor_odds);self.ivs=self.iv_editor.values
        row=tk.Frame(self.editor,bg=BG);row.pack(fill='x',pady=4);label(row,t('capture.workers'),10,MUTED,wraplength=145,pack=False).pack(side='left');self.workers=tk.IntVar(value=cfg.search_workers);Stepper(row,self.workers,1,4).pack(side='right')
        self.gender.trace_add('write',lambda *_:self.editor_odds())
        self.edit_odds=label(self.editor,'',10,BLUE,wraplength=280);Button(self.editor,t('search.save_resume'),self.save_editor,variant='primary').pack(fill='x',pady=5);Button(self.editor,t('search.back'),self.close_editor).pack(fill='x');self.editor_odds();self.canvas.yview_moveto(0)
    def editor_patch(self):return dict(gender=self.gender.get(),shiny=self.shiny.get(),nature=None,natures=self.natures.selected,priority_ivs=self.iv_editor.preferred,min_ivs=[self.ivs[k].get() for k in STAT_KEYS],search_workers=self.workers.get())
    def editor_odds(self):
        if not getattr(self,'edit_odds',None) or not self.editor or not self.edit_odds.winfo_exists():return
        try:self.edit_odds.configure(text=summary(starter_odds(NewGameConfig.parse(dict(self.marker['config'],**self.editor_patch()))),starter=True))
        except (ValueError,tk.TclError) as e:self.edit_odds.configure(text=str(e))
    def save_editor(self):
        try:patch=self.editor_patch();NewGameConfig.parse(dict(self.marker['config'],**patch))
        except (ValueError,tk.TclError) as e:self.note.configure(text=str(e),fg=AMBER);return
        def saved(_):self.close_editor();self.load();self.m.operation.begin('prologue',{})
        self.m.watch(self.m.runtime.submit('prologue_config',patch),saved,lambda e:self.note.configure(text=str(e),fg=AMBER))
    def close_editor(self):
        if self.editor:self.editor.destroy();self.editor=None
        for widget in (self.title,self.stage,self.metrics,self.lanes,self.estimate,self.candidate_tabs,self.coverage,self.best_label,self.note):widget.pack(fill='x')
        self.controls.pack(fill='x',pady=(8,0));self.canvas.yview_moveto(0)
