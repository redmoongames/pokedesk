"""Selectable display values without permanently allocating hundreds of Texts.

A Label keeps its existing geometry. Dragging creates one read-only text surface;
selection freezes that surface until focus leaves, so telemetry cannot erase it.
"""
from . import localized_tk as tk
import tkinter as native_tk
from .i18n import t


def copy_text(widget, text):
    widget.clipboard_clear()
    widget.clipboard_append(str(text))
    return 'break'


def copy_menu(widget, event, entries):
    """Modeless context actions: no grab or nested wait can block F9."""
    root = widget._root()
    previous = getattr(root, '_copy_popup', None)
    if previous is not None and previous.winfo_exists():
        previous.destroy()
    popup = root._copy_popup = tk.Toplevel(widget)
    popup.overrideredirect(True)
    popup.configure(bg=widget.cget('bg'))
    from .ui import Button
    for caption, text in entries:
        def choose(value=text):
            copy_text(widget, value)
            popup.destroy()
        Button(popup, caption, choose, anchor='w').pack(fill='x')
    popup.update_idletasks()
    x = max(0, min(event.x_root, popup.winfo_screenwidth()-popup.winfo_reqwidth()))
    y = max(0, min(event.y_root, popup.winfo_screenheight()-popup.winfo_reqheight()))
    popup.geometry(f'+{x}+{y}')
    def lost(_=None):
        def check():
            if popup.winfo_exists():
                focus = popup.focus_get()
                if focus is None or focus.winfo_toplevel() is not popup:
                    popup.destroy()
        popup.after_idle(check)
    popup.bind('<FocusOut>', lost)
    popup.bind('<Escape>', lambda _: popup.destroy())
    popup.winfo_children()[0].focus_set()
    return 'break'


class SelectableLabel(tk.Label):
    """Label-compatible display text with drag/word selection and context copy."""
    def __init__(self, parent, **options):
        options.setdefault('cursor', 'xterm')
        super().__init__(parent, **options)
        self.editor = None
        self.press_at = None
        self._close_id=None;self._destroying=False
        self.bind('<ButtonPress-1>', self.pressed, add='+')
        self.bind('<B1-Motion>', self.dragged, add='+')
        self.bind('<Double-Button-1>', self.word, add='+')
        self.bind('<Button-3>', self.context, add='+')
        self.bind('<Control-Button-1>', self.context, add='+')
        self.bind('<Destroy>',self.destroyed,add='+')

    def destroyed(self,event):
        if event.widget is not self:return
        self._destroying=True
        if self._close_id:self.after_cancel(self._close_id);self._close_id=None
        if self.editor is not None and self.editor.winfo_exists():self.editor.destroy()

    def schedule_close(self,_=None):
        if not self._destroying and not self._close_id:self._close_id=self.after_idle(self.close_surface)

    def pressed(self, event):
        self.press_at = (event.x, event.y)

    def surface(self):
        if self.editor is not None and self.editor.winfo_exists():
            return self.editor
        from .tooltips import dismiss_tooltips
        dismiss_tooltips()
        self.editor = text = native_tk.Text(self.master, wrap='word', state='normal',
            font=self.cget('font'), bg=self.cget('bg'), fg=self.cget('fg'),
            bd=0, highlightthickness=0, cursor='xterm', takefocus=True,
            padx=self.cget('padx'), pady=self.cget('pady'), exportselection=False)
        text._display_selection = True
        text.insert('1.0', str(self.cget('text')))
        anchor=str(self.cget('anchor'))
        justify='right' if 'e' in anchor else 'left' if 'w' in anchor else 'center'
        text.tag_configure('value', justify=justify)
        text.tag_add('value', '1.0', 'end')
        text.configure(state='disabled')
        text.place(in_=self,x=0, y=0, relwidth=1, relheight=1)
        text.lift()
        text.update_idletasks()
        text.bind('<FocusOut>',self.schedule_close)
        text.bind('<Button-3>', self.context)
        text.bind('<Control-Button-1>', self.context)
        return text

    def close_surface(self):
        self._close_id=None
        text = self.editor
        if text is not None and text.winfo_exists() and text.focus_get() is not text:
            text.destroy()
            self.editor = None

    def dragged(self, event):
        if self.press_at is None:
            return
        x, y = self.press_at
        if abs(x-event.x)+abs(y-event.y) < 4:
            return
        text = self.surface()
        first, last = sorted((text.index(f'@{x},{y}'), text.index(f'@{event.x},{event.y}')),
                             key=lambda index: tuple(map(int, index.split('.'))))
        text.tag_remove('sel', '1.0', 'end')
        text.tag_add('sel', first, last)
        text.mark_set('insert', last)
        text.focus_set()
        return 'break'

    def word(self, event):
        text = self.surface()
        index = f'@{event.x},{event.y}'
        text.tag_add('sel', index+' wordstart', index+' wordend')
        text.focus_set()
        return 'break'

    def context(self, event):
        text = self.editor
        selected = ''
        if text is not None and text.winfo_exists() and text.tag_ranges('sel'):
            selected = text.get('sel.first', 'sel.last')
        return copy_menu(self, event, [(t('design.copy_selection') if selected else t('design.copy'),
                                       selected or str(self.cget('text')))])
