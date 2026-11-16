"""Modeless session actions; save/close remains owned by the existing runtime."""
from . import localized_tk as tk
from .i18n import t
from .ui import BG,TEXT,MUTED,HOVER,GREEN,Button,label,rounded,theme
from .tooltips import Tooltip


class ExitButton(Button):
    def __init__(self,parent,command):
        super().__init__(parent,t('sessions.exit'),command,width=34,height=32,variant='ghost')
        Tooltip(self,t('sessions.exit'))
    def draw(self):
        if not self.winfo_exists():return
        self.delete('all');w=self.winfo_width();h=self.winfo_height();x,y=w/2,h/2
        fill=HOVER if self.hover else self.cget('bg')
        rounded(self,1,1,w-1,h-1,8,fill=fill,outline=GREEN if self.focus_get() is self else fill)
        ink=TEXT if self.enabled else MUTED
        self.create_line(x-1,y-9,x-10,y-9,x-10,y+9,x-1,y+9,fill=ink,width=1.5)
        self.create_line(x-3,y,x+10,y,fill=ink,width=1.5)
        self.create_line(x+5,y-5,x+10,y,x+5,y+5,fill=ink,width=1.5)


class Confirmation:
    """No nested mainloop or keyboard grab: emergency input remains available."""
    def __init__(self,parent,*,title,message,confirm,on_confirm,danger=False):
        self.closed=False;self.on_confirm=on_confirm
        self.window=tk.Toplevel(parent);self.window.title(title);self.window.configure(bg=BG)
        self.window.transient(parent.winfo_toplevel());self.window.resizable(False,False);theme(self.window)
        body=tk.Frame(self.window,bg=BG,padx=20,pady=18);body.pack(fill='both',expand=True)
        label(body,title,17,bold=True,wraplength=400).pack_configure(pady=(0,10))
        label(body,message,12,MUTED,wraplength=400)
        actions=tk.Frame(body,bg=BG);actions.pack(fill='x',pady=(18,0))
        self.cancel_button=Button(actions,t('sessions.cancel'),self.cancel);self.cancel_button.pack(side='left')
        self.confirm_button=Button(actions,confirm,self.accept,variant='danger' if danger else 'primary');self.confirm_button.pack(side='right',padx=(14,0))
        self.window.protocol('WM_DELETE_WINDOW',self.cancel);self.window.bind('<Escape>',self.cancel)
        self.window.update_idletasks()
        parent=parent.winfo_toplevel();x=parent.winfo_rootx()+max(0,(parent.winfo_width()-self.window.winfo_reqwidth())//2);y=parent.winfo_rooty()+70
        self.window.geometry(f'+{max(0,x)}+{max(0,y)}');self.cancel_button.focus_set()
    def cancel(self,_=None):
        if not self.closed:self.closed=True;self.window.destroy()
        return 'break'
    def accept(self):
        if self.closed:return
        self.cancel();self.on_confirm()


def confirm_return_to_menu(monitor,on_confirm):
    if monitor.closed or monitor.close_requested:return
    previous=getattr(monitor,'_exit_confirmation',None)
    if previous is not None and not previous.closed:
        previous.window.lift();return previous
    # Revoke the bot out of band before displaying any UI. Cancel leaves the
    # game paused under manual control; confirming delegates to the save barrier.
    monitor.take_control(focus=False);monitor.pause(save=False)
    parent=monitor.panel.window if monitor.panel else monitor.window
    dialog=Confirmation(parent,title=t('sessions.exit_question'),message=t('sessions.exit_message'),confirm=t('sessions.exit_confirm'),on_confirm=on_confirm)
    monitor._exit_confirmation=dialog
    return dialog


def profile_actions(home,row,anchor):
    previous=getattr(home,'action_menu',None)
    if previous is not None and previous.winfo_exists():previous.destroy()
    window=home.action_menu=tk.Toplevel(home.root);window.configure(bg=BG);window.title(t('sessions.actions'))
    window.transient(home.root);window.resizable(False,False);window.minsize(230,110)
    home.dialogs.append(window)
    body=tk.Frame(window,bg=BG,padx=10,pady=10);body.pack(fill='both',expand=True)
    actions=((t('design.rename'),lambda:home.rename(row),False),
             (t('sessions.duplicate'),lambda:home.duplicate(row),bool(row.get('busy'))),
             (t('sessions.delete'),lambda:home.delete(row),bool(row.get('busy'))))
    for caption,command,disabled in actions:
        def invoke(action=command):window.destroy();action()
        button=Button(body,caption,invoke,anchor='w');button.pack(fill='x');button.configure(state='disabled' if disabled else 'normal')
        if disabled:Tooltip(button,t('sessions.busy'))
    window.update_idletasks();window.geometry(f'+{max(0,anchor.winfo_rootx()+anchor.winfo_width()-window.winfo_reqwidth())}+{anchor.winfo_rooty()+anchor.winfo_height()}')
    window.bind('<Escape>',lambda _:(window.destroy(),'break')[1])
    # A normal modeless window stays keyboard-reachable on macOS; undecorated
    # popovers can lose activation before their first focus event is delivered.
    body.winfo_children()[0].focus_set()
