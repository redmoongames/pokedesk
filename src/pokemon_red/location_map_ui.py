"""A read-only regional map; opening it never requests movement or a game tick."""
from . import localized_tk as tk
from .ui import BG,CARD,TEXT,MUTED,GREEN,BLUE,AMBER,label
from .region_map import atlas,topology,positions,section_label

class LocationMapView:
    def __init__(self,panel,parent,place,encounter=None):
        self.panel=panel;self.root=panel.monitor.folder;self.place=place;self.map_width=atlas(self.root)['width'];self.map_height=atlas(self.root)['height'];self.layers=atlas(self.root)['pages'][place['page']];self.cells={};self.hovered=None
        self.frame=tk.Frame(parent,bg=BG);self.frame.pack(fill='x')
        label(self.frame,place['title'],19,bold=True,wraplength=510)
        label(self.frame,'Карта · '+place['page_title'],11,BLUE).pack_configure(pady=(5,7))
        if encounter:
            label(self.frame,encounter['method_label']+' · '+str(encounter['probability'])+'% встреч · Lv '+encounter['level_label'],11,GREEN,wraplength=510).pack_configure(pady=(0,8))
        self.canvas=tk.Canvas(self.frame,bg='#102533',height=360,bd=0,highlightthickness=0);self.canvas.pack(fill='x',pady=(0,8))
        self.caption=label(self.frame,'',10,BLUE,wraplength=510);self.caption.pack_configure(pady=(0,5))
        label(self.frame,'● Город   ◆ Пещера / здание   ━ Маршрут   ◉ Выбранное место',9,MUTED,wraplength=510).pack_configure(pady=(0,6))
        self.context=label(self.frame,'Ориентиры: '+', '.join(place['nearby'])+'.',11,wraplength=510)
        note=place['note'] or 'Выделено положение локации на карте региона. Этажи и внутренние зоны имеют общую отметку.'
        if encounter and encounter.get('note'):note+='\n'+encounter['note']
        label(self.frame,note,10,MUTED,wraplength=510).pack_configure(pady=(6,8))
        self.canvas.bind('<Configure>',self.draw);self.canvas.bind('<Motion>',self.hover);self.canvas.bind('<Leave>',lambda _:self.show_caption(None));self.frame.bind('<Configure>',self.resize)
        self.show_caption(None)
    def resize(self,event):
        height=max(240,int((event.width-24)/self.map_width*self.map_height+26))
        if self.canvas.winfo_reqheight()!=height:self.canvas.configure(height=height)
        for child in self.frame.winfo_children():
            if isinstance(child,tk.Label):child.configure(wraplength=max(220,event.width-8))
    def show_caption(self,section):
        self.caption.configure(text=section_label(self.root,section) if section else 'Выбрано: '+self.place['title'])
    def hover(self,event):
        x=int((event.x-self.left)/self.scale);y=int((event.y-self.top)/self.scale)
        section=self.cells.get((x,y)) if event.x>=self.left and event.y>=self.top else None
        if section!=self.hovered:self.hovered=section;self.show_caption(section)
    def draw(self,_=None):
        c=self.canvas;c.delete('all');width=max(1,c.winfo_width());height=max(1,c.winfo_height());self.scale=s=min((width-24)/self.map_width,(height-26)/self.map_height);self.left=(width-self.map_width*s)/2;self.top=(height-self.map_height*s)/2
        def point(x,y):return self.left+(x+.5)*s,self.top+(y+.5)*s
        # Canonical Town Map grid, with land routes, towns and dungeon overlays.
        base=self.layers['map'];self.cells={};towns={m['region'] for m in topology(self.root).values() if m['map_type'] in ('MAP_TYPE_TOWN','MAP_TYPE_CITY')}
        for y,row in enumerate(base):
            for x,section in enumerate(row):
                if section=='MAPSEC_NONE':continue
                self.cells[x,y]=section;px,py=point(x,y)
                c.create_rectangle(px-s*.48,py-s*.48,px+s*.48,py+s*.48,fill='#193c43',outline='')
                for dx,dy in ((1,0),(0,1)):
                    if y+dy<self.map_height and x+dx<self.map_width and base[y+dy][x+dx]!='MAPSEC_NONE':
                        a,b=point(x+dx,y+dy);c.create_line(px,py,a,b,fill='#507d83',width=max(3,s*.24),capstyle='round')
                c.create_oval(px-2,py-2,px+2,py+2,fill='#507d83',outline='')
        for y,row in enumerate(self.layers['dungeon']):
            for x,section in enumerate(row):
                if section=='MAPSEC_NONE':continue
                self.cells[x,y]=section;px,py=point(x,y);r=max(3,s*.18)
                c.create_polygon(px,py-r,px+r,py,px,py+r,px-r,py,fill='#8caab8',outline='#102533')
        for section in sorted(towns):
            pts=positions(self.layers,section,'map')
            if not pts:continue
            x,y=pts[0];px,py=point(x,y);r=max(3,s*.2)
            c.create_oval(px-r,py-r,px+r,py+r,fill='#9cc6cf',outline='#102533',width=2)
            text=section_label(self.root,section);label_y=py+s*.6 if y<self.map_height-1 else py-s*.6
            c.create_text(px,label_y,text=text,font=('Helvetica',max(8,int(s*.37)),'bold'),fill='#b5cbd4',anchor='center')
        selected=set(self.place['points'])
        for x,y in selected:
            px,py=point(x,y)
            for dx,dy in ((1,0),(0,1)):
                if (x+dx,y+dy) in selected:
                    a,b=point(x+dx,y+dy);c.create_line(px,py,a,b,fill=AMBER,width=max(5,s*.3),capstyle='round',tags='destination')
            c.create_oval(px-4,py-4,px+4,py+4,fill=AMBER,outline='',tags='destination')
        # One ring at each distinct access point, preserving long highlighted routes.
        for x,y in selected:
            if len(selected)>2 and sum((x+dx,y+dy) in selected for dx,dy in ((1,0),(-1,0),(0,1),(0,-1)))>1:continue
            px,py=point(x,y);r=s*.43;c.create_oval(px-r,py-r,px+r,py+r,outline=AMBER,width=2,tags='destination')
        c.create_text(12,12,text=self.place['page_title'],anchor='nw',font=('Helvetica',10,'bold'),fill='#7897aa')
