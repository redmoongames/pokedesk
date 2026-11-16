"""Paused encounter alternatives survive views until caught, retired or expired."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
import time
from . import localized_tk as tk
from .ui import BG,MUTED,BLUE,AMBER,Button,Select,label,card
from .scrolling import Scrollbar
from .search_candidates_ui import SearchCandidatesView
from .wild_search_history import saved_searches
from .i18n import t,format_datetime,literal,format_number
from .entity_names import species_name,nature_name

class SavedEncountersView:
    title_text=t('capture.saved_title')
    def __init__(self,panel,parent,*,operation_id=None,sha=None):
        self.panel=panel;self.m=panel.monitor;self.root=self.m.folder;self.closed=False;self.selected_id=operation_id;self.rows=[];self.record=None;self.after=None;self.confirmation=None;self.confirm_mode='catch';self.attempted=False;self.previous_result_id=None;self.requested_sha=sha;self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='saved-encounters');self.future=None;self.next_scan=0;self.labels={}
        self.frame=tk.Frame(parent,bg=BG);self.frame.pack(fill='both',expand=True)
        footer=tk.Frame(self.frame,bg=BG,padx=10,pady=8);footer.pack(side='bottom',fill='x');self.status=label(footer,'',10,BLUE,wraplength=450)
        self.stop=Button(footer,t('capture.stop_choose'),self.stop_search,variant='primary');self.stop.pack(fill='x',pady=4)
        self.secondary=tk.Frame(footer,bg=BG)
        self.resume=Button(self.secondary,t('capture.resume_search'),self.ask_resume);self.resume.pack(side='left',fill='x',expand=True,padx=(0,3))
        self.finish=Button(self.secondary,t('capture.finish_search'),self.finish_search,variant='ghost');self.finish.pack(side='right',fill='x',expand=True,padx=(3,0))
        self.action=Button(footer,t('capture.review_candidate'),self.ask,variant='primary');self.action.pack(fill='x',pady=4);self.secondary.pack(fill='x',pady=3)
        self.confirm_actions=tk.Frame(footer,bg=BG);self.confirm_button=Button(self.confirm_actions,t('capture.confirm_saved'),self.confirm,variant='primary');self.confirm_button.pack(fill='x',pady=4);Button(self.confirm_actions,t('capture.back_to_candidates'),self.dismiss,variant='ghost').pack(fill='x')
        canvas=self.canvas=tk.Canvas(self.frame,bg=BG,highlightthickness=0,yscrollincrement=1);scroll=Scrollbar(self.frame,command=canvas.yview);canvas.configure(yscrollcommand=scroll.set);scroll.pack(side='right',fill='y');canvas.pack(fill='both',expand=True);body=tk.Frame(canvas,bg=BG,padx=10,pady=8);item=canvas.create_window(0,0,anchor='nw',window=body);body.bind('<Configure>',lambda _:canvas.configure(scrollregion=canvas.bbox('all')));canvas.bind('<Configure>',lambda e:canvas.itemconfigure(item,width=e.width))
        self.review_parent=body;self.browser=tk.Frame(body,bg=BG);self.browser.pack(fill='x');body=self.browser
        self.confirm_box=card(self.review_parent);self.confirm_text=label(self.confirm_box,'',10,AMBER,wraplength=250)
        label(body,t('capture.saved_title'),17,bold=True);label(body,t('capture.encounters_explanation'),10,MUTED,wraplength=450)
        self.choice=tk.StringVar();self.picker=Select(body,self.choice,command=self.select);self.picker.pack(fill='x',pady=8);self.info=label(body,'',10,BLUE,wraplength=450);self.criteria=label(body,'',10,MUTED,wraplength=450)
        self.candidates=SearchCandidatesView(body,self.root,lambda _:self.ask(),on_select=lambda _:self.dismiss());self.candidates.action.pack_forget()
        self.frame.bind('<Destroy>',lambda e:self.close() if e.widget is self.frame else None,add='+');body.bind('<Configure>',lambda e:[w.configure(wraplength=max(200,e.width-20)) for w in (self.info,self.criteria)],add='+');self.confirm_box.bind('<Configure>',lambda e:self.confirm_text.configure(wraplength=max(150,e.width-28)),add='+');footer.bind('<Configure>',lambda e:self.status.configure(wraplength=max(150,e.width-20)),add='+');self.poll()
    def stop_search(self):
        self.m.operation.command('pause');self.status.configure(text=t('capture.stopping'))
    def finish_search(self):
        identifier=self.record['id'] if self.record else None
        if self.m.operation.active:
            identifier=Path(self.m.operation.job).name if self.m.operation.job else None
        if identifier:
            self.m.operation.command('finish_search:'+identifier);self.dismiss();self.status.configure(text=t('capture.finishing'))
    def ask_resume(self):
        if not self.record or self.m.operation.active or self.m.automation.running or self.m.status.get('saving'):return
        self.confirmation={'operation_id':self.record['id']};self.confirm_mode='resume'
        self.confirm_text.configure(text=t('capture.resume_review',time=format_datetime(self.record['created_at']),slot=t('capture.rollback_slot')))
        self.show_confirmation()
    def select(self,caption):
        identifier=self.labels.get(caption)
        if identifier!=self.selected_id:self.selected_id=identifier;self.dismiss()
        self.render()
    def render(self):
        self.rows=[r for r in self.rows if r.get('expires_at') is None or time.time()<r['expires_at']]
        self.record=next((r for r in self.rows if r['id']==self.selected_id),None)
        busy=self.m.operation.active or self.m.automation.running or bool(self.m.status.get('saving'))
        self.resume.configure(state='normal' if self.record and not busy else 'disabled')
        self.finish.configure(state='normal' if self.record and not busy or self.m.operation.active and self.m.operation.kind=='local' else 'disabled')
        if not self.record and self.confirmation:self.dismiss()
        if self.record:
            row=self.record;cfg=row['config'];self.info.configure(text=t('capture.saved_summary',name=species_name(cfg['species_id']),time=format_datetime(row['created_at']),count=row['attempts']))
            values=' · '.join(f"{name} ≥{cfg.get('min_ivs',{}).get(key,10)}" for key,name in zip(('hp','attack','defense','speed','special_attack','special_defense'),('HP','ATK','DEF','SPEED','SP ATK','SP DEF')))
            self.criteria.configure(text=t('capture.saved_criteria',ivs=literal(values),gender=t('capture.gender_'+cfg.get('gender','any')),natures=len(cfg.get('natures') or []) or 25))
            if cfg.get('stat_preferences'):
                from .models import STAT_KEYS
                from .iv_preferences_ui import TITLES
                roles=cfg['stat_preferences'];parts={role:literal(', '.join(title for k,title in zip(STAT_KEYS,TITLES) if roles.get(k)==role) or '—') for role in ('positive','negative')}
                text=t('capture.saved_priority_criteria',positive=parts['positive'],negative=parts['negative'],seconds=cfg.get('search_seconds') or '—')
                if cfg.get('exact_ivs'):text=str(text)+'\n'+str(t('capture.minimum_criteria',ivs=literal(values)))
                self.criteria.configure(text=text)
            if self.requested_sha:
                self.candidates.selected=self.requested_sha;self.candidates.user_selected=True;self.requested_sha=None
            self.candidates.update(row['candidates'],not busy);self.action.configure(state='normal' if self.candidates.selected and not busy else 'disabled');self.confirm_button.configure(state='disabled' if busy else 'normal')
        else:self.info.configure(text=t('capture.loading_saved') if self.future else t('capture.saved_missing') if self.rows else t('capture.no_saved_encounters'));self.criteria.configure(text='');self.candidates.update([],False);self.action.configure(state='disabled')
        if self.m.operation.active and self.m.operation.kind=='local':self.stop.pack(fill='x',before=self.action,pady=4)
        else:self.stop.pack_forget()
        if not self.confirmation:
            result=self.m.operation.result or {}
            self.status.configure(text=(getattr(self.m,'notice','') or t('capture.stop_before_choose')) if busy else t('capture.saved_ready'))
            if not busy and (result.get('config',{}).get('_saved_candidate') or self.attempted and result.get('operation_id')!=self.previous_result_id):
                self.status.configure(text=t('capture.saved_problem',reason=result.get('stage') or getattr(self.m,'notice','')) if result.get('status') in ('error','attention') else t('capture.saved_done') if result.get('status')=='ready' and result.get('applied') else t('capture.saved_attempt_stopped'))
    def ask(self):
        if self.m.operation.active or self.m.automation.running or self.m.status.get('saving') or not self.record:return
        selected=next((r for r in self.record['candidates'] if r['sha256']==self.candidates.selected),None)
        if not selected:return
        self.confirm_mode='catch';self.confirmation=dict(operation_id=self.record['id'],sha256=selected['sha256']);mon=selected['pokemon']
        self.confirm_text.configure(text=t('capture.rollback_review',name=species_name(mon['species_id']),level=mon['level'],nature=nature_name(mon.get('nature',mon['personality']%25)),time=format_datetime(self.record['created_at']),score=format_number(selected['score'],decimals=int(selected['score']%1!=0)),goal=format_number(selected['target_score'],decimals=int(selected['target_score']%1!=0)),slot=t('capture.rollback_slot')))
        self.show_confirmation()
    def show_confirmation(self):
        self.secondary.pack_forget()
        self.confirm_button.configure(text=t('capture.confirm_resume') if self.confirm_mode=='resume' else t('capture.confirm_saved'))
        self.browser.pack_forget();self.confirm_box.pack(fill='x',pady=6);self.action.pack_forget();self.status.pack_forget();self.confirm_actions.pack(fill='x');self.canvas.yview_moveto(0)
    def dismiss(self):
        self.confirmation=None;self.confirm_box.pack_forget();self.confirm_actions.pack_forget()
        if not self.browser.winfo_manager():self.browser.pack(fill='x')
        if not self.status.winfo_manager():self.status.pack(fill='x')
        if not self.action.winfo_manager():self.action.pack(fill='x',pady=4)
        if not self.secondary.winfo_manager():self.secondary.pack(fill='x',pady=3)
    def confirm(self):
        reference=self.confirmation
        if not reference or self.m.operation.active or self.m.automation.running or self.m.status.get('saving'):return
        mode=self.confirm_mode;self.dismiss();self.attempted=True;self.previous_result_id=(self.m.operation.result or {}).get('operation_id')
        try:self.m.operation.begin('local',dict(schema_version=2,_resume_search=reference['operation_id']) if mode=='resume' else dict(schema_version=2,_saved_candidate=reference));self.status.configure(text=t('capture.saving_before_restore'))
        except Exception as error:self.status.configure(text=str(error))
    def poll(self):
        if self.closed:return
        if self.future and self.future.done():
            try:
                rows=self.future.result()
                self.rows=rows;self.labels={str(t('capture.search_label',number=i+1,name=species_name(r['config']['species_id']),time=format_datetime(r['created_at']))):r['id'] for i,r in enumerate(rows)};self.picker.configure(values=list(self.labels))
                if self.selected_id not in {r['id'] for r in rows}:self.selected_id=rows[0]['id'] if rows else None
                self.choice.set(next((label for label,identifier in self.labels.items() if identifier==self.selected_id),''))
            except Exception as error:self.status.configure(text=str(error))
            self.future=None
        op=self.m.operation;token=(op.active,str(op.job),(op.result or {}).get('operation_id'),getattr(op,'data',{}).get('context_revision',0))
        if self.future is None and token!=getattr(self,'scan_token',None):self.scan_token=token;self.future=self.pool.submit(saved_searches,self.root)
        self.render();self.after=self.frame.after(150,self.poll)
    def close(self):
        if self.closed:return
        self.closed=True
        if self.after:
            try:self.frame.after_cancel(self.after)
            except tk.TclError:pass
        self.pool.shutdown(wait=False,cancel_futures=True)
        if self.frame.winfo_exists():self.frame.destroy()
