
from .paths import installation_root
from .entity_names import pokemon_name
from .i18n import literal
from .ui import cached_font
"""Offline FireRed/LeafGreen 64px sprites, cached per Tk interpreter."""
from . import localized_tk as tk
from .catalog import species

def sprite(master,root,number,*,scale=1,shiny=False,gray=False):
    national=species(number,root).get('national_id')
    if national is None:return None
    owner=master._root();cache=getattr(owner,'_pokemon_sprites',{});owner._pokemon_sprites=cache
    key=(str(root),national,scale,bool(shiny),bool(gray))
    if key not in cache:
        if gray:
            info=species(number,root)
            original=installation_root(root)/info.get('shiny_sprite_path' if shiny else 'sprite_path',f"assets/pokemon/{'shiny/' if shiny else ''}{national}.png")
            prepared=original.parent/'gray'/original.name
            if prepared.exists():
                result=tk.PhotoImage(master=owner,file=str(prepared))
                if scale>1:result=result.zoom(int(scale))
                elif scale<1:result=result.subsample(round(1/scale))
                cache[key]=result;return result
            # Backward-compatible fallback for old portable asset folders.
            base=sprite(master,root,number,shiny=shiny)
            if base is None:return None
            gray_key=(str(root),national,1,bool(shiny),True)
            if gray_key not in cache:
                shaded=base.copy()
                for y in range(base.height()):
                    for x in range(base.width()):
                        if base.transparency_get(x,y):continue
                        r,g,b=base.get(x,y);v=(299*r+587*g+114*b+500)//1000;shaded.put(f'#{v:02x}{v:02x}{v:02x}',(x,y))
                cache[gray_key]=shaded
            result=cache[gray_key]
            if scale>1:result=result.zoom(int(scale))
            elif scale<1:result=result.subsample(round(1/scale))
            cache[key]=result;owner._pokemon_sprites=cache
            return result
        info=species(number,root)
        path=installation_root(root)/info.get('shiny_sprite_path' if shiny else 'sprite_path',f"assets/pokemon/{'shiny/' if shiny else ''}{national}.png")
        if not path.exists():return None
        image=tk.PhotoImage(master=owner,file=str(path))
        if scale>1:image=image.zoom(int(scale))
        elif scale<1:image=image.subsample(round(1/scale))
        cache[key]=image;owner._pokemon_sprites=cache
    return cache[key]

