from .i18n import t
"""Modeless, demand-created automation tools, independent of the party dashboard."""
from . import localized_tk as tk
from types import SimpleNamespace
from .editions import edition
from .ui import BG,MUTED,AMBER,Button,label,theme
from .scrolling import Scrollbar

class AutomationWindows:
    def __init__(self,panel):self.panel=panel;self.monitor=panel.monitor;self.tools={}
    def _create(self,kind):
        window=tk.Toplevel(self.panel.window);window.title(edition(self.monitor.folder).name+' · '+('Автопрокачка' if kind=='training' else 'Автоловля'));window.configure(bg=BG);window.geometry('600x810');window.minsize(540,500);theme(window)
        window.bind('<FocusOut>',self.monitor.focus_out);window.bind('<Escape>',self.monitor.emergency_stop)
        canvas=tk.Canvas(window,bg=BG,highlightthickness=0,yscrollincrement=1);scroll=Scrollbar(window,command=canvas.yview);canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right',fill='y');canvas.pack(side='left',fill='both',expand=True)
        body=tk.Frame(canvas,bg=BG,padx=18,pady=14);item=canvas.create_window(0,0,anchor='nw',window=body)
        body.bind('<Configure>',lambda _:canvas.configure(scrollregion=canvas.bbox('all')));canvas.bind('<Configure>',lambda e:canvas.itemconfigure(item,width=e.width));window._scroll_fallback=lambda:canvas
        proxy=SimpleNamespace(monitor=self.monitor,window=window,inspect_uid=self.panel.inspect_uid)
        if kind=='training':
            from .training_view import TrainingSetup
            view=TrainingSetup(proxy,body,dock=window)
        else:
            from .acquisition_view import AcquisitionView
            view=AcquisitionView(proxy,body,window);view.actions.pack(side='bottom',fill='x',before=canvas)
        controls=tk.Frame(view.actions,bg=BG);controls.pack(fill='x',pady=(7,0))
        Button(controls,'Взять управление · F9',self.monitor.take_control,variant='primary').pack(side='left',fill='x',expand=True)
        Button(controls,'Пауза / продолжить',self.monitor.toggle_pause).pack(side='right',padx=(8,0))
        reason=label(view.actions,'',11,AMBER,wraplength=530);reason.pack_configure(pady=(5,0))
        tool=dict(window=window,view=view,reason=reason,controls=controls);self.tools[kind]=tool
        window.protocol('WM_DELETE_WINDOW',lambda:self.hide(kind))
        return tool
    def open_training(self,uid=None):return self.panel.details.open_training(uid)
    def open_acquisition(self):
        return self.panel.collection_view.open_acquisition()
    def hide(self,kind):
        tool=self.tools[kind]
        if tool.get('embedded'):
            if self.panel.details.active and self.panel.details.history.routes[-1].kind=='training':self.panel.details.back()
            else:tool['view'].suspend()
            return
        tool['window'].withdraw()
        if kind=='training':tool['view'].suspend()
    def refresh(self):
        for kind,tool in list(self.tools.items()):
            if not tool['window'].winfo_exists():self.tools.pop(kind,None);continue
            if not tool['window'].winfo_viewable():continue
            if tool.get('embedded'):continue
            if kind=='training':tool['view'].refresh(self.monitor.last_state)
            else:tool['view'].refresh()
            info=self.monitor.automation.info()
            active=bool(info.get('running') or getattr(self.monitor,'pending_start',False) or info.get('status') in ('attention','error'))
            if active and not tool['controls'].winfo_manager():tool['controls'].pack(fill='x',pady=(7,0))
            elif not active:tool['controls'].pack_forget()
            tool['reason'].configure(text='' if kind=='training' else info.get('reason','') if info.get('status') in ('attention','error') else '')
    def close(self):
        for tool in self.tools.values():tool['view'].close()
        collection=getattr(self.panel,'collection_view',None)
        if collection and collection.acquisition:collection.acquisition.close()
