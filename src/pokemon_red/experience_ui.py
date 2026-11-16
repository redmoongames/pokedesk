"""Exact level costs with an interactive native chart and a useful target budget."""
from . import localized_tk as tk
from .catalog import catalog
from .ui import BG,CARD,BORDER,TEXT,MUTED,GREEN,BLUE,AMBER,Button,Stepper,Segments,label,card
from .move_details_ui import ArticleBody

GROWTH_NAMES=['Средний быстрый','Неравномерный','Колеблющийся','Средний медленный','Быстрый','Медленный']


def number(value):return f'{int(value):,}'.replace(',',' ')


def level_budget(curve,start,target,experience=None):
    if not 1<=start<=100 or not 1<=target<=100:raise ValueError('Уровень должен быть от 1 до 100')
    if target<start:raise ValueError('Целевой уровень ниже начального')
    current=curve[start] if experience is None else int(experience)
    upper=curve[start+1]-1 if start<100 else curve[100]
    if not curve[start]<=current<=upper:raise ValueError('Опыт не соответствует начальному уровню')
    return dict(current=current,total=curve[target],remaining=max(0,curve[target]-current),next_level=0 if start==100 else curve[start+1]-current,costs=[curve[lv+1]-curve[lv] for lv in range(1,100)])


class ExperienceChart(tk.Canvas):
    def __init__(self,parent,curve,readout):
        super().__init__(parent,bg=CARD,bd=0,highlightthickness=0,height=190,width=420)
        self.curve=curve;self.readout=readout;self.start=1;self.target=50;self.hover=None;self.full=False;self.error=None
        self.costs=[curve[lv+1]-curve[lv] for lv in range(1,100)]
        self.bind('<Configure>',lambda _:self.draw());self.bind('<Motion>',self.motion);self.bind('<Leave>',self.leave)
    def set(self,start,target):
        if (start,target)!=(self.start,self.target):self.hover=None
        self.start=start;self.target=target;self.error=None;self.draw()
    def scope(self,value):self.full=value=='all';self.hover=None;self.draw()
    def bounds(self):
        if self.full:return 1,99
        first=min(self.start,98);last=min(99,max(first+1,self.target-1));return first,last
    def peak(self):
        first,last=self.bounds();return max(self.costs[first-1:last])
    def coords_for(self,lv):
        width=max(260,self.winfo_width());height=max(150,self.winfo_height());top=14;bottom=height-32
        first,last=self.bounds()
        return (58+(lv-first)/max(1,last-first)*(width-74),bottom-self.costs[lv-1]/self.peak()*(bottom-top))
    def draw(self):
        if not self.winfo_exists():return
        self.delete('all');width=max(260,self.winfo_width());height=max(150,self.winfo_height());bottom=height-32;top=14;max_cost=self.peak()
        if self.error:
            self.create_text(width/2,height/2,text=self.error,fill=MUTED,width=width-40,font=('Helvetica',12));return
        if self.start==100:
            self.create_text(width/2,height/2,text='Lv 100 · максимальный уровень',fill=MUTED,font=('Helvetica',13));return
        first,last=self.bounds()
        left,_=self.coords_for(min(self.start,99));right,_=self.coords_for(min(max(self.target-1,self.start),99))
        if self.target>self.start:self.create_rectangle(left,top,right,bottom,fill='#203849',outline='')
        for fraction in (0,.5,1):
            y=bottom-(bottom-top)*fraction;value=round(max_cost*fraction)
            self.create_line(58,y,width-16,y,fill=BORDER);self.create_text(49,y,text=number(value),anchor='e',fill=MUTED,font=('Helvetica',9))
        ticks=(1,20,40,60,80,99) if self.full else sorted({round(first+(last-first)*p/4) for p in range(5)})
        for lv in ticks:
            x,_=self.coords_for(lv);self.create_text(x,bottom+15,text=str(lv),fill=MUTED,font=('Helvetica',9))
        points=[coordinate for lv in range(first,last+1) for coordinate in self.coords_for(lv)]
        self.create_line(*points,fill=GREEN,width=2)
        for lv,color in ((min(self.start,99),BLUE),(min(self.target-1,99),AMBER)):
            x,y=self.coords_for(max(1,lv));self.create_oval(x-4,y-4,x+4,y+4,fill=color,outline=CARD)
        if self.hover is not None:
            x,y=self.coords_for(self.hover);self.create_line(x,top,x,bottom,fill=MUTED,dash=(3,3));self.create_oval(x-4,y-4,x+4,y+4,fill=TEXT,outline=CARD)
    def motion(self,event):
        if self.start==100 or self.error:return
        width=max(260,self.winfo_width());first,last=self.bounds();lv=max(first,min(last,round(first+(event.x-58)/max(1,width-74)*(last-first))))
        self.hover=lv;self.readout.configure(text=f'Lv {lv} → {lv+1}: {number(self.costs[lv-1])} XP за полный уровень');self.draw()
    def leave(self,_):self.hover=None;self.draw()


