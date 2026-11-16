from .entity_names import display_entity_names as _entity_label
"""One visual language for Pokémon types, moves and defensive matchups (Gen III)."""
import math
from . import localized_tk as tk
from .catalog import species,ability,effectiveness
from .tooltips import Tooltip
from .ui import BG,CARD,TEXT,MUTED

TYPE_INFO={0:('Нормальный','Норм.','#aab5c1'),1:('Боевой','Бой','#d48467'),2:('Летающий','Полёт','#a5b8ea'),3:('Ядовитый','Яд','#bf91d9'),4:('Земляной','Земля','#c9a874'),5:('Каменный','Камень','#bdb489'),6:('Насекомый','Жук','#b1c778'),7:('Призрачный','Призрак','#a294d0'),8:('Стальной','Сталь','#9bbcc7'),9:('Неизвестный','?','#aab5c1'),10:('Огненный','Огонь','#eea17d'),11:('Водный','Вода','#83b7e8'),12:('Травяной','Трава','#93c78c'),13:('Электрический','Электро','#ead27c'),14:('Психический','Психо','#df91b3'),15:('Ледяной','Лёд','#96d7d9'),16:('Драконий','Дракон','#9e9bdd'),17:('Тёмный','Тьма','#b6a6ad')}

def types_for(mon,root):
    ids=mon.get('types')
    if not ids or not all(isinstance(v,int) for v in ids):ids=species(mon['species_id'],root).get('type_ids',[])
    return list(dict.fromkeys(ids))

def defensive_profile(mon,root):
    types=types_for(mon,root);rule=ability(mon.get('ability_id',0),root).get('mechanics',{});result=dict(weak=[],resist=[],immune=[])
    for typ in TYPE_INFO:
        if typ==9:continue
        factor=effectiveness(typ,types,root)
        if typ==rule.get('immune_type') or rule.get('only_super_effective') and factor<=1:factor=0
        elif typ in rule.get('reduced_types',[]):factor*=rule.get('attack_multiplier',1)
        if factor>1:result['weak'].append((typ,factor))
        elif factor==0:result['immune'].append((typ,0))
        elif factor<1:result['resist'].append((typ,factor))
    result['weak'].sort(key=lambda p:(-p[1],p[0]));result['resist'].sort(key=lambda p:(p[1],p[0]));return result

def draw_type(c,x,y,typ,*,size=18,tags=()):
    """Small original vector pictograms; no resampling or alteration of sprites."""
    _,_,color=TYPE_INFO.get(typ,TYPE_INFO[9]);r=size/2;ink='#192830';scale=size/18
    c.create_oval(x-r,y-r,x+r,y+r,fill=color,outline='',tags=tags)
    def line(points,**kw):c.create_line(*sum(([x+a*scale,y+b*scale] for a,b in points),[]),fill=ink,width=max(1,1.45*scale),tags=tags,**kw)
    def poly(points):c.create_polygon(*sum(([x+a*scale,y+b*scale] for a,b in points),[]),fill=ink,outline='',tags=tags)
    if typ==13:poly([(1,-7),(-5,1),(-1,1),(-2,7),(5,-2),(1,-2)])
    elif typ in (11,3):
        poly([(0,-6),(-4,0),(-4,3),(-2,5),(2,5),(4,3),(4,0)])
        if typ==3:
            c.create_oval(x-2*scale,y,x+2*scale,y+3*scale,fill=color,outline='',tags=tags)
    elif typ==12:
        poly([(-5,4),(-5,-1),(0,-5),(6,-6),(5,1),(1,5)]);line([(-4,4),(3,-3)])
    elif typ==10:poly([(0,-7),(-1,-2),(-4,-4),(-5,2),(-3,6),(2,6),(5,2),(3,-3),(2,1)])
    elif typ==2:
        for offset in (-3,0,3):line([(-6,offset+2),(2,offset-3),(6,offset-3)])
    elif typ==15:
        for angle in (0,60,120):
            a=math.radians(angle);dx,dy=math.cos(a)*6,math.sin(a)*6;line([(-dx,-dy),(dx,dy)])
    elif typ==4:poly([(-7,5),(-1,-5),(2,0),(4,-2),(7,5)])
    elif typ==5:poly([(-5,-2),(0,-6),(5,-2),(4,5),(-3,5)])
    elif typ==8:
        poly([(0,-6),(5,-3),(5,3),(0,6),(-5,3),(-5,-3)]);c.create_oval(x-2*scale,y-2*scale,x+2*scale,y+2*scale,fill=color,outline='',tags=tags)
    elif typ==14:
        points=[]
        for i in range(30):
            a=i*.27;r2=1+i*.16;points.append((math.cos(a)*r2,math.sin(a)*r2))
        line(points)
    elif typ==6:
        c.create_oval(x-3*scale,y-5*scale,x+3*scale,y+5*scale,fill=ink,outline='',tags=tags)
        for yy in (-3,1,4):line([(-6,yy),(-2,yy-1)]);line([(2,yy-1),(6,yy)])
    elif typ==7:
        poly([(-5,6),(-5,-2),(-3,-5),(2,-5),(5,-2),(5,6),(2,4),(0,6),(-2,4)])
        for xx in (-2,2):c.create_oval(x+(xx-1)*scale,y-2*scale,x+(xx+1)*scale,y,fill=color,outline='',tags=tags)
    elif typ==17:
        c.create_oval(x-5*scale,y-5*scale,x+5*scale,y+5*scale,fill=ink,outline='',tags=tags);c.create_oval(x-1*scale,y-6*scale,x+7*scale,y+3*scale,fill=color,outline='',tags=tags)
    elif typ==1:poly([(-5,4),(-5,-2),(-3,-2),(-3,-5),(-1,-5),(-1,-3),(1,-6),(3,-5),(3,-2),(5,-2),(5,2),(2,6)])
    elif typ==16:poly([(-6,5),(-2,-1),(-3,-6),(2,-4),(6,-5),(3,-1),(5,2),(1,2),(-1,6)])
    else:
        c.create_oval(x-4*scale,y-4*scale,x+4*scale,y+4*scale,outline=ink,width=max(1,2*scale),tags=tags)

