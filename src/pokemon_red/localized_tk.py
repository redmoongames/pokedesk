"""Explicit Tk presentation adapters for legacy screens, never a global patch.

Widget values, selections and commands retain their original identity. Only
visible text is translated, so switching languages cannot change game actions.
Entries are deliberately the original Tk classes: typed text is not translated.
"""
from tkinter import *  # re-export the standard Tk interface for existing views
import tkinter as _tk
from tkinter import messagebox as _messagebox, simpledialog as _simpledialog, filedialog as _filedialog
from .i18n import render, subscribe, unsubscribe


class _TextOptions:
    def __init__(self, master=None, cnf=None, **kw):
        options = dict(cnf or {}, **kw)
        self._source_text = options.get('text', '')
        self._requested_wrap=int(options.get('wraplength',0) or 0)
        self._source_variable = None
        self._variable_trace = None
        if 'textvariable' in options and isinstance(options['textvariable'], _tk.Variable):
            self._source_variable = options['textvariable']
            self._display_variable = _tk.StringVar(master, value=render(self._source_variable.get()))
            options['textvariable'] = self._display_variable
            self._variable_trace = self._source_variable.trace_add('write', self._translate_variable)
        if 'text' in options:
            options['text'] = render(options['text'])
        super().__init__(master, **options)
        subscribe(self)
        self.bind('<Destroy>', self._localization_destroyed, add='+')
        if isinstance(self,_tk.Label):self.bind('<Configure>',self._fit_wrap,add='+')

    def _fit_wrap(self,_=None):
        if self._requested_wrap and self.winfo_width()>1:
            available=max(40,self.winfo_width()-2*int(self.cget('padx') or 0)-4)
            target=min(self._requested_wrap,available)
            if int(self.cget('wraplength') or 0)!=target:super().configure(wraplength=target)

    def _translate_variable(self, *_):
        self._display_variable.set(render(self._source_variable.get()))

    def _localization_destroyed(self, event):
        if event.widget is self:unsubscribe(self)
        if event.widget is self and self._variable_trace:
            self._source_variable.trace_remove('write', self._variable_trace)
            self._variable_trace = None

    def configure(self, cnf=None, **kw):
        if isinstance(cnf, str):
            return super().configure(cnf, **kw)
        if cnf:
            kw.update(cnf)
        if 'wraplength' in kw:self._requested_wrap=int(kw['wraplength'] or 0)
        if 'text' in kw:
            self._source_text = kw['text']
            kw['text'] = render(kw['text'])
        return super().configure(**kw)

    config = configure

    def locale_changed(self):
        if self.winfo_exists():
            super().configure(text=render(self._source_text))
            if self._source_variable is not None:
                self._translate_variable()


class Label(_TextOptions, _tk.Label):
    pass


class Button(_TextOptions, _tk.Button):
    pass


class Checkbutton(_TextOptions, _tk.Checkbutton):
    pass


class LabelFrame(_TextOptions, _tk.LabelFrame):
    pass


class Canvas(_tk.Canvas):
    def __init__(self, *args, **kw):
        self._source_items = {}
        super().__init__(*args, **kw)
        subscribe(self)
        self.bind('<Destroy>',lambda e:unsubscribe(self) if e.widget is self else None,add='+')

    def create_text(self, *args, **kw):
        text = kw.get('text', '')
        if 'text' in kw:
            kw['text'] = render(text)
        item = super().create_text(*args, **kw)
        if text:
            self._source_items[item] = text
        return item

    def itemconfigure(self, tagOrId, cnf=None, **kw):
        if isinstance(cnf, str):
            return super().itemconfigure(tagOrId, cnf, **kw)
        if cnf:
            kw.update(cnf)
        if 'text' in kw:
            for item in self.find_withtag(tagOrId):
                self._source_items[item] = kw['text']
            kw['text'] = render(kw['text'])
        return super().itemconfigure(tagOrId, **kw)

    itemconfig = itemconfigure

    def delete(self, *tags):
        for tag in tags:
            for item in self.find_withtag(tag):
                self._source_items.pop(item, None)
        return super().delete(*tags)

    def locale_changed(self):
        if not self.winfo_exists():
            return
        for item, text in list(self._source_items.items()):
            super().itemconfigure(item, text=render(text))
        # Canvas design-system controls keep the original source in their model.
        draw = getattr(self, 'draw', None)
        if draw is not None:
            import inspect
            if all(p.default is not p.empty or p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD) for p in inspect.signature(draw).parameters.values()):
                draw()


