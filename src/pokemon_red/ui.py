"""Small desktop design system. Canvas controls never install keyboard grabs."""
from . import localized_tk as tk
import math
from .i18n import render,literal,subscribe,unsubscribe
from tkinter import ttk,font as tkfont
from .text_values import SelectableLabel

from .design_tokens import COLORS
BG=COLORS['canvas'];CARD=COLORS['surface'];HOVER=COLORS['raised'];BORDER=COLORS['border']
TEXT=COLORS['text'];MUTED=COLORS['secondary'];GREEN=COLORS['success'];BLUE=COLORS['selection_text'];AMBER=COLORS['warning'];RED=COLORS['danger']

def rounded(canvas,x1,y1,x2,y2,r=8,**kw):
    return canvas.create_polygon(x1+r,y1,x2-r,y1,x2,y1,x2,y1+r,x2,y2-r,x2,y2,x2-r,y2,x1+r,y2,x1,y2,x1,y2-r,x1,y1+r,x1,y1,smooth=True,**kw)

def short(text,width,font):
    text=render(text)
    if font.measure(text)<=width:return literal(text)
    while text and font.measure(text+'…')>width:text=text[:-1]
    return literal(text+'…')

def theme(master):
    from .scrolling import install
    install(master)
    style=ttk.Style(master)
    if style.theme_use()!='clam':style.theme_use('clam')
    top=master.winfo_toplevel();root=master._root()
    if top is not root and not top.cget('menu') and root.cget('menu'):top.configure(menu=root.cget('menu'))
    style.configure('Trainer.Treeview',background=CARD,fieldbackground=CARD,foreground=TEXT,rowheight=44,borderwidth=0,font=('Helvetica',11))
    style.map('Trainer.Treeview',background=[('selected',HOVER)],foreground=[('selected',TEXT)])
    style.configure('Trainer.Treeview.Heading',background=BG,foreground=MUTED,font=('Helvetica',10),relief='flat',padding=(8,8))
    style.configure('Sprite.Treeview',background=CARD,fieldbackground=CARD,foreground=TEXT,rowheight=68,borderwidth=0,font=('Helvetica',12))
    style.map('Sprite.Treeview',background=[('selected',HOVER)])
    style.configure('Sprite.Treeview.Heading',background=BG,foreground=MUTED,relief='flat',padding=(8,8))
    style.configure('Dark.Vertical.TScrollbar',background=BORDER,troughcolor=BG,borderwidth=0,arrowsize=10)
    return style

def label(parent,text='',size=12,color=TEXT,*,bold=False,pack=True,**kw):
    w=SelectableLabel(parent,text=text,bg=parent.cget('bg'),fg=color,font=('Helvetica',size,'bold' if bold else 'normal'),anchor='w',justify='left',**kw)
    if pack:w.pack(fill='x')
    return w

def card(parent,**kw):return tk.Frame(parent,bg=CARD,padx=14,pady=12,**kw)

