"""Stable trainer sections and detached task presentation for both side windows."""
from dataclasses import dataclass
from .i18n import t
from . import localized_tk as tk
from .ui import BG, CARD, TEXT, MUTED, BLUE, AMBER, Button, Segments, label


@dataclass(frozen=True)
class TaskSummary:
    kind: str
    title: str
    stage: str
    active: bool
    attention: bool = False


def task_summary(monitor):
    """Resolve ownership before battle context, without reading an emulator."""
    status = monitor.status
    auto = monitor.automation.info() if hasattr(monitor,'automation') else {}
    op = monitor.operation.data if hasattr(monitor,'operation') else {}
    if status.get('save_failed'):
        return TaskSummary('save_error', str(t('design.save_error')), str(t('workspace.save_failed')), False, True)
    if auto.get('status') in ('attention', 'error') and not auto.get('running'):
        return TaskSummary('attention', str(t('search.context_title')), str(auto.get('reason') or ''), False, True)
    if op.get('active'):
        progress = op.get('progress') or {}
        return TaskSummary('operation', str(t('search.context_title')), str(progress.get('stage') or t('search.working')), True)
    if getattr(getattr(monitor,'delivery',None),'data',{}).get('enabled') and not auto.get('running') and not getattr(monitor,'pending_start',False):
        return TaskSummary('delivery',str(t('workspace.delivery')),str(t('workspace.delivery_reserved')),True)
    if getattr(monitor, 'pending_start', False):
        return TaskSummary('preparing', str(t('search.context_title')), str(getattr(monitor,'notice','') or t('search.working')), True)
    if auto.get('running'):
        script = auto.get('script')
        kind = {'train_xp.py':'training', 'travel.py':'travel', 'change_party.py':'party','auto_battle.py':'battle_auto'}.get(script, 'script')
        stage = auto.get('stage') or auto.get('reason') or t('search.working')
        if isinstance(stage, dict):stage=stage.get('label') or stage.get('name') or ''
        return TaskSummary(kind, str(t('battle.auto') if kind=='battle_auto' else t('workspace.task_'+kind)), str(stage), True)
    for key, name in (('battle_capture','capture.short'), ('battle_auto','battle.auto')):
        battle = status.get(key) or {}
        if battle.get('active') or battle.get('pending'):
            return TaskSummary(key, str(t(name)), str(battle.get('reason') or ''), True)
    if op.get('catch_context'):
        return TaskSummary('saved_search', str(t('capture.search_paused')), str(t('capture.paused_lifetime')), False)
    if auto.get('status')=='stopped':
        stage=auto.get('reason') or ''
        if auto.get('script')=='change_party.py':stage=str(t('party_edit.stopped_hint'))
        return TaskSummary('stopped',str(t('workspace.task_stopped')),str(stage),False)
    if auto.get('status')=='finished':
        return TaskSummary('finished', str(t('workspace.task_complete')), str(auto.get('reason') or ''), False)
    return TaskSummary('idle', str(t('workspace.current')), str(t('workspace.task_none')), False)


class TasksView:
    def __init__(self, panel, parent):
        self.panel=panel;self.m=panel.monitor;self.parent=parent;self.saved=None
        self.section=tk.StringVar(value='current')
        Segments(parent,[(key,t('workspace.'+key)) for key in ('current','results','history')],
                 self.section,self.select).pack(fill='x',pady=(0,12))
        self.pages={key:tk.Frame(parent,bg=BG) for key in ('current','results','history')}
        current=self.pages['current']
        self.title=label(current,'',17,bold=True)
        self.stage=label(current,'',12,BLUE,wraplength=440);self.stage.pack_configure(pady=(8,8))
        self.note=label(current,t('workspace.task_hint'),11,MUTED,wraplength=440)
        controls=tk.Frame(current,bg=BG);controls.pack(fill='x',pady=(10,16))
        self.context=Button(controls,t('workspace.open_context'),self.m.show_battle_panel);self.context.pack(side='left')
        self.stop=Button(controls,t('workspace.stop'),lambda:self.m.take_control(focus=False));self.stop.pack(side='right')
        for key,command in [('workspace.training_setup',panel.open_training),('workspace.catch_setup',panel.open_acquisition),('party_edit.title',panel.open_party_editor)]:
            Button(current,t(key),command,height=36,anchor='w',variant='ghost').pack(fill='x',pady=3)
        results=self.pages['results']
        label(results,t('workspace.results_hint'),11,MUTED,wraplength=440).pack_configure(pady=(0,8))
        self.results_host=tk.Frame(results,bg=BG);self.results_host.pack(fill='both',expand=True)
        self.log=tk.Text(self.pages['history'],height=22,wrap='word',bg=CARD,fg=TEXT,
                         relief='flat',font=('Helvetica',11),padx=10,pady=10,state='disabled')
        self.log.pack(fill='both',expand=True);self.log_signature=None
        parent.bind('<Destroy>',lambda e:self.close() if e.widget is parent else None,add='+')
        parent.bind('<Configure>',lambda e:[w.configure(wraplength=max(240,e.width-10)) for w in (self.stage,self.note)],add='+')
        self.select('current')
    def select(self,key):
        self.section.set(key)
        for k,page in self.pages.items():
            if k==key:page.pack(fill='both',expand=True)
            else:page.pack_forget()
        if key=='results' and self.saved is None:
            from .wild_history_ui import SavedEncountersView
            self.saved=SavedEncountersView(self.panel,self.results_host)
        self.refresh()
    def refresh(self):
        summary=task_summary(self.m);self.title.configure(text=summary.title)
        self.stage.configure(text=summary.stage,fg=AMBER if summary.attention else BLUE)
        self.stop.configure(state='normal' if summary.active else 'disabled')
        if self.section.get()=='history':
            lines=self.m.automation.logs;signature=(self.m.automation.log_revision,self.m.generation)
            if signature!=self.log_signature:
                self.log_signature=signature;self.log.configure(state='normal');self.log.delete('1.0','end')
                self.log.insert('1.0','\n'.join(lines));self.log.configure(state='disabled')
    def close(self):
        if self.saved:self.saved.close()


def show_section(panel, tab=None, *, detail_return=False):
    """Root navigation switches stacks; it never destroys another section's draft."""
    if tab is None:
        panel.window.deiconify();panel.window.lift();panel.refresh();return
    if tab=='overview':
        tab='collection'
        if panel.collection_view.current!='party':panel.collection_view.select('party')
    if tab=='automation':
        show_section(panel,'tasks');return panel.open_training()
    target='settings' if tab in ('settings','hotkeys','slots','journal','scripts') else tab
    if target not in ('collection','inventory','location','tasks','settings'):target='collection'
    current=panel.details.origin() if panel.details.active else panel.active_section
    destination=tab if target=='settings' else target
    if not detail_return:
        if current==destination and panel.details.active:
            panel.window.deiconify();panel.window.lift();return
        panel.details.park()
    panel.active_section=target
    if target=='settings':
        panel.tabs.pack_forget();panel.settings_shell.pack(fill='both',expand=True)
        panel.settings_tabs.select(panel.page_containers[tab])
        if tab=='slots':panel.refresh_slots()
    else:
        panel.settings_shell.pack_forget();panel.tabs.pack(fill='both',expand=True)
        panel.tabs.select(panel.page_containers[target])
    if not detail_return:panel.details.restore(destination)
    panel.window.deiconify();panel.window.lift();panel.refresh()