class ExperienceView:
    def __init__(self,parent,panel,sp,context):
        self.parent=parent;self.panel=panel;self.context=context;self.curve=catalog(panel.monitor.folder)['growth'][sp['growth']];self.signature=None;self.timer=None
        mon=context() or {};start=max(1,min(100,mon.get('level',5)));self.start=tk.IntVar(parent,value=start);self.target=tk.IntVar(parent,value=min(100,start+10))
        article=ArticleBody(parent);body=article.body
        label(body,'Сколько опыта нужно до цели',15,bold=True)
        article.text(body,'Группа роста: '+GROWTH_NAMES[sp['growth']]+'. Пороги XP взяты из FireRed.',10,MUTED).pack_configure(pady=(5,12))
        controls=tk.Frame(body,bg=BG);controls.pack(fill='x',pady=(0,10));controls.columnconfigure((0,1),weight=1,uniform='levels')
        for i,(title,var) in enumerate([('С уровня',self.start),('До уровня',self.target)]):
            box=tk.Frame(controls,bg=BG);box.grid(row=0,column=i,sticky='ew',padx=(0,16) if i==0 else (0,0));label(box,title,10,MUTED);Stepper(box,var,1,100).pack(fill='x',pady=(5,0))
        result=card(body);result.pack(fill='x',pady=(0,12));self.amount=label(result,'',22,BLUE,bold=True);self.detail=article.text(result,'',11,MUTED,margin=36)
        head=tk.Frame(body,bg=BG);head.pack(fill='x');label(head,'XP на следующий уровень',12,bold=True,pack=False).pack(side='left')
        self.scope=tk.StringVar(parent,value='range');switch=Segments(head,[('range','До цели'),('all','Вся шкала')],self.scope,lambda value:self.chart.scope(value));switch.pack(side='right')
        for _,button in switch.buttons:button.configure(width=100)
        self.readout=label(body,'Наведи на график, чтобы увидеть точную стоимость уровня',10,MUTED);self.readout.pack_configure(pady=(4,6))
        self.chart=ExperienceChart(body,self.curve,self.readout);self.chart.pack(fill='x')
        article.text(body,'По горизонтали — текущий уровень, по вертикали — XP для перехода на следующий. Выбранный диапазон выделен; на Lv 100 рост заканчивается.',10,MUTED).pack_configure(pady=(8,10))
        Button(body,'XP за победу над этим видом ↗',lambda:__import__('pokemon_red.reference_ui',fromlist=['show_xp_calculator']).show_xp_calculator(panel,sp['id'],min(100,self.start.get())),variant='ghost').pack(anchor='w')
        self.traces=[(var,var.trace_add('write',lambda *_:self.refresh())) for var in (self.start,self.target)]
        parent.bind('<Destroy>',self.destroyed,add='+');self.refresh();self.tick()
    def refresh(self):
        try:start=int(self.start.get());target=int(self.target.get())
        except (ValueError,tk.TclError):return
        mon=self.context() or {};own=mon.get('experience') if mon.get('level')==start else None
        try:budget=level_budget(self.curve,start,target,own)
        except ValueError as e:
            self.amount.configure(text=str(e),fg=AMBER,font=('Helvetica',13,'bold'));self.detail.configure(text='Укажи уровень от 1 до 100 и цель не ниже начального.');self.chart.error='Укажи корректные уровни для графика';self.chart.draw();return
        self.amount.configure(text=number(budget['remaining'])+' XP до цели',fg=BLUE,font=('Helvetica',22,'bold'))
        detail=f"Порог Lv {target}: {number(budget['total'])} XP"
        if own is not None:detail+=' · учтён текущий опыт Pokémon'
        else:detail+=' · расчёт от начала Lv '+str(start)
        if start<100:detail+='\nДо следующего уровня: '+number(budget['next_level'])+' XP'
        else:detail+='\nLv 100 — максимальный уровень'
        self.detail.configure(text=detail);self.chart.set(start,target)
    def tick(self):
        if not self.parent.winfo_exists():return
        mon=self.context() or {};signature=(mon.get('uid'),mon.get('level'),mon.get('experience'))
        if signature!=self.signature:
            try:following=self.signature and self.start.get()==self.signature[1]
            except (ValueError,tk.TclError):following=False
            if following and mon.get('level'):self.start.set(mon['level'])
            self.signature=signature;self.refresh()
        self.timer=self.parent.after(500,self.tick)
    def destroyed(self,event):
        if event.widget is not self.parent:return
        if self.timer:self.parent.after_cancel(self.timer);self.timer=None
        for variable,trace in self.traces:variable.trace_remove('write',trace)