class PokemonCard(tk.Canvas):
    def __init__(self,parent,root,command=None,*,compact=False):
        super().__init__(parent,height=88 if compact else 110,width=240,bg=parent.cget('bg'),highlightthickness=0,bd=0,cursor='hand2',takefocus=True)
        from .tooltips import Tooltip
        self.root_path=root;self.command=command;self.mon=None;self.role=None;self.compact=compact;self.hover=False;self.region=None;self.type_regions=[];self.hint=Tooltip(self,bind=False)
        self.bind('<Configure>',lambda _:self.draw());self.bind('<Enter>',lambda _:self.over(True));self.bind('<Leave>',self.leave);self.bind('<Motion>',self.motion)
        self.bind('<Button-1>',self.clicked);self.bind('<Return>',lambda _:self.invoke());self.bind('<space>',lambda _:self.invoke())
        self.bind('<FocusIn>',lambda _:(self.draw(),self.hint.focused()));self.bind('<FocusOut>',lambda _:(self.draw(),self.hint.hide()))
    def invoke(self):
        if self.mon and self.command:self.command()
        return 'break'
    def clicked(self,event):
        from .statuses import show_status
        self.hint.hide()
        if self.hit(event.x,event.y)=='status' and self.mon:show_status(self,self.mon,self.root_path)
        else:self.invoke()
        return 'break'
    def hit(self,x,y):
        from .statuses import status_info
        if not self.mon:return None
        if status_info(self.mon,self.root_path) and (x-58)**2+(y-15)**2<=12**2:return 'status'
        for typ,x1,x2,cy in self.type_regions:
            if x1<=x<=x2 and abs(y-cy)<=10:return ('type',typ)
        if self.mon.get('shiny') and (x-58)**2+(y-40)**2<=11**2:return 'shiny'
        if 76<=x<=self.winfo_width()-12:
            if 36<=y<=52:return 'hp'
            if 60<=y<=76:return 'xp'
        return None
    def motion(self,event):
        from .statuses import status_info
        region=self.hit(event.x,event.y)
        if region!=self.region:self.region=region;self.hint.hide();self.draw()
        if not self.mon:return
        m=self.mon;text=''
        if region=='hp':text=f"Здоровье: {m['hp']} из {m['max_hp']} HP"
        elif region=='xp':text=f"До Lv {min(100,m['level']+1)}: {m.get('exp_to_next_level',0)} XP\nВсего опыта: {m.get('experience',0)} XP" if m['level']<100 else 'Достигнут максимальный уровень 100'
        elif region=='shiny':text='✦ Shiny Pokémon'
        elif region=='status':text=status_info(m,self.root_path)['name']+' · нажми для подробностей'
        elif isinstance(region,tuple) and region[0]=='type':
            from .types_ui import TYPE_INFO
            text=TYPE_INFO[region[1]][0]+' тип'
        if text:self.hint.enter(event,text)
    def leave(self,_):self.hover=False;self.region=None;self.hint.hide();self.draw()
    def over(self,value):self.hover=value;self.draw()
    def set(self,mon,role=None):
        signature=repr(([mon.get(k) for k in ('uid','species_id','nickname','species','level','hp','max_hp','experience','exp_to_next_level','status_code','status','types','type_ids','shiny')],role)) if mon else None
        self.mon=mon;self.role=role
        if signature==getattr(self,'_signature',object()):return
        self._signature=signature;self.draw()
    def draw(self):
        if not self.winfo_exists():return
        from .ui import rounded,short,CARD,HOVER,BORDER,TEXT,MUTED,GREEN,AMBER,RED,BLUE
        from .catalog import catalog,species
        from .statuses import status_info
        from tkinter import font as tkfont
        self.delete('all');self.type_regions=[];w=self.winfo_width();h=self.winfo_height();rounded(self,1,1,w-1,h-1,10,fill=HOVER if self.hover else CARD,outline=TEXT if self.focus_get() is self else GREEN if self.role=='trainee' else BLUE if self.role=='fighter' else BORDER,width=1)
        if not self.mon:return
        m=self.mon;self.photo=sprite(self,self.root_path,m['species_id'],shiny=m.get('shiny',False),gray=m['hp']<=0)
        if self.photo:self.create_image(35,34,image=self.photo)
        from .types_ui import draw_type,types_for
        from tkinter import font as tkfont
        types=types_for(m,self.root_path)
        if self.compact:
            for i,typ in enumerate(types):
                cx=35 if len(types)==1 else 23+i*24;draw_type(self,cx,72,typ,size=18,tags='type');self.type_regions.append((typ,cx-10,cx+10,72))
        else:
            from .types_ui import TYPE_INFO
            x=20
            for typ in types:
                draw_type(self,x,94,typ,size=16,tags='type');text=TYPE_INFO.get(typ,TYPE_INFO[9])[1];self.create_text(x+12,94,text=text,font=('Helvetica',9),fill=TEXT,anchor='w',tags='type');end=x+28+cached_font(self,('Helvetica',9)).measure(text);self.type_regions.append((typ,x-9,end-8,94));x=end
        if m.get('shiny'):
            self.create_oval(47,29,69,51,fill=CARD,outline=AMBER);self.create_text(58,40,text='✦',fill=AMBER,font=('Helvetica',12,'bold'))
        font=cached_font(self,('Helvetica',12,'bold'));self.create_text(76,18,text=short(pokemon_name(m),max(20,w-131),font),font=font,fill=TEXT,anchor='w');self.create_text(w-12,18,text=f"Lv {m['level']}",font=('Helvetica',10),fill=MUTED,anchor='e')
        fraction=max(0,min(1,m['hp']/max(1,m['max_hp'])));health_color='#376b52' if fraction>.5 else '#806237' if fraction>.2 else '#7a444a'
        self.meter(76,36,w-12,52,fraction,health_color,f"{m['hp']} / {m['max_hp']} HP",self.region=='hp')
        info=species(m['species_id'],self.root_path);level=m['level'];curve=catalog(self.root_path)['growth'][info['growth']] if info else [0]*101;xp=m.get('experience',curve[level] if 1<=level<=100 else 0)
        xp_fraction=1 if level>=100 else max(0,min(1,(xp-curve[level])/max(1,curve[level+1]-curve[level]))) if 1<=level<100 else 0
        self.meter(76,60,w-12,76,xp_fraction,'#385b82',f"до Lv {level+1} · {m.get('exp_to_next_level',0)} XP" if level<100 else 'Максимальный уровень',self.region=='xp')
        status=status_info(m,self.root_path)
        if status:
            self.create_oval(47,4,69,26,fill=CARD,outline=status['color'],width=1.5,tags='status');self.create_text(58,15,text=status['glyph'],fill=status['color'],font=('Helvetica',11,'bold'),tags='status')
    def meter(self,x1,y1,x2,y2,value,color,text,active):
        from .ui import rounded,short,TEXT
        from tkinter import font as tkfont
        rounded(self,x1,y1,x2,y2,4,fill='#213141',outline='')
        if value:rounded(self,x1,y1,x1+max(3,(x2-x1)*value),y2,4,fill=color,outline='')
        font=cached_font(self,('Helvetica',10,'bold' if active else 'normal'));self.create_text((x1+x2)/2,(y1+y2)/2,text=short(text,x2-x1-8,font),font=font,fill=TEXT)