class Button(tk.Canvas):
    def __init__(self,parent,text='',command=None,*,variant='secondary',width=None,height=36,anchor='center',font=None,**kw):
        self._auto_width=width is None
        self.text=text;self.command=command;self.variant=variant;self.enabled=True;self.hover=False;self.anchor=anchor
        self.ink=kw.pop('fg',None);kw.pop('takefocus',None)
        self.font=tkfont.Font(root=parent,font=font or ('Helvetica',12,'bold'))
        super().__init__(parent,width=width or self.font.measure(render(text))+28,height=height,bg=parent.cget('bg'),highlightthickness=0,bd=0,takefocus=True,cursor='hand2',**kw)
        self.bind('<Configure>',lambda _:self.draw());self.bind('<Enter>',lambda _:self.over(True));self.bind('<Leave>',lambda _:self.over(False))
        self.bind('<Button-1>',lambda _:self.invoke());self.bind('<Return>',self.keyboard_invoke);self.bind('<space>',self.keyboard_invoke)
        self.bind('<FocusIn>',lambda _:self.draw());self.bind('<FocusOut>',lambda _:self.draw())
        from .tooltips import Tooltip
        Tooltip(self,lambda:self.text if self.font.measure(render(self.text))>max(1,self.winfo_width()-24) else '')
    def locale_changed(self):
        if self.winfo_exists():
            if self._auto_width:super().configure(width=self.font.measure(render(self.text))+28)
            super().locale_changed()
    def keyboard_invoke(self,_):self.invoke();return 'break'
    def over(self,value):self.hover=value;self.draw()
    def invoke(self):
        if self.enabled and self.command:return self.command()
    def configure(self,cnf=None,**kw):
        if cnf:kw.update(cnf)
        if 'width' in kw:self._auto_width=False
        for name in ('text','command','variant','anchor'):
            if name in kw:setattr(self,name,kw.pop(name))
        if 'state' in kw:
            self.enabled=kw.pop('state')!='disabled';kw['takefocus']=self.enabled
        if 'fg' in kw:self.ink=kw.pop('fg')
        if kw:super().configure(**kw)
        self.draw()
    config=configure
    def cget(self,key):
        if key=='text':return self.text
        if key=='state':return 'normal' if self.enabled else 'disabled'
        return super().cget(key)
    def draw(self):
        if not self.winfo_exists():return
        self.delete('all');w=max(4,self.winfo_width());h=max(4,self.winfo_height())
        fill=COLORS['primary'] if self.variant=='primary' else '#3a272e' if self.variant=='danger' else HOVER if self.hover or self.variant=='selected' else CARD if self.variant!='ghost' else self.cget('bg')
        ink=COLORS['primary_text'] if self.variant=='primary' else RED if self.variant=='danger' else self.ink or TEXT
        if not self.enabled:fill=CARD;ink=MUTED
        rounded(self,1,1,w-1,h-1,8,fill=fill,outline=GREEN if self.focus_get() is self else BORDER if self.variant!='ghost' else fill,width=1)
        x=12 if self.anchor=='w' else w-12 if self.anchor=='e' else w/2
        self.create_text(x,h/2,text=self.text if len(render(self.text))==1 else short(self.text,w-24,self.font),font=self.font,fill=ink,anchor=self.anchor)

class IconButton(Button):
    """Icon-only controls have their own geometry; text truncation never applies."""
    def draw(self):
        if not self.winfo_exists():return
        self.delete('all');w=self.winfo_width();h=self.winfo_height();x,y=w/2,h/2
        fill=HOVER if self.hover or self.variant=='selected' else self.cget('bg')
        rounded(self,1,1,w-1,h-1,8,fill=fill,outline=GREEN if self.focus_get() is self else fill)
        points=[]
        for i in range(48):
            angle=i*math.tau/48;radius=11 if i%6 in (1,2,3,4) else 8.5
            points.extend((x+math.cos(angle)*radius,y+math.sin(angle)*radius))
        self.create_polygon(points,fill=TEXT if self.enabled else MUTED,outline='')
        self.create_oval(x-4,y-4,x+4,y+4,fill=fill,outline='')

class Tabs(tk.Frame):
    """Notebook-compatible navigation with custom buttons and no native tab chrome."""
    def __init__(self,parent,**kw):
        kw.pop('style',None);kw.pop('height',None);super().__init__(parent,bg=BG,**kw)
        self.nav=tk.Frame(self,bg=BG);self.nav.pack(fill='x',pady=(0,10))
        self.entries=[];self.current=None
    def add(self,child,*,text):
        button=Button(self.nav,text,lambda:self.select(child),height=36,variant='ghost');button.pack(side='left',fill='x',expand=True,padx=2)
        self.entries.append((child,text,button))
        child.bind('<Destroy>',lambda e,c=child:self.remove(c) if e.widget is c else None,add='+')
        if self.current is None:self.select(child)
    def remove(self,child):
        kept=[]
        for entry in self.entries:
            if entry[0] is child:
                if entry[2].winfo_exists():entry[2].destroy()
            else:kept.append(entry)
        self.entries=kept
        if self.current is child:self.current=None
    def select(self,child=None):
        if child is None:return str(self.current) if self.current is not None else ''
        target=next((c for i,(c,_,_) in enumerate(self.entries) if child in (c,str(c),i)),None)
        if target is None:return
        for c,_,b in self.entries:
            if c is target:c.pack(fill='both',expand=True)
            else:c.pack_forget()
            b.configure(variant='selected' if c is target else 'ghost',fg=TEXT if c is target else MUTED)
        self.current=target;self.event_generate('<<NotebookTabChanged>>')
    def tabs(self):return tuple(str(c) for c,_,_ in self.entries)
    def tab(self,child,option=None):
        value=next(text for c,text,_ in self.entries if child in (c,str(c)))
        return value if option=='text' else {'text':value}

