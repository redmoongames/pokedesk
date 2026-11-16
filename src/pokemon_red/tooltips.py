"""Pointer and keyboard help; no focus grabs, engine calls or nested waits."""
from . import localized_tk as tk
import weakref

_HINTS = weakref.WeakSet()


def dismiss_tooltips():
    for hint in tuple(_HINTS):
        hint.hide()


class Tooltip:
    def __init__(self, widget, text='', *, bind=True):
        old = getattr(widget, '_tooltip', None)
        if old is not None:
            old.hide()
        widget._tooltip = self
        self.widget=widget;self.text=text;self.window=None;self.timer=None;self.position=None
        _HINTS.add(self)
        if bind:
            widget.bind('<Enter>',self.enter,add='+')
            widget.bind('<Leave>',self.hide,add='+')
            widget.bind('<ButtonPress>',self.hide,add='+')
            widget.bind('<FocusIn>',self.focused,add='+')
            widget.bind('<FocusOut>',self.hide,add='+')
            widget.bind('<Unmap>',self.hide,add='+')
        widget.bind('<Destroy>',self.destroyed,add='+')

    def value(self):
        return str(self.text() if callable(self.text) else self.text or '')

    def focused(self, _=None):
        self.position=None
        self.enter()

    def destroyed(self,event):
        if event.widget is self.widget:self.hide()

    def enter(self,event=None,text=None):
        if getattr(self.widget,'_tooltip',None) is not self:return
        if text is not None and text!=self.text:self.hide();self.text=text
        if event:self.position=(event.x_root+12,event.y_root+18)
        if self.value() and not self.timer and not self.window:self.timer=self.widget.after(350,self.show)

    def show(self):
        self.timer=None
        if not self.widget.winfo_exists() or getattr(self.widget,'_tooltip',None) is not self:return
        text=self.value()
        if not text:return
        w=self.window=tk.Toplevel(self.widget);w.overrideredirect(True);w.configure(bg='#42464d',padx=1,pady=1)
        tk.Label(w,text=text,bg='#24272c',fg='#f1f2f4',font=('Helvetica',12),justify='left',padx=11,pady=8,wraplength=340).pack()
        w.update_idletasks();x,y=self.position or (self.widget.winfo_rootx(),self.widget.winfo_rooty()+self.widget.winfo_height()+5)
        x=max(5,min(x,w.winfo_screenwidth()-w.winfo_reqwidth()-8));y=max(5,min(y,w.winfo_screenheight()-w.winfo_reqheight()-25));w.geometry(f'+{x}+{y}')

    def hide(self,_=None):
        if self.timer:
            try:self.widget.after_cancel(self.timer)
            except tk.TclError:pass
            self.timer=None
        if self.window:
            try:self.window.destroy()
            except tk.TclError:pass
            self.window=None
