"""Stat priorities become an explicit OR-list of accepted nature IDs."""
from .models import STAT_KEYS
from .natures import nature_effect
from .i18n import t,literal
from .entity_names import nature_name
from .tooltips import Tooltip
from . import localized_tk as tk
from .ui import MUTED,GREEN,AMBER,Button,Select,Toggle,label

STATS=STAT_KEYS[1:]
PRESETS={'any':(), 'special':(5,10,15,20), 'physical':(3,8,13,23)}
ROLES=('prefer','protect','any','dump')

def accepted(roles):
    if set(roles)!=set(STATS) or any(v not in ROLES for v in roles.values()):raise ValueError(t('odds.invalid_preferences'))
    preferred={k for k,v in roles.items() if v=='prefer'};protected={k for k,v in roles.items() if v in ('prefer','protect')}
    result=[]
    for n in range(25):
        effects=nature_effect(n)['modifiers']
        if any(effects.get(k,0)<0 for k in protected):continue
        if preferred and not any(effects.get(k,0)>0 for k in preferred):continue
        result.append(n)
    return tuple(result)

def description(n):
    effects=nature_effect(n)['modifiers']
    if not effects:return t('nature_filter.neutral',name=nature_name(n))
    boost=next(k for k,v in effects.items() if v>0);drop=next(k for k,v in effects.items() if v<0)
    return t('nature_filter.effect',name=nature_name(n),boost=t('nature_filter.stat_'+boost),drop=t('nature_filter.stat_'+drop))

class Option(str):
    def __new__(cls,text,identifier):
        obj=super().__new__(cls,str(text));obj.identifier=identifier;return obj

class NatureFilter:
    def __init__(self,parent,*,initial=(),command=lambda:None,compact=False):
        self.compact=compact;self.command=command;self.frame=tk.Frame(parent,bg=parent.cget('bg'));self.frame.pack(fill='x',pady=(8,4))
        self.expanded=False;self.mode='exact' if initial else 'any';self.mode_text=tk.StringVar(value=t('nature_filter.'+self.mode))
        label(self.frame,t('capture.nature') if compact else t('nature_filter.title'),12,bold=True)
        modes=[Option(t('nature_filter.'+k),k) for k in ('any','special','physical','custom','exact')]
        Select(self.frame,self.mode_text,modes,lambda value:self.change_mode(value.identifier)).pack(fill='x',pady=(3,4))
        self.custom=tk.Frame(self.frame,bg=parent.cget('bg'));self.roles={};self.role_text={}
        for key in STATS:
            row=tk.Frame(self.custom,bg=parent.cget('bg'));row.pack(fill='x',pady=2)
            label(row,t('nature_filter.stat_'+key),10,MUTED,pack=False).pack(side='left')
            role='dump' if key=='attack' else 'prefer';self.roles[key]=role;var=tk.StringVar(value=t('nature_filter.role_'+role));self.role_text[key]=var
            Select(row,var,[Option(t('nature_filter.role_'+v),v) for v in ROLES],lambda value,k=key:self.change_role(k,value.identifier),width=210,height=29).pack(side='right')
        self.exact=tk.Frame(self.frame,bg=parent.cget('bg'));self.toggles=[];self.checked={};self.traces=[]
        actions=tk.Frame(self.exact,bg=parent.cget('bg'));actions.grid(row=0,column=0,columnspan=3,sticky='w')
        Button(actions,t('nature_filter.select_all'),lambda:self.check_all(True),variant='ghost').pack(side='left')
        Button(actions,t('nature_filter.clear'),lambda:self.check_all(False),variant='ghost').pack(side='left',padx=6)
        for n in range(25):
            var=tk.BooleanVar(value=n in initial if initial else True);self.checked[n]=var
            toggle=Toggle(self.exact,nature_name(n),var,self.changed,height=28);Tooltip(toggle,description(n));self.toggles.append(toggle);toggle.grid(row=1+n//3,column=n%3,sticky='ew',padx=2);self.exact.columnconfigure(n%3,weight=1)
        def arrange(event):
            columns=1 if event.width<330 else 2 if event.width<480 else 3
            actions.grid_configure(columnspan=columns)
            for col in range(3):self.exact.columnconfigure(col,weight=int(col<columns))
            for i,toggle in enumerate(self.toggles):toggle.grid_configure(row=1+i//columns,column=i%columns)
        self.exact.bind('<Configure>',arrange)
        self.edit_exact=Button(self.frame,t('nature_filter.edit_exact'),self.expand_exact,variant='ghost',height=28)
        self.names=label(self.frame,'',10,GREEN,wraplength=620);self.help=label(self.frame,t('nature_filter.help'),10,MUTED,wraplength=620)
        self.frame.bind('<Configure>',lambda e:[widget.configure(wraplength=max(180,e.width-8)) for widget in (self.names,self.help)])
        if compact:self.help.pack_forget()
        Tooltip(self.names,lambda:getattr(self,'full_names',''))
        self.refresh()
    @property
    def selected(self):
        if self.mode in PRESETS:return PRESETS[self.mode]
        result=accepted(self.roles) if self.mode=='custom' else tuple(n for n,v in self.checked.items() if v.get())
        if not result:raise ValueError(t('odds.no_natures'))
        return result
    def expand_exact(self):self.expanded=True;self.refresh()
    def change_mode(self,mode):
        if mode=='exact':self.expanded=True
        if mode=='exact' and self.mode!='exact':
            try:previous=self.selected or tuple(range(25))
            except ValueError:previous=()
            for n,var in self.checked.items():var.set(n in previous)
        self.mode=mode;self.mode_text.set(t('nature_filter.'+mode));self.changed()
    def check_all(self,value):
        for var in self.checked.values():var.set(value)
        self.changed()
    def change_role(self,key,role):self.roles[key]=role;self.role_text[key].set(t('nature_filter.role_'+role));self.changed()
    def changed(self):self.refresh();self.command()
    def refresh(self):
        self.custom.pack_forget();self.exact.pack_forget();self.edit_exact.pack_forget()
        if self.mode=='custom':self.custom.pack(fill='x',before=self.names)
        if self.mode=='exact':
            if self.expanded:self.exact.pack(fill='x',before=self.names)
            else:self.edit_exact.pack(fill='x',before=self.names)
        try:
            values=self.selected
            names='; '.join(str(description(n)) for n in values)
            self.full_names=names
            self.names.configure(text=t('capture.nature_count',count=len(values)) if self.compact and values and len(values)<25 else t('nature_filter.accepted',count=len(values),names=names) if values and len(values)<25 else t('nature_filter.all'),fg=GREEN)
        except ValueError as error:self.names.configure(text=str(error),fg=AMBER)
