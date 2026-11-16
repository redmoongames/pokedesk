"""An editable draft; applying is an explicit, guarded main-game operation."""
import json, time
from . import localized_tk as tk
from .i18n import t, search_matches
from .entity_names import pokemon_name, entity_aliases
from .collection import owned_pokemon, location_label
from .ui import BG, CARD, TEXT, MUTED, GREEN, AMBER, Button, label
from .table import Table
from .sprites import sprite
from .travel_service import TravelService
from .party_management import validate_roster, validate_field


class PartyService(TravelService):
    worker = 'party_worker.py'
    def arguments(self, desired):
        return [json.dumps(desired)]


class PartyEditor:
    def __init__(self, panel, parent, *, dock=None):
        self.panel = panel; self.m = panel.monitor; self.parent = parent
        draft=getattr(panel,'party_draft',None)
        self.desired = list(draft['desired']) if draft and draft['generation']==self.m.generation else [m['uid'] for m in self.m.last_state.get('party', [])]
        self.plan = None; self.review_key = None; self.request_key = None
        self.request_id = 0; self.service = None; self.closed = False
        self.inventory = {}; self.signature = None; self.photos = {}; self.last_poll = 0
        label(parent, t('party_edit.title'), 18, bold=True)
        self.hint = label(parent, t('party_edit.draft_hint'), 11, MUTED, wraplength=440)
        self.hint.pack_configure(pady=(6, 10))
        self.selected = self.table(parent, ('name', 'level'),
                                   [('name', t('party_edit.selected'), 280), ('level', 'Lv', 50)], 4)
        self.selected.bind('<<TreeviewSelect>>', lambda _: self.update_controls())
        row = tk.Frame(parent, bg=BG); row.pack(fill='x', pady=(5, 10))
        self.remove = Button(row, t('party_edit.remove'), self.remove_selected, height=30)
        self.remove.pack(side='left')
        self.up = Button(row, '↑', lambda: self.move(-1), width=36, height=30); self.up.pack(side='right')
        self.down = Button(row, '↓', lambda: self.move(1), width=36, height=30); self.down.pack(side='right', padx=5)
        label(parent, t('party_edit.collection'), 12, bold=True)
        self.query = tk.StringVar(value=draft.get('query','') if draft and draft['generation']==self.m.generation else '')
        self.entry = tk.Entry(parent, textvariable=self.query, bg=CARD, fg=TEXT,
                              insertbackground=TEXT, relief='flat', font=('Helvetica', 12))
        self.entry.pack(fill='x', ipady=7, pady=(5, 6))
        self.available = self.table(parent, ('name', 'place', 'level'),
                                    [('name', t('party_edit.pokemon'), 180),
                                     ('place', t('party_edit.where'), 150), ('level', 'Lv', 45)], 5)
        self.available.bind('<<TreeviewSelect>>', lambda _: self.update_controls())
        self.available.bind('<Double-1>', lambda _: self.add_selected())
        self.available.bind('<Return>', lambda _: self.add_selected())
        self.add = Button(parent, t('party_edit.add'), self.add_selected, height=32)
        self.add.pack(fill='x', pady=(6, 4))
        label(parent, t('party_edit.collection_hint'), 10, MUTED, wraplength=440).pack_configure(pady=(0, 9))
        actions=dock if dock is not None else parent
        self.status = label(actions, '', 11, AMBER, wraplength=440)
        self.review = Button(actions, t('party_edit.review'), self.prepare, height=36)
        self.review.pack(fill='x', pady=(8, 5))
        self.apply = Button(actions, t('party_edit.apply'), self.start, variant='primary', height=36)
        self.apply.pack(fill='x')
        if dock is not None:dock.bind('<Configure>',lambda e:self.status.configure(wraplength=max(240,e.width-12)),add='+')
        self.trace = self.query.trace_add('write', lambda *_: self.render_available())
        parent.bind('<Destroy>', lambda e: self.close() if e.widget is parent else None, add='+')
        parent.bind('<Configure>', self.resize, add='+')
        self.refresh(self.m.last_state)

    def resize(self, event):
        for widget in (self.hint, self.status):widget.configure(wraplength=max(240, event.width-8))

    def table(self, parent, columns, headings, height):
        from .scrolling import Scrollbar
        box = tk.Frame(parent, bg=BG); box.pack(fill='x')
        view = Table(box, columns=columns, show='tree headings', height=height,
                     selectmode='browse', style='Trainer.Treeview')
        view.column('#0', width=42, minwidth=42, stretch=False)
        for key, title, width in headings:
            view.heading(key, text=title)
            view.column(key, width=width, minwidth=40 if key=='level' else 80,
                        stretch=key!='level', anchor='e' if key=='level' else 'w')
        scroll = Scrollbar(box, command=view.yview, height=1); scroll.pack(side='right', fill='y')
        view.configure(yscrollcommand=scroll.set); view.pack(fill='x', expand=True)
        return view

    def key(self):
        s = self.m.last_state; c = s.get('controls', {}); p = s.get('position', {})
        return (self.m.generation, tuple(self.desired), (s.get('map') or {}).get('name'),
                p.get('x'), p.get('y'), bool(s.get('in_battle')), c.get('callback'),
                bool(c.get('field_locked')), bool(c.get('moving')),
                tuple((m['uid'], m.get('held_item',0), m.get('hp')) for m in self.inventory.get('party', [])),
                tuple((m['uid'], m.get('box'), m.get('box_slot')) for m in self.inventory.get('boxes', [])))

    def busy(self):
        return bool(self.m.ai_controlled() or getattr(getattr(self.m,'delivery',None),'data',{}).get('enabled') or self.m.status.get('battle_auto', {}).get('active')
                    or self.m.status.get('battle_capture', {}).get('active')
                    or self.m.status.get('saving') or self.m.pending_takeover)

    def invalidate(self):
        self.plan = None; self.review_key = None; self.request_key = None; self.request_id += 1
        if self.service:self.service.close(); self.service = None

    def changed(self):
        self.invalidate(); self.render_selected(); self.render_available(); self.update_controls()

    def render_selected(self):
        previous = self.selected.selection(); self.selected.delete(*self.selected.get_children())
        owned = {m['uid']:m for m in owned_pokemon(self.inventory)}
        for i, uid in enumerate(self.desired):
            m = owned.get(uid)
            name = ('✦ ' if m and m.get('shiny') else '')+(str(pokemon_name(m)) if m else str(t('party_edit.missing_short')))
            photo = self.photo(m) if m else ''
            self.selected.insert('', 'end', iid=uid, image=photo,
                                 values=(f'{i+1}. {name}', m.get('level','—') if m else '—'))
        if previous and self.selected.exists(previous[0]):self.selected.selection_set(previous[0])

    def photo(self, mon):
        key = (mon['species_id'], bool(mon.get('shiny')))
        if key not in self.photos:self.photos[key] = sprite(self.parent, self.m.folder, key[0], scale=.5, shiny=key[1])
        return self.photos[key] or ''

    def render_available(self):
        previous = self.available.selection(); y = self.available.yview()[0]
        self.available.delete(*self.available.get_children())
        query = self.query.get()
        for m in owned_pokemon(self.inventory):
            if m['uid'] in self.desired or m.get('is_egg') or m.get('location')=='daycare':continue
            if not search_matches(query, m.get('nickname',''), entity_aliases('species',m['species_id'])):continue
            self.available.insert('', 'end', iid=m['uid'], image=self.photo(m),
                                  values=(('✦ ' if m.get('shiny') else '')+str(pokemon_name(m)), location_label(m), m.get('level','—')))
        if previous and self.available.exists(previous[0]):self.available.selection_set(previous[0])
        self.available.configure(height=max(1,min(5,len(self.available.get_children()))))
        self.available.yview_moveto(y); self.update_controls()

    def add_selected(self):
        rows = self.available.selection()
        if rows and len(self.desired)<6 and not self.busy():
            self.desired.append(rows[0]); self.changed()

    def remove_selected(self):
        rows = self.selected.selection()
        if rows and rows[0] in self.desired and not self.busy():
            self.desired.remove(rows[0]); self.changed()

    def move(self, delta):
        rows = self.selected.selection()
        if not rows or self.busy():return
        i = self.desired.index(rows[0]); j = i+delta
        if 0<=j<len(self.desired):
            self.desired[i],self.desired[j] = self.desired[j],self.desired[i]
            self.changed(); self.selected.selection_set(rows[0])

    def update_controls(self):
        if self.closed:return
        busy = self.busy(); error = ''
        try:validate_roster(self.inventory,self.desired);validate_field(self.m.last_state)
        except ValueError as e:error = str(e)
        if busy:error = str(t('party_edit.busy'))
        if self.plan and self.review_key!=self.key():self.invalidate()
        pending = self.request_key is not None
        if error:message = error
        elif self.plan:message = str(t('party_edit.review_summary',clinic=self.plan['label'],steps=self.plan['steps'],added=len(self.plan['added']),removed=len(self.plan['removed'])))
        elif pending:message = str(t('party_edit.checking'))
        else:message = str(t('party_edit.review_hint'))
        if getattr(self,'failure','') and not error and not self.plan and not pending:message=self.failure
        self.status.configure(text=message,fg=GREEN if self.plan and not error else MUTED if pending else AMBER)
        self.review.configure(state='normal' if not error and not pending else 'disabled')
        self.apply.configure(state='normal' if self.plan and not error and not pending else 'disabled')
        self.remove.configure(state='normal' if self.selected.selection() and not busy else 'disabled')
        self.add.configure(state='normal' if self.available.selection() and len(self.desired)<6 and not busy else 'disabled')
        for button in (self.up,self.down):button.configure(state='normal' if self.selected.selection() and not busy else 'disabled')

    def prepare(self):
        if self.busy():return
        try:validate_roster(self.inventory,self.desired);validate_field(self.m.last_state)
        except ValueError as e:self.failure=str(e);self.update_controls();return
        self.invalidate();self.failure='';self.request_key=self.key();request_id=self.request_id
        key=self.request_key;generation=self.m.generation
        def captured(snapshot):
            if self.closed or request_id!=self.request_id or key!=self.key() or snapshot['generation']!=generation:return
            self.service=PartyService();self.service.request(self.m.folder,snapshot['state'],list(self.desired))
        def failed(error):
            if not self.closed and request_id==self.request_id:
                self.request_key=None;self.failure=str(error);self.update_controls()
        self.m.watch(self.m.travel_snapshot(),captured,failed);self.update_controls()

    def start(self):
        if not self.plan or self.review_key!=self.key() or self.busy():self.update_controls();return
        self.m.start_party_change(dict(self.plan));self.panel.party_draft=None;self.invalidate();self.failure=''
        self.status.configure(text=t('party_edit.starting'))

    def refresh(self,state):
        if self.closed:return
        if getattr(self.m,'party_change_error',''):
            self.failure=self.m.party_change_error;self.m.party_change_error=''
        if time.monotonic()-self.last_poll>.7:
            self.last_poll=time.monotonic();self.inventory=self.m.inventory_snapshot()
            signature=repr([(m.get('uid'),m.get('level'),m.get('nickname'),m.get('location'),m.get('slot'),m.get('box'),m.get('box_slot')) for m in owned_pokemon(self.inventory)])
            if signature!=self.signature:
                self.signature=signature;self.render_selected();self.render_available()
        if self.request_key is not None and self.request_key!=self.key():self.invalidate()
        if self.service:
            result=self.service.poll()
            if result:
                plan,error=result;key=self.request_key;self.service.close();self.service=None;self.request_key=None
                if key==self.key():self.plan=plan;self.review_key=key if plan else None;self.failure=error or ''
        self.update_controls()

    def suspend(self):
        self.invalidate()

    def close(self):
        if self.closed:return
        self.panel.party_draft=dict(generation=self.m.generation,desired=list(self.desired),query=self.query.get())
        self.closed=True;self.invalidate();self.query.trace_remove('write',self.trace)
