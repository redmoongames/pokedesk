"""One compact, responsive IV editor for starter, recovery and wild search."""
from . import localized_tk as tk
from .models import STAT_KEYS
from .i18n import t,literal
from .ui import CARD,MUTED,GREEN,Button,Stepper,label
from .tooltips import Tooltip

TITLES=('HP','ATK','DEF','SPEED','SP ATK','SP DEF')

class IVPreferences:
    def __init__(self,parent,*,minimums=(0,)*6,preferred=(),command=lambda:None,show_priorities=True,help_text=None,title=None):
        self.frame=tk.Frame(parent,bg=parent.cget('bg'));self.frame.pack(fill='x',pady=(8,4))
        label(self.frame,title or t('capture.ivs'),12,bold=True)
        self.grid=tk.Frame(self.frame,bg=parent.cget('bg'));self.grid.pack(fill='x',pady=(4,0))
        self.values={};self.stars={};self.cells=[];self.buttons={};self.traces=[];self.columns=None
        for key,title,minimum in zip(STAT_KEYS,TITLES,minimums):
            cell=tk.Frame(self.grid,bg=CARD,padx=6,pady=4);self.cells.append(cell)
            head=tk.Frame(cell,bg=CARD);head.pack(fill='x')
            label(head,literal(title),10,MUTED,pack=False).pack(side='left')
            star=tk.BooleanVar(value=key in preferred);self.stars[key]=star
            button=Button(head,'★' if star.get() else '☆',width=28,height=24,variant='ghost',fg=GREEN if star.get() else MUTED);self.buttons[key]=button
            button.configure(command=lambda v=star:v.set(not v.get()));button.pack(side='right') if show_priorities else None
            Tooltip(button,t('capture.star_help'))
            value=tk.IntVar(value=minimum);self.values[key]=value;Stepper(cell,value,0,31).pack(fill='x')
            def changed(*_,k=key):
                selected=self.stars[k].get();self.buttons[k].configure(text='★' if selected else '☆',fg=GREEN if selected else MUTED);command()
            for var in (value,star):self.traces.append((var,var.trace_add('write',changed)))
        Tooltip(self.frame,help_text or t('capture.iv_help'))
        self.grid.bind('<Configure>',lambda e:self.arrange(e.width));self.arrange(500)
        self.frame.bind('<Destroy>',self.destroyed,add='+')
    @property
    def preferred(self):return tuple(k for k in STAT_KEYS if self.stars[k].get())
    def arrange(self,width):
        columns=1 if width<300 else 2
        if columns==self.columns:return
        self.columns=columns
        for col in range(2):self.grid.columnconfigure(col,weight=int(col<columns),uniform='ivs' if col<columns else '')
        for i,cell in enumerate(self.cells):cell.grid(row=i//columns,column=i%columns,sticky='ew',padx=(0 if i%columns==0 else 4,0),pady=(0,4))
    def destroyed(self,event):
        if event.widget is self.frame:
            for var,token in self.traces:var.trace_remove('write',token)
            self.traces=[]