class Badges(tk.Canvas):
    def __init__(self,parent,*,labels=True):
        super().__init__(parent,height=26,bg=parent.cget('bg'),highlightthickness=0,bd=0,width=200);self.labels=labels;self.types=[];self.regions=[];self.hint=Tooltip(self,bind=False)
        self.bind('<Configure>',lambda _:self.draw());self.bind('<Motion>',self.motion);self.bind('<Leave>',self.hint.hide)
    def set(self,types):self.types=list(types);self.draw()
    def draw(self):
        if not self.winfo_exists():return
        self.delete('all');self.regions=[];x=10
        from tkinter import font
        f=font.Font(root=self,font=('Helvetica',10))
        for typ in self.types:
            name=TYPE_INFO.get(typ,TYPE_INFO[9])[0];draw_type(self,x,13,typ,size=18);width=22
            if self.labels:self.create_text(x+14,13,text=name,font=f,fill=TEXT,anchor='w');width+=f.measure(name)+14
            self.regions.append((x-10,x+width-10,typ));x+=width
    def motion(self,event):
        typ=next((t for a,b,t in self.regions if a<=event.x<=b),None)
        if typ is None:self.hint.hide()
        else:self.hint.enter(event,TYPE_INFO.get(typ,TYPE_INFO[9])[0]+' тип')

class Matchups(tk.Canvas):
    def __init__(self,parent,root):
        super().__init__(parent,height=1,bg=parent.cget('bg'),highlightthickness=0,bd=0,width=300);self.root_path=root;self.mon=None;self.hint=Tooltip(self,bind=False);self.regions=[]
        self.bind('<Configure>',lambda _:self.draw());self.bind('<Motion>',self.motion);self.bind('<Leave>',self.hint.hide)
    def set(self,mon):self.mon=mon;self.draw()
    def draw(self):
        if not self.winfo_exists():return
        self.delete('all');self.regions=[]
        if not self.mon:return
        profile=defensive_profile(self.mon,self.root_path);width=max(280,self.winfo_width());y=13
        for kind,title in [('weak','Слабости'),('resist','Сопротивл.'),('immune','Иммунитет')]:
            rows=profile[kind]
            if not rows:
                if kind=='weak':self.create_text(0,y,text=title,font=('Helvetica',10),fill=MUTED,anchor='w');self.create_text(84,y,text='Нет',font=('Helvetica',10),fill=TEXT,anchor='w');y+=27
                continue
            self.create_text(0,y,text=title,font=('Helvetica',10),fill=MUTED,anchor='w');x=84
            for typ,factor in rows:
                if x+48>width:x=84;y+=25
                draw_type(self,x+9,y,typ,size=18);self.create_text(x+23,y,text=f'×{factor:g}',font=('Helvetica',10),fill=TEXT,anchor='w');self.regions.append((x-2,y-11,x+50,y+11,typ,factor));x+=58
            y+=27
        height=max(25,y-4)
        if int(self.cget('height'))!=height:self.configure(height=height)
    def motion(self,event):
        row=next((r for r in self.regions if r[0]<=event.x<=r[2] and r[1]<=event.y<=r[3]),None)
        if row:
            _,_,_,_,typ,factor=row;name=TYPE_INFO[typ][0];a=ability((self.mon or {}).get('ability_id',0),self.root_path);self.hint.enter(event,f'{name} урон: ×{factor:g}'+('\nУчтена способность '+_entity_label(a['name']) if a else '')+'\nОбычные прямые атаки; особые эффекты могут действовать иначе.')
        else:self.hint.hide()
