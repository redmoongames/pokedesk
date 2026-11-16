"""Fractional macOS trackpad input and unobtrusive, temporary scroll indicators."""
import math
import tkinter as base_tk
from . import localized_tk as tk
from tkinter import ttk,font as tkfont

TAG='PokemonSmoothScroll'

def wheel_pixels(delta,precise=False):
    """Native trackpads report points; coarse wheel input reports notches/units."""
    if precise:return -float(delta)
    return -float(delta)*(36/120 if abs(delta)>=120 else 12)

class Motion:
    """Accumulate tiny gestures without losing their fraction or reversing at edges."""
    def __init__(self):self.target=None;self.position=0
    def add(self,pixels,current,maximum):
        if self.target is None:
            if abs(self.position-current)>1:self.position=current
            self.target=self.position
        if (self.target-self.position)*pixels<0:self.target=self.position
        self.target=max(0,min(maximum,self.target+pixels))
    def step(self):
        if self.target is None:return None
        difference=self.target-self.position
        if abs(difference)<.35:
            self.position=self.target;self.target=None
        else:self.position+=difference*.22
        return self.position

class Scrollbar(tk.Canvas):
    """Thin floating thumb: hidden when idle/full; draggable, without arrow chrome."""
    def __init__(self,parent,*,command,orient='vertical',**kw):
        kw.pop('style',None);super().__init__(parent,width=9,bg=parent.cget('bg'),bd=0,highlightthickness=0,takefocus=False,**kw)
        self.command=command;self.first=0;self.last=1;self.visible=False;self.hover=False;self.drag=None;self.hide_id=None
        self.bind('<Configure>',lambda _:self.draw());self.bind('<Enter>',self.enter);self.bind('<Leave>',self.leave);self.bind('<Button-1>',self.pressed);self.bind('<B1-Motion>',self.dragged);self.bind('<ButtonRelease-1>',self.released)
        self.bind('<Destroy>',self.destroyed,add='+')
    def destroyed(self,event):
        if event.widget is self and self.hide_id:
            try:self.after_cancel(self.hide_id)
            except tk.TclError:pass
            self.hide_id=None
    def set(self,first,last):
        first,last=float(first),float(last);changed=abs(first-self.first)>1e-6 or abs(last-self.last)>1e-6;self.first,self.last=first,last
        if changed and last-first<.999:self.flash()
        else:self.draw()
    def flash(self):
        if self.hide_id:self.after_cancel(self.hide_id)
        self.visible=True;self.draw();self.hide_id=self.after(750,self.hide)
    def hide(self):
        self.hide_id=None
        if not self.hover and self.drag is None:self.visible=False;self.draw()
    def enter(self,_):self.hover=True;self.flash()
    def leave(self,_):self.hover=False;self.flash()
    def bounds(self):
        h=max(1,self.winfo_height());height=min(h,max(26,(self.last-self.first)*h));top=self.first*max(1,h-height)/max(.001,1-(self.last-self.first))
        return top,min(h,top+height)
    def draw(self):
        if not self.winfo_exists():return
        self.delete('all')
        if self.last-self.first>=.999 or not(self.visible or self.hover or self.drag is not None):return
        top,bottom=self.bounds();width=5 if self.hover or self.drag is not None else 3;center=self.winfo_width()/2
        self.create_line(center,top+3,center,bottom-3,width=width,fill='#8393a3' if self.hover or self.drag is not None else '#475868',capstyle='round')
    def pressed(self,event):
        if self.last-self.first>=.999:return 'break'
        top,bottom=self.bounds();self.drag=(event.y-top) if top<=event.y<=bottom else (bottom-top)/2;self.dragged(event);return 'break'
    def dragged(self,event):
        if self.drag is None:return 'break'
        _,bottom=self.bounds();top,_=self.bounds();thumb=bottom-top;available=max(1,self.winfo_height()-thumb)
        fraction=max(0,min(1,(event.y-self.drag)/available))*(1-(self.last-self.first))
        target=getattr(self.command,'__self__',None)
        controller=getattr(target,'_smooth_controller',None)
        if controller:controller.cancel()
        self.command('moveto',fraction);self.flash();return 'break'
    def released(self,_):self.drag=None;self.flash();return 'break'

class Controller:
    def __init__(self,widget):
        self.widget=widget;self.motion=Motion();self.timer=None;self.remainder=0
        widget.bind('<Destroy>',self.destroyed,add='+')
    def destroyed(self,event):
        if event.widget is self.widget:self.cancel()
    def cancel(self):
        if self.timer:
            try:self.widget.after_cancel(self.timer)
            except tk.TclError:pass
        self.timer=None;self.motion=Motion();self.remainder=0
    def canvas_extent(self):
        w=self.widget;region=w.cget('scrollregion')
        if not region:return 0
        parts=[float(x) for x in w.tk.splitlist(region)];return max(0,parts[3]-parts[1])
    def extent(self):
        w=self.widget
        if getattr(w,'_pixel_scroll',False):return w.scroll_extent(),w.viewport_height()
        if isinstance(w,base_tk.Canvas):return self.canvas_extent(),w.winfo_height()
        if isinstance(w,base_tk.Text):
            total=w.count('1.0','end','ypixels')
            return max(1,total[0] if total else 1),max(1,w.winfo_height()-2*int(w.cget('pady')))
        return 0,0
    def scroll(self,pixels):
        w=self.widget;first,last=w.yview()
        if last-first>=.999:return False
        total,visible=self.extent()
        if total:
            current=w.offset if getattr(w,'_pixel_scroll',False) else first*total
            maximum=max(0,total-visible)
            if current<=.5 and pixels<0 or current>=maximum-.5 and pixels>0:
                self.cancel();return False
            self.motion.add(pixels,current,maximum)
            if not self.timer:self.animate()
        else:
            # Compatibility for third-party native controls, never used by app tables.
            height=26 if isinstance(w,ttk.Treeview) else 18
            self.remainder+=pixels;units=math.trunc(self.remainder/height)
            if units:w.yview_scroll(units,'units');self.remainder-=units*height
            if first<=0 and pixels<0 or last>=1 and pixels>0:self.remainder=0;return False
        return True
    def animate(self):
        self.timer=None;w=self.widget
        if not w.winfo_exists():return
        point=self.motion.step();total,_=self.extent()
        if point is not None and total:
            if getattr(w,'_pixel_scroll',False):w.scroll_to_pixel(point)
            else:w.yview_moveto(point/total)
        if self.motion.target is not None:self.timer=w.after(12,self.animate)