class Meter(tk.Canvas):
    def __init__(self,parent,*,color=GREEN,height=5):
        super().__init__(parent,height=height,bg=parent.cget('bg'),highlightthickness=0,bd=0,takefocus=False);self.value=0;self.color=color
        self.bind('<Configure>',lambda _:self.draw())
    def set(self,value,color=None):
        self.value=max(0,min(1,value));self.color=color or self.color;self.draw()
    def draw(self):
        self.delete('all');w=self.winfo_width();h=self.winfo_height();rounded(self,0,0,w,h,2,fill=BORDER,outline='')
        if self.value:rounded(self,0,0,max(h,w*self.value),h,2,fill=self.color,outline='')
    def __setitem__(self,key,value):
        if key=='value':self.set(value/100)
        else:super().__setitem__(key,value)

class Toggle(tk.Canvas):
    def __init__(self,parent,text,variable,command=None,*,height=34):
        super().__init__(parent,height=height,bg=parent.cget('bg'),highlightthickness=0,bd=0,takefocus=True,cursor='hand2')
        self.text=text;self.variable=variable;self.command=command;self.enabled=True
        self.font=tkfont.Font(root=self,font=('Helvetica',12));self.trace=variable.trace_add('write',lambda *_:self.draw())
        self.bind('<Configure>',lambda _:self.draw());self.bind('<Button-1>',self.toggle);self.bind('<space>',self.toggle);self.bind('<Return>',self.toggle)
        self.bind('<Destroy>',lambda e:self.variable.trace_remove('write',self.trace) if e.widget is self else None)
        self.bind('<FocusIn>',lambda _:self.draw());self.bind('<FocusOut>',lambda _:self.draw())
    def configure(self,cnf=None,**kw):
        if cnf:kw.update(cnf)
        if 'state' in kw:self.enabled=kw['state']!='disabled';kw['takefocus']=self.enabled
        super().configure(**kw)
        if hasattr(self,'variable'):self.draw()
    config=configure
    def toggle(self,_=None):
        if self.enabled:
            self.variable.set(not self.variable.get())
            if self.command:self.command()
        return 'break'
    def draw(self):
        if not self.winfo_exists():return
        self.delete('all');w=self.winfo_width();h=self.winfo_height();on=bool(self.variable.get())
        if self.focus_get() is self:rounded(self,1,1,w-1,h-1,6,fill='',outline=GREEN,tags='focus')
        self.create_text(0,h/2,text=short(self.text,max(1,w-62),self.font),font=self.font,fill=TEXT if self.enabled else MUTED,anchor='w')
        rounded(self,w-44,h/2-10,w-2,h/2+10,10,fill=GREEN if on else BORDER,outline='')
        x=w-13 if on else w-33;self.create_oval(x-7,h/2-7,x+7,h/2+7,fill='#10251b' if on else MUTED,outline='')

class Stepper(tk.Frame):
    def __init__(self,parent,variable,low,high,*,step=1,width=136,suffix=''):
        super().__init__(parent,bg=parent.cget('bg'));self.variable=variable;self.low=low;self.high=high;self.step=step
        self.minus=Button(self,'−',lambda:self.change(-step),width=34);self.minus.pack(side='left')
        self.entry=tk.Entry(self,textvariable=variable,width=4,justify='center',bg=CARD,fg=TEXT,insertbackground=TEXT,bd=0,highlightthickness=1,highlightbackground=BORDER,highlightcolor=GREEN,font=('Helvetica',14,'bold'))
        self.entry.pack(side='left',fill='both',expand=True,padx=5,ipady=7)
        self.plus=Button(self,'+',lambda:self.change(step),width=34);self.plus.pack(side='left')
        self.entry.bind('<FocusOut>',self.commit);self.entry.bind('<Return>',self.commit)
    def value(self):
        try:return int(self.variable.get())
        except (ValueError,tk.TclError):return self.low
    def change(self,delta):self.variable.set(min(self.high,max(self.low,self.value()+delta)))
    def commit(self,_=None):self.variable.set(min(self.high,max(self.low,self.value())));return 'break'
    def configure(self,cnf=None,**kw):
        if 'state' in kw:
            state=kw.pop('state');self.minus.configure(state=state);self.plus.configure(state=state);self.entry.configure(state=state)
        if kw:super().configure(cnf,**kw)

