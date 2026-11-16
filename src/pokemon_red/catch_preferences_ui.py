"""Six compact priority rows; nature selection follows the same domain model."""
from . import localized_tk as tk
from .ui import MUTED,GREEN,Segments,Select,Stepper,label
from .models import STAT_KEYS
from .catch_preferences import normalize_preferences,accepted_natures,WEIGHTS
from .nature_preferences import description,Option
from .tooltips import Tooltip
from .i18n import t,format_number

class CatchPreferences:
    def __init__(self,parent,*,initial=None,command=lambda:None):
        initial=normalize_preferences(initial or ('neutral',)*6);self.values={};self.controls={};self.command=command
        self.frame=tk.Frame(parent,bg=parent.cget('bg'));self.frame.pack(fill='x',pady=(8,4))
        label(self.frame,t('capture.stat_preferences'),12,bold=True)
        for key,role in zip(STAT_KEYS,initial):
            row=tk.Frame(self.frame,bg=parent.cget('bg'));row.pack(fill='x',pady=2)
            label(row,t('nature_filter.stat_'+key),10,MUTED,pack=False).pack(side='left')
            var=tk.StringVar(value=role);self.values[key]=var
            control=Segments(row,[('positive','↑'),('neutral','—'),('negative','↓')],var,lambda _:self.changed());control.pack(side='right');self.controls[key]=control
            for value,button in control.buttons:Tooltip(button,t('capture.hp_stat_help',weight=format_number(WEIGHTS[value],decimals=int(WEIGHTS[value]%1!=0))) if key=='hp' else t('capture.stat_'+value))
        self.natures=label(self.frame,'',10,GREEN,wraplength=380);self.hint=Tooltip(self.natures,'')
        Tooltip(self.frame,t('capture.stat_preferences_help'));self.frame.bind('<Configure>',lambda e:self.natures.configure(wraplength=max(180,e.width-8)),add='+');self.refresh()
    @property
    def preferences(self):return {k:v.get() for k,v in self.values.items()}
    def refresh(self):
        choices=accepted_natures(self.preferences);self.natures.configure(text=t('capture.auto_natures',count=len(choices)));self.hint.text='\n'.join(map(str,(description(n) for n in choices)))
    def changed(self):self.refresh();self.command()

class SearchTime:
    PRESETS=(10,30,60,120,300)
    def __init__(self,parent,variable):
        self.variable=variable;self.frame=tk.Frame(parent,bg=parent.cget('bg'));self.frame.pack(fill='x',pady=(6,4))
        label(self.frame,t('capture.search_time'),12,bold=True)
        values=[Option(t('capture.time_seconds',seconds=n) if n<60 else t('capture.time_minutes',minutes=n//60),n) for n in self.PRESETS]
        self.custom_option=Option(t('capture.time_custom'),None);values.append(self.custom_option)
        selected=next((v for v in values if v.identifier==variable.get()),self.custom_option);self.caption=tk.StringVar(value=selected)
        self.picker=Select(self.frame,self.caption,values,self.choose);self.picker.pack(fill='x',pady=(3,0));Tooltip(self.picker,t('capture.search_time_help'))
        self.custom=tk.Frame(self.frame,bg=parent.cget('bg'));Stepper(self.custom,variable,1,86400).pack(fill='x',pady=4)
        if selected is self.custom_option:self.custom.pack(fill='x')
    def choose(self,value):
        if value.identifier is None:self.custom.pack(fill='x')
        else:self.custom.pack_forget();self.variable.set(value.identifier)