class Router:
    def __init__(self,root):
        self.root=root
        root.bind_class(TAG,'<MouseWheel>',self.wheel)
        root.bind_class(TAG,'<TouchpadScroll>',self.touchpad)
        root.bind_class(TAG,'<Button-4>',lambda e:self.wheel(e,button=4))
        root.bind_class(TAG,'<Button-5>',lambda e:self.wheel(e,button=5))
        root.bind_all('<Map>',self.mapped,add='+');self.attach_tree(root)
    def mapped(self,event):self.attach(event.widget)
    def attach(self,widget):
        try:
            tags=widget.bindtags()
            if TAG not in tags:widget.bindtags((TAG,*tags))
            if isinstance(widget,tk.Entry):
                widget.configure(bd=0,relief='flat',highlightthickness=1,highlightbackground='#182330',highlightcolor='#40566d')
            if isinstance(widget,(base_tk.Text,base_tk.Listbox)):
                widget.configure(bd=0,highlightthickness=0,relief='flat')
            if isinstance(widget,(base_tk.Text,base_tk.Listbox)) and not getattr(widget,'_display_selection',False) and not widget.cget('yscrollcommand'):
                indicator=Scrollbar(widget,command=widget.yview)
                indicator.place(relx=1,rely=0,relheight=1,width=9,anchor='ne')
                widget.configure(yscrollcommand=indicator.set);widget._scroll_indicator=indicator
        except (tk.TclError,AttributeError):pass
    def attach_tree(self,widget):
        self.attach(widget)
        for child in widget.winfo_children():self.attach_tree(child)
    def targets(self,widget):
        while widget is not None:
            if getattr(widget,'_display_selection',False):
                widget=getattr(widget,'master',None);continue
            if getattr(widget,'_pixel_scroll',False) or isinstance(widget,(ttk.Treeview,base_tk.Text,base_tk.Listbox)) or (isinstance(widget,base_tk.Canvas) and widget.cget('scrollregion')):yield widget
            widget=getattr(widget,'master',None)
    def touchpad(self,event):
        # Tk 9 emits TouchpadScroll, not MouseWheel, for two-finger gestures.
        dx,dy=self.root.tk.call('tk::PreciseScrollDeltas',event.delta)
        reader=getattr(self.root,'_scroll_delta_reader',None)
        if reader and not getattr(event,'send_event',False):
            native=reader()
            if native and native[2]:dx,dy=native[:2]
        if abs(dx)>abs(dy)*2:return 'break'
        return self.route(event.widget,-float(dy))
    def wheel(self,event,button=None):
        pixels=wheel_pixels(120 if button==4 else -120 if button==5 else event.delta)
        reader=getattr(self.root,'_scroll_delta_reader',None)
        if reader and button is None and getattr(event,'time',0) and not getattr(event,'send_event',False):
            native=reader()
            if native:
                dx,dy,precise=native
                if abs(dx)>abs(dy)*2:return 'break'
                pixels=wheel_pixels(dy,precise)
        return self.route(event.widget,pixels)
    def route(self,widget,pixels):
        if not pixels:return 'break'
        from .tooltips import dismiss_tooltips
        dismiss_tooltips()
        tried=set()
        for target in self.targets(widget):
            tried.add(target)
            controller=getattr(target,'_smooth_controller',None)
            if controller is None:controller=target._smooth_controller=Controller(target)
            if controller.scroll(pixels):return 'break'
        top=widget.winfo_toplevel();fallback=getattr(top,'_scroll_fallback',None)
        target=fallback() if fallback else self.default_target(top)
        if target is not None and target not in tried:
            controller=getattr(target,'_smooth_controller',None)
            if controller is None:controller=target._smooth_controller=Controller(target)
            if controller.scroll(pixels):return 'break'
        # No scroll target: leave ordinary game shortcuts and other input alone.
        return None
    def default_target(self,top):
        candidates=[]
        def collect(parent):
            for child in parent.winfo_children():
                if isinstance(child,base_tk.Toplevel) or not child.winfo_viewable() or getattr(child,'_display_selection',False):continue
                if getattr(child,'_pixel_scroll',False) or isinstance(child,(ttk.Treeview,base_tk.Text,base_tk.Listbox)) or (isinstance(child,base_tk.Canvas) and child.cget('scrollregion')):
                    first,last=child.yview()
                    if last-first<.999:candidates.append(child)
                collect(child)
        collect(top)
        return max(candidates,key=lambda w:w.winfo_width()*w.winfo_height(),default=None)

def install(master):
    root=master._root()
    if not hasattr(root,'_scroll_router'):root._scroll_router=Router(root)
    return root._scroll_router