class Segments(tk.Frame):
    def __init__(self,parent,items,variable,command=None):
        super().__init__(parent,bg=parent.cget('bg'));self.items=items;self.variable=variable;self.command=command;self.buttons=[]
        for i,(value,text) in enumerate(items):
            b=Button(self,text,lambda v=value:self.choose(v),height=32,width=48);b.pack(side='left',fill='x',expand=True,padx=(0 if i==0 else 4,0));self.buttons.append((value,b))
        self.trace=variable.trace_add('write',lambda *_:self.draw());self.draw()
        self.bind('<Destroy>',lambda e:variable.trace_remove('write',self.trace) if e.widget is self else None)
    def choose(self,value):
        self.variable.set(value)
        if self.command:self.command(value)
    def draw(self):
        for value,b in self.buttons:b.configure(variant='selected' if self.variable.get()==value else 'secondary',fg=GREEN if self.variable.get()==value else MUTED)

class Slider(tk.Canvas):
    def __init__(self,parent,variable,command=None,*,low=0,high=100):
        super().__init__(parent,height=30,bg=parent.cget('bg'),highlightthickness=0,bd=0,cursor='hand2',takefocus=True)
        self.variable=variable;self.command=command;self.low=low;self.high=high
        self.trace=variable.trace_add('write',lambda *_:self.draw());self.bind('<Configure>',lambda _:self.draw())
        self.bind('<Button-1>',self.drag);self.bind('<B1-Motion>',self.drag)
        self.bind('<Left>',lambda _:self.change(-1));self.bind('<Right>',lambda _:self.change(1))
        self.bind('<Destroy>',lambda e:variable.trace_remove('write',self.trace) if e.widget is self else None)
        self.bind('<FocusIn>',lambda _:self.draw());self.bind('<FocusOut>',lambda _:self.draw())
    def drag(self,event):self.set_value(self.low+(self.high-self.low)*max(0,min(1,(event.x-7)/max(1,self.winfo_width()-14))))
    def change(self,delta):self.set_value(float(self.variable.get())+delta);return 'break'
    def set_value(self,value):
        self.variable.set(max(self.low,min(self.high,round(value))))
        if self.command:self.command(str(self.variable.get()))
    def draw(self):
        if not self.winfo_exists():return
        self.delete('all');w=self.winfo_width()
        if self.focus_get() is self:rounded(self,1,1,w-1,29,6,fill='',outline=GREEN,tags='focus')
        p=(float(self.variable.get())-self.low)/max(1,self.high-self.low);x=7+max(0,min(1,p))*(w-14)
        rounded(self,7,12,w-7,18,3,fill=BORDER,outline='');rounded(self,7,12,max(8,x),18,3,fill=GREEN,outline='');self.create_oval(x-6,9,x+6,21,fill=TEXT,outline='')

class Collapse(tk.Frame):
    def __init__(self,parent,title,*,opened=False):
        super().__init__(parent,bg=parent.cget('bg'));self.title=title;self.opened=opened
        self.header=Button(self,literal(('⌄ ' if opened else '› ')+render(title)),self.toggle,variant='ghost',anchor='w',height=34);self.header.pack(fill='x')
        self.body=tk.Frame(self,bg=self.cget('bg'),pady=8)
        if opened:self.body.pack(fill='x')
        subscribe(self);self.bind('<Destroy>',lambda e:unsubscribe(self) if e.widget is self else None,add='+')
    def locale_changed(self):
        if self.winfo_exists():self.header.configure(text=literal(('⌄ ' if self.opened else '› ')+render(self.title)))
    def toggle(self):
        self.opened=not self.opened;self.locale_changed()
        if self.opened:self.body.pack(fill='x')
        else:self.body.pack_forget()

