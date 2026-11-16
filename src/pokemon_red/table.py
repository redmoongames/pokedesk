"""Virtual, pixel-scrolled tables with the app's existing Treeview data API.

An unmapped ttk model preserves IDs, values, tags and selection semantics.
Only the visible rows are painted; neither headers nor scrolling snap to rows.
"""
import math
from .i18n import render,subscribe,unsubscribe,t,literal
from . import localized_tk as tk
from tkinter import ttk
from .ui import BG,CARD,TEXT,MUTED,GREEN,HOVER,rounded,short,cached_font

class Table(tk.Frame):
    _pixel_scroll=True
    def __init__(self,parent,**options):
        options.setdefault('height',10);options.setdefault('selectmode','browse')
        self.model=ttk.Treeview(parent,**options)
        self.rowheight=int(ttk.Style(parent).lookup(options.get('style','Treeview'),'rowheight') or 44)
        self.offset=0.0;self._draw_id=None;self._row_ids=None;self._hover=None;self._drag=None;self._tags={};self._heading_commands={};self._yscroll=None;self._indicator=None
        super().__init__(parent,bg=BG,bd=0,highlightthickness=0,takefocus=True,width=500,height=self.requested_height())
        self.pack_propagate(False)
        self.header=tk.Canvas(self,bg=BG,bd=0,highlightthickness=0,takefocus=False,height=self.header_height)
        self.body=tk.Canvas(self,bg=CARD,bd=0,highlightthickness=0,takefocus=False)
        if self.header_height:self.header.pack(fill='x')
        self.body.pack(fill='both',expand=True)
        # Let a table's existing mouse bindings receive events from its canvases.
        for canvas in (self.header,self.body):
            tags=canvas.bindtags();canvas.bindtags((tags[0],str(self),*tags[1:]))
        self.bind('<Configure>',lambda _:self.redraw(),add='+')
        self.bind('<FocusIn>',lambda _:self.redraw(),add='+');self.bind('<FocusOut>',lambda _:self.redraw(),add='+')
        self.bind('<ButtonPress-1>',self.pressed,add='+');self.bind('<B1-Motion>',self.dragged,add='+');self.bind('<ButtonRelease-1>',self.released,add='+')
        self.bind('<Motion>',self.hovered,add='+');self.bind('<Leave>',lambda _:self.clear_hover(),add='+')
        for key in ('Up','Down','Home','End','Prior','Next'):
            self.bind('<'+key+'>',lambda e,k=key:self.key(k))
        self.model.bind('<<TreeviewSelect>>',self.selected)
        self.bind('<Destroy>',self.destroyed,add='+')
        self._install_indicator();self.redraw();subscribe(self)
        from .tooltips import Tooltip
        self.value_hint=Tooltip(self,lambda:self.hover_value(),bind=False)
        self.bind('<FocusIn>',lambda _:self.value_hint.focused(),add='+')
        self.bind('<FocusOut>',self.value_hint.hide,add='+')
        self.bind('<<Copy>>',self.copy_selection)
        self.bind('<Command-c>',self.copy_selection);self.bind('<Control-c>',self.copy_selection)
        self.bind('<Button-3>',self.context_copy);self.bind('<Control-Button-1>',self.context_copy)
    def locale_changed(self):
        if self.winfo_exists():self.value_hint.hide();self.redraw()
    @property
    def header_height(self):return 34 if 'headings' in self.show_parts() else 0
    def show_parts(self):return tuple(str(value) for value in self.model['show'])
    def requested_height(self):return max(1,int(self.model['height']))*self.rowheight+self.header_height
    def bind(self,sequence=None,func=None,add=None):
        if func is not None and callable(func):
            def adapted(event):
                if event.type in (tk.EventType.ButtonPress,tk.EventType.ButtonRelease,tk.EventType.Motion,tk.EventType.Enter,tk.EventType.Leave):
                    if event.widget is self.body:event.y+=self.header_height
                    event.widget=self
                return func(event)
            return super().bind(sequence,adapted,add)
        return super().bind(sequence,func,add)
    def configure(self,cnf=None,**kw):
        if cnf:kw.update(cnf)
        model_keys={'columns','displaycolumns','height','show','selectmode','style'}
        changed={k:kw.pop(k) for k in list(kw) if k in model_keys}
        if 'yscrollcommand' in kw:
            self._yscroll=kw.pop('yscrollcommand')
            if self._indicator:self._indicator.place_forget()
        if changed:
            self.model.configure(**changed)
            if 'style' in changed:self.rowheight=int(ttk.Style(self).lookup(self.model['style'],'rowheight') or 44)
            super().configure(height=self.requested_height());self.header.configure(height=self.header_height)
            if 'show' in changed:
                if self.header_height:self.header.pack(fill='x',before=self.body)
                else:self.header.pack_forget()
        if kw:super().configure(**kw)
        if hasattr(self,'body'):self.redraw()
    config=configure
    def cget(self,key):
        if key in ('columns','displaycolumns','height','show','selectmode','style'):return self.model.cget(key)
        if key=='yscrollcommand':return self._yscroll or ''
        return super().cget(key)
    __getitem__=cget
    def _install_indicator(self):
        from .scrolling import Scrollbar
        self._indicator=Scrollbar(self.body,command=self.yview)
        self._indicator.place(relx=1,rely=0,relheight=1,width=9,anchor='ne')
    def destroyed(self,event):
        if event.widget is not self:return
        unsubscribe(self)
        if self._draw_id:
            try:self.after_cancel(self._draw_id)
            except tk.TclError:pass
        # The unmapped model is a sibling, so explicitly release it as well.
        if self.model.winfo_exists():self.model.destroy()
    def redraw(self):
        if not self._draw_id and self.winfo_exists():self._draw_id=self.after_idle(self.draw)
    def changed(self):
        self._row_ids=None
        controller=getattr(self,'_smooth_controller',None)
        if controller:controller.cancel()
        self.redraw()
    def rows(self):
        if self._row_ids is None:self._row_ids=self.model.get_children()
        return self._row_ids
    def insert(self,*args,**kw):
        result=self.model.insert(*args,**kw);self.changed();return result
    def delete(self,*items):self.model.delete(*items);self.changed()
    def get_children(self,item=None):return self.model.get_children(item)
    def exists(self,item):return self.model.exists(item)
    def item(self,item,option=None,**kw):
        result=self.model.item(item,option,**kw)
        if kw:self.redraw()
        return result
    def set(self,item,column=None,value=None):
        result=self.model.set(item,column,value)
        if value is not None:self.redraw()
        return result
    def move(self,item,parent,index):self.model.move(item,parent,index);self.changed()
    def index(self,item):return self.model.index(item)
    def selection(self):return self.model.selection()
    def selection_set(self,*items):self.model.selection_set(*items);self.redraw()
    def selection_add(self,*items):self.model.selection_add(*items);self.redraw()
    def selection_remove(self,*items):self.model.selection_remove(*items);self.redraw()
    def focus(self,item=None):return self.model.focus(item)
    def selected(self,_):
        self.redraw()
        if self.winfo_exists():self.event_generate('<<TreeviewSelect>>',when='tail')
    def tag_configure(self,tag,option=None,**kw):
        self._tags.setdefault(tag,{}).update(kw);self.redraw();return self.model.tag_configure(tag,option,**kw)
    tag_config=tag_configure
    def heading(self,column,option=None,**kw):
        if 'command' in kw:self._heading_commands[column]=kw['command']
        result=self.model.heading(column,option,**kw)
        if kw:self.redraw()
        return result
    def column(self,column,option=None,**kw):
        result=self.model.column(column,option,**kw)
        if kw:self.redraw();return result
        width=next((w for k,x,w in self.layout_columns() if k==column),None)
        if option=='width' and width is not None:return width
        if option is None and width is not None:result['width']=width
        return result
    def layout_columns(self):
        columns=[str(k) for k in self.model['columns']];display=tuple(str(k) for k in self.model['displaycolumns'])
        keys=columns if tuple(display)==('#all',) else [columns[int(k)] if str(k).isdigit() else k for k in display]
        if 'tree' in self.show_parts():keys=['#0',*keys]
        specs=[self.model.column(k) for k in keys];widths=[s['width'] for s in specs];available=max(1,self.winfo_width())
        flexible=[i for i,s in enumerate(specs) if s['stretch']]
        difference=available-sum(widths)
        if difference>0 and flexible:
            total=sum(widths[i] for i in flexible) or len(flexible)
            for i in flexible:widths[i]+=int(difference*(specs[i]['width']/total))
            widths[flexible[-1]]+=available-sum(widths)
        elif difference<0:
            remaining=-difference
            for _ in range(len(widths)+1):
                candidates=[i for i in flexible if widths[i]>specs[i]['minwidth']]
                if not candidates:break
                portion=max(1,math.ceil(remaining/len(candidates)))
                for i in candidates:
                    cut=min(portion,widths[i]-specs[i]['minwidth'],remaining);widths[i]-=cut;remaining-=cut
                if not remaining:break
        result=[];x=0
        for key,width in zip(keys,widths):result.append((key,x,int(width)));x+=width
        return result
    def scroll_extent(self):return len(self.rows())*self.rowheight
    def viewport_height(self):return max(1,self.winfo_height()-self.header_height)
    def yview(self,*args):
        if args:
            if args[0]=='moveto':self.yview_moveto(float(args[1]))
            elif args[0]=='scroll':self.yview_scroll(int(args[1]),args[2])
            return
        total=self.scroll_extent();visible=self.viewport_height()
        if not total or visible>=total:return (0.0,1.0)
        return (self.offset/total,min(1.0,(self.offset+visible)/total))
    def scroll_to_pixel(self,position):
        self.offset=max(0.0,min(max(0,self.scroll_extent()-self.viewport_height()),position));self.redraw();self.notify_scroll()
    def cancel_motion(self):
        controller=getattr(self,'_smooth_controller',None)
        if controller:controller.cancel()
    def yview_moveto(self,fraction):self.cancel_motion();self.scroll_to_pixel(float(fraction)*self.scroll_extent())
    def yview_scroll(self,number,what):
        self.cancel_motion();self.scroll_to_pixel(self.offset+number*(self.viewport_height()*.85 if what=='pages' else 1 if what=='pixels' else self.rowheight))
    def notify_scroll(self):
        first,last=self.yview()
        command=self._yscroll or (self._indicator.set if self._indicator else None)
        if callable(command):command(first,last)
        elif command:self.tk.call(*self.tk.splitlist(command),first,last)
    def see(self,item):
        if item not in self.rows():return
        top=self.rows().index(item)*self.rowheight;bottom=top+self.rowheight
        if top<self.offset:self.yview_moveto(top/max(1,self.scroll_extent()))
        elif bottom>self.offset+self.viewport_height():self.yview_moveto((bottom-self.viewport_height())/max(1,self.scroll_extent()))
    def identify_row(self,y):
        if y<self.header_height:return ''
        index=int((y-self.header_height+self.offset)//self.rowheight)
        return self.rows()[index] if 0<=index<len(self.rows()) and y<self.winfo_height() else ''
    def identify_column(self,x):
        for i,(key,left,width) in enumerate(self.layout_columns()):
            if left<=x<left+width:return '#0' if key=='#0' else '#'+str(i+(0 if 'tree' in self.show_parts() else 1))
        return ''
    def identify_region(self,x,y):
        if y<self.header_height:
            return 'separator' if any(abs(x-left-width)<4 for _,left,width in self.layout_columns()[:-1]) else 'heading'
        row=self.identify_row(y)
        return ('tree' if self.identify_column(x)=='#0' else 'cell') if row else 'nothing'
    def bbox(self,item,column=None):
        if item not in self.rows():return ''
        y=self.header_height+self.rows().index(item)*self.rowheight-self.offset
        if y+self.rowheight<=self.header_height or y>=self.winfo_height():return ''
        left=0;width=self.winfo_width()
        if column is not None:
            for key,x,w in self.layout_columns():
                if key==column:left,width=x,w;break
        return (int(left),int(y),int(width),self.rowheight)
    def pressed(self,event):
        self.focus_set();region=self.identify_region(event.x,event.y)
        if region=='separator':
            cols=self.layout_columns()
            for i,(key,x,width) in enumerate(cols[:-1]):
                if abs(event.x-x-width)<4:self._drag=(event.x,key,cols[i+1][0],width,cols[i+1][2]);break
        elif region=='heading':
            for key,x,width in self.layout_columns():
                if x<=event.x<x+width:
                    command=self._heading_commands.get(key)
                    if callable(command):command();self.redraw()
                    break
        else:
            row=self.identify_row(event.y)
            if row:self.model.focus(row);self.selection_set(row)
    def dragged(self,event):
        if not self._drag:return
        start,left,right,a,b=self._drag;delta=event.x-start
        delta=max(self.model.column(left,'minwidth')-a,min(b-self.model.column(right,'minwidth'),delta))
        self.model.column(left,width=a+delta);self.model.column(right,width=b-delta);self.redraw()
    def released(self,_):self._drag=None
    def hovered(self,event):
        row=self.identify_row(event.y)
        if row!=self._hover:
            self._hover=row;self.redraw();self.value_hint.hide()
        if row:self.value_hint.enter(event)
        self.configure(cursor='sb_h_double_arrow' if self.identify_region(event.x,event.y)=='separator' else '')
    def clear_hover(self):
        if self._hover:self._hover=None;self.redraw()
        self.value_hint.hide()
    def row_values(self,row):
        item=self.model.item(row)
        values=[str(item.get('text',''))] if 'tree' in self.show_parts() else []
        values.extend(str(self.model.set(row,key)) for key,_,_ in self.layout_columns() if key!='#0')
        return [render(value) for value in values]
    def copy_selection(self,_=None):
        from .text_values import copy_text
        rows=self.selection()
        if rows:return copy_text(self,'\n'.join('\t'.join(self.row_values(row)) for row in rows))
        return 'break'
    def context_copy(self,event):
        from .text_values import copy_menu
        row=self.identify_row(event.y)
        if not row:return 'break'
        column=next((key for key,x,width in self.layout_columns() if x<=event.x<x+width),None)
        value=self.model.item(row,'text') if column=='#0' else self.model.set(row,column) if column else ''
        return copy_menu(self,event,[(t('design.copy_cell'),render(str(value))),(t('design.copy_row'),'\t'.join(self.row_values(row)))])
    def hover_value(self):
        row=self._hover or (self.selection()[0] if self.selection() else None)
        return ' · '.join(self.row_values(row)) if row and self.exists(row) else ''
    def key(self,key):
        rows=self.rows()
        if not rows:return 'break'
        selected=self.selection();index=rows.index(selected[0]) if selected and selected[0] in rows else -1
        step=max(1,int(self.viewport_height()/self.rowheight)-1)
        target={'Home':0,'End':len(rows)-1,'Up':max(0,index-1),'Down':min(len(rows)-1,index+1),'Prior':max(0,index-step),'Next':min(len(rows)-1,index+step)}[key]
        self.focus(rows[target]);self.selection_set(rows[target]);self.see(rows[target]);self.value_hint.hide();self.value_hint.enter();return 'break'
    def draw(self):
        self._draw_id=None
        if not self.winfo_exists():return
        self.header.delete('all');self.body.delete('all');cols=self.layout_columns();width=max(1,self.winfo_width());height=self.viewport_height()
        self.offset=max(0.0,min(max(0,self.scroll_extent()-height),self.offset))
        body_font=cached_font(self,('Helvetica',11));bold=cached_font(self,('Helvetica',11,'bold'));secondary=cached_font(self,('Helvetica',10));head_font=cached_font(self,('Helvetica',10,'bold'))
        for key,x,w in cols:
            text=self.model.heading(key,'text');anchor=str(self.model.column(key,'anchor'))
            sort=getattr(self,'_sort_column',None)
            if sort and sort[0]==key:text+= ' ↓' if sort[1] else ' ↑'
            tx=x+w-12 if anchor=='e' else x+w/2 if anchor=='center' else x+12
            self.header.create_text(tx,17,text=short(text,max(1,w-16),head_font),font=head_font,fill=MUTED,anchor=anchor)
        if self.header_height:self.header.create_line(8,self.header_height-1,width-8,self.header_height-1,fill='#253342')
        selected=set(self.selection());start=max(0,int(self.offset//self.rowheight));stop=min(len(self.rows()),math.ceil((self.offset+height)/self.rowheight))
        for index in range(start,stop):
            iid=self.rows()[index];row=self.model.item(iid);top=index*self.rowheight-self.offset;bottom=top+self.rowheight;styles={}
            # ttk.item() coerces numeric-looking strings; painting must retain "001".
            values=self.tk.call(self.model._w,'item',iid,'-values')
            for tag in row['tags']:styles.update(self._tags.get(tag,{}))
            fill='#20372f' if iid in selected else HOVER if iid==self._hover else styles.get('background','#141e29')
            if fill!='#141e29':rounded(self.body,4,top+2,width-4,bottom-2,7,fill=fill,outline='')
            if iid in selected:self.body.create_line(5,top+11,5,bottom-11,fill=GREEN,width=2,capstyle='round')
            self.body.create_line(12,bottom-.5,width-12,bottom-.5,fill='#1e2b39')
            for key,x,w in cols:
                value=row['text'] if key=='#0' else values[list(self.model['columns']).index(key)] if len(values)>list(self.model['columns']).index(key) else ''
                source_label=getattr(self,'_label_sources',{}).get(iid) if key=='label' else None
                if source_label is not None:value=render(source_label)
                padding=8 if key=='number' else 12
                text=str(value);left=x+padding;available=max(1,w-padding*2)
                if key=='#0' and row['image']:
                    image=row['image'][0];image_width=int(self.tk.call('image','width',image))
                    self.body.create_image(x+w/2 if not text else left+image_width/2,top+self.rowheight/2,image=image)
                    if text:left+=image_width+8;available=max(1,x+w-12-left)
                lines=text.split('\n');font=styles.get('font',bold if key in ('name','#0') else secondary if key in ('number','source','pocket') else body_font);font=cached_font(self,font) if isinstance(font,tuple) else font
                foreground=MUTED if key in ('number','pocket') else styles.get('foreground',TEXT);anchor=str(self.model.column(key,'anchor'));tx=x+w-12 if anchor=='e' else x+w/2 if anchor=='center' else left
                for line_index,line in enumerate(lines[:2]):
                    if source_label is not None:line=literal(line)
                    f=secondary if line_index else font;color=MUTED if line_index else foreground
                    y=top+self.rowheight/2+(9 if line_index else -8) if len(lines)>1 else top+self.rowheight/2
                    self.body.create_text(tx,y,text=short(line,available,f),font=f,fill=color,anchor=anchor)
        self.notify_scroll()

class ChoiceList(Table):
    """The same pixel viewport for dropdowns; retains Listbox's small API."""
    def __init__(self,parent,**options):
        for key in ('bg','fg','selectbackground','selectforeground','bd','highlightthickness','font','activestyle','exportselection'):options.pop(key,None)
        super().__init__(parent,columns=('label',),show='',height=8,**options)
        self.rowheight=32;self._counter=0;self._label_sources={};self.column('label',width=220,minwidth=40,stretch=True)
        super().configure(height=8)
    def insert(self,index,*elements):
        for text in elements:
            self._counter+=1;self._label_sources[str(self._counter)]=text;super().insert('',index,iid=str(self._counter),values=(text,))
    def row_values(self,row):return [render(self._label_sources.get(row,''))]
    def curselection(self):return tuple(self.rows().index(i) for i in self.selection() if i in self.rows())
    def selection_set(self,first,last=None):
        if isinstance(first,int):first=self.rows()[first]
        super().selection_set(first)
    def activate(self,index):self.focus(self.rows()[index])
    def see(self,index):super().see(self.rows()[index] if isinstance(index,int) else index)