class _WindowTitle:
    def title(self, string=None):
        if string is None:
            return super().title()
        self._source_title = string
        if not getattr(self,'_locale_title_bound',False):
            self.bind('<Destroy>',lambda e:unsubscribe(self) if e.widget is self else None,add='+')
            self._locale_title_bound=True
        subscribe(self)
        return super().title(render(string))

    wm_title = title

    def locale_changed(self):
        if self.winfo_exists() and hasattr(self, '_source_title'):
            super().title(render(self._source_title))


class Tk(_WindowTitle, _tk.Tk):
    pass


class Toplevel(_WindowTitle, _tk.Toplevel):
    def __init__(self,master=None,cnf=None,**kw):
        options=dict(cnf or {},**kw)
        if master is not None and 'menu' not in options:
            menu=master.winfo_toplevel().cget('menu')
            if menu:options['menu']=menu
        super().__init__(master,**options)


class Menu(_tk.Menu):
    def __init__(self, *args, **kw):
        self._source_labels = {}
        super().__init__(*args, **kw)
        subscribe(self)
        self.bind('<Destroy>',lambda e:unsubscribe(self) if e.widget is self else None,add='+')

    def add(self, itemType, cnf=None, **kw):
        if cnf:
            kw.update(cnf)
        source = kw.get('label')
        if source is not None:
            kw['label'] = render(source)
        result = super().add(itemType, **kw)
        if source is not None:
            self._source_labels[self.index('end')] = source
        return result

    def insert(self,index,itemType,cnf=None,**kw):
        if cnf:kw.update(cnf)
        at=self.index(index);source=kw.get('label')
        self._source_labels={key+(key>=at):value for key,value in self._source_labels.items()}
        if source is not None:kw['label']=render(source)
        result=super().insert(index,itemType,**kw)
        if source is not None:self._source_labels[at]=source
        return result

    def entryconfigure(self,index,cnf=None,**kw):
        if isinstance(cnf,str):return super().entryconfigure(index,cnf,**kw)
        if cnf:kw.update(cnf)
        if 'label' in kw:
            self._source_labels[self.index(index)]=kw['label'];kw['label']=render(kw['label'])
        return super().entryconfigure(index,**kw)

    entryconfig=entryconfigure

    def source_label(self,index):
        return self._source_labels.get(self.index(index),self.entrycget(index,'label'))

    def locale_changed(self):
        if self.winfo_exists():
            for index, text in self._source_labels.items():
                super().entryconfigure(index, label=render(text))


class Text(_tk.Text):
    def __init__(self,*args,**kw):
        self._source_chunks=[]
        super().__init__(*args,**kw);subscribe(self)
        self.bind('<Destroy>',lambda e:unsubscribe(self) if e.widget is self else None,add='+')

    def insert(self,index,chars,*tags):
        chunk=(chars,tags)
        if str(index)=='1.0':self._source_chunks.insert(0,chunk)
        elif str(index) in ('end','end-1c'):self._source_chunks.append(chunk)
        else:self._source_chunks=[]
        return super().insert(index,render(chars),*tags)

    def delete(self,index1,index2=None):
        # Unsupported partial edits invalidate the retained presentation model.
        # A user-edited Text must never be reconstructed from an old snapshot.
        self._source_chunks=[]
        return super().delete(index1,index2)

    def locale_changed(self):
        if not self.winfo_exists() or str(self.cget('state'))!='disabled' or not self._source_chunks:return
        scroll=self.yview()[0];selection=self.tag_ranges('sel')
        super().configure(state='normal');super().delete('1.0','end')
        for chars,tags in self._source_chunks:super().insert('end',render(chars),*tags)
        super().configure(state='disabled');self.yview_moveto(scroll)
        if selection:self.tag_add('sel',*selection)


class _Dialogs:
    def __init__(self, module):
        self.module = module

    def __getattr__(self, name):
        function = getattr(self.module, name)
        def localized(*args, **kw):
            args = tuple(render(value) if isinstance(value, str) else value for value in args)
            for key in ('title', 'message', 'detail', 'prompt'):
                if key in kw:
                    kw[key] = render(kw[key])
            return function(*args, **kw)
        return localized


messagebox = _Dialogs(_messagebox)
simpledialog = _Dialogs(_simpledialog)
filedialog = _Dialogs(_filedialog)