class Select(Button):
    """Compact custom popover. Losing focus closes it; no grab_set is used."""
    def __init__(self,parent,variable,values=(),command=None,**kw):
        self.variable=variable;self.values=list(values);self.on_change=command;self.popup=None;self.listing=None
        super().__init__(parent,self.caption(),self.open,anchor='w',**kw)
        self.trace=variable.trace_add('write',lambda *_:self.configure(text=self.caption()))
        self.bind('<Destroy>',self.cleanup,add='+')
    def caption(self):
        raw=self.variable.get();source=next((value for value in self.values if str(value)==str(raw)),raw)
        return literal(str(render(source))+'  ⌄')
    def locale_changed(self):
        if self.winfo_exists():self.configure(text=self.caption());super().locale_changed()
    def configure(self,cnf=None,**kw):
        if 'values' in kw:
            self.values=list(kw.pop('values'));kw.setdefault('text',self.caption())
        super().configure(cnf,**kw)
    def cleanup(self,event):
        if event.widget is self:
            self.dismiss();self.variable.trace_remove('write',self.trace)
    def dismiss(self,restore=False):
        popup,self.popup=self.popup,None;self.listing=None
        if popup is not None and popup.winfo_exists():popup.destroy()
        owner=getattr(self,'popup_owner',None)
        if owner is not None and owner.winfo_exists():
            for event,token in getattr(self,'popup_bindings',[]):owner.unbind(event,token)
        self.popup_bindings=[]
        if restore and self.winfo_exists():self.focus_set()
    def choose(self,value):
        self.variable.set(value);self.dismiss(restore=True)
        if self.on_change:self.on_change(value)
    def open(self):
        if self.popup is not None:self.dismiss(restore=True);return
        if not self.values:return
        owner=self.popup_owner=self.winfo_toplevel();self.popup=tk.Frame(owner,bg=BORDER,padx=1,pady=1);p=self.popup
        width=min(max(220,self.winfo_width()),max(100,owner.winfo_width()-16));x=max(8,min(self.winfo_rootx()-owner.winfo_rootx(),owner.winfo_width()-width-8))
        y=self.winfo_rooty()-owner.winfo_rooty()+self.winfo_height()+4;below=max(80,owner.winfo_height()-y-8);above=max(0,self.winfo_rooty()-owner.winfo_rooty()-8)
        height=min(360,len(self.values)*30+4,max(below,above) if below<120 else below)
        if below<120 and above>below:y=self.winfo_rooty()-owner.winfo_rooty()-height-4
        p.place(x=x,y=y,width=width,height=height);p.lift()
        from .table import ChoiceList
        listing=ChoiceList(p,bg=CARD,fg=TEXT,selectbackground=HOVER,selectforeground=GREEN,bd=0,highlightthickness=0,font=('Helvetica',12),activestyle='none',exportselection=False)
        self.listing=listing
        listing.pack(fill='both',expand=True)
        for value in self.values:listing.insert('end',value)
        if self.variable.get() in self.values:
            index=self.values.index(self.variable.get());listing.selection_set(index);listing.activate(index);listing.see(index)
        def picked(_=None):
            if listing.curselection():self.choose(self.values[listing.curselection()[0]])
            return 'break'
        def outside(event):
            if event.widget is self:return
            if self.popup is not None and not str(event.widget).startswith(str(self.popup)):self.dismiss()
        def cancel(_):self.dismiss(restore=True);return 'break'
        listing.bind('<ButtonRelease-1>',picked);listing.bind('<Return>',picked)
        p.bind('<Escape>',cancel);listing.bind('<Escape>',cancel)
        self.popup_bindings=[('<Button-1>',owner.bind('<Button-1>',outside,add='+')),('<FocusOut>',owner.bind('<FocusOut>',lambda _:self.after_idle(self.check_focus),add='+'))]
        listing.focus_set()
    def check_focus(self):
        if self.popup is None:return
        focused=self.popup.focus_get()
        if focused is None or not str(focused).startswith(str(self.popup)):self.dismiss()


def cached_font(master,font):
    """Named fonts are shared within their Tk interpreter, never across threads."""
    owner=master._root();cache=getattr(owner,'_pokemon_fonts',None)
    if cache is None:cache={};owner._pokemon_fonts=cache
    key=tuple(font)
    if key not in cache:cache[key]=tkfont.Font(root=owner,font=font)
    return cache[key]
