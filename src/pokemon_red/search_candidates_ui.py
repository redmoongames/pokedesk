"""Compact top-three view of detached, scored search candidates."""
from . import localized_tk as tk
from .ui import CARD,BG,TEXT,MUTED,BLUE,GREEN,Button,label
from .sprites import sprite
from .entity_names import species_name,nature_name
from .capture_target import gender_of
from .iv_preferences_ui import TITLES
from .models import STAT_KEYS
from .i18n import t,literal,format_number
from .tooltips import Tooltip

class SearchCandidatesView:
    def __init__(self,parent,root,command,*,on_select=None):
        self.root=root;self.command=command;self.frame=tk.Frame(parent,bg=BG);self.frame.pack(fill='x');self.rows=[];self.selected=None;self.signature=None;self.user_selected=False;self.active=False
        self.cards=tk.Frame(self.frame,bg=BG);self.cards.pack(fill='x')
        self.action=Button(self.frame,t('capture.use_best'),self.accept);self.action.pack(fill='x',pady=(6,0));Tooltip(self.action,t('capture.use_best_help'))
        self.on_select=on_select
    def accept(self):
        if self.active and self.selected:self.command(self.selected)
    def choose(self,sha):
        if not self.active:return
        self.selected=sha;self.user_selected=True;self.signature=None;self.update(self.rows,self.active)
        if sha in self.card_widgets:self.card_widgets[sha].focus_set()
        if self.on_select:self.on_select(sha)
    def update(self,rows,active):
        self.rows=list(rows[:3]);self.active=active
        hashes=[r['sha256'] for r in self.rows]
        if self.selected not in hashes:self.selected=hashes[0] if hashes and not self.user_selected else None
        self.action.configure(state='normal' if active and self.selected else 'disabled')
        signature=(tuple(hashes),self.selected,bool(active))
        if signature==self.signature:return
        self.signature=signature
        for child in self.cards.winfo_children():child.destroy()
        self.card_widgets={}
        for i,row in enumerate(self.rows):
            mon=row['pokemon'];sha=row['sha256'];chosen=sha==self.selected
            card=tk.Frame(self.cards,bg=CARD,highlightthickness=1,highlightbackground=BLUE if chosen else CARD,padx=5,pady=4,takefocus=bool(active),cursor='hand2' if active else '');card.pack(fill='x',pady=(0,5))
            self.card_widgets[sha]=card
            photo=sprite(card,self.root,mon['species_id'],shiny=mon.get('shiny',False));image=tk.Label(card,image=photo,bg=CARD,width=64);image.image=photo;image.pack(side='left')
            content=tk.Frame(card,bg=CARD);content.pack(side='left',fill='x',expand=True)
            title=t('capture.candidate_rank',rank=i+1,name=species_name(mon['species_id']),score=format_number(row['score'],decimals=int(row['score']%1!=0)),target=format_number(row['target_score'],decimals=int(row['target_score']%1!=0)))
            label(content,title,11,GREEN if chosen else TEXT,bold=True)
            gender={'male':'♂','female':'♀','genderless':'—'}[gender_of(mon,self.root)]
            label(content,literal(f"Lv.{mon['level']} · {gender} · {nature_name(mon.get('nature',mon['personality']%25))}"),10,MUTED)
            values=[('★' if k in row.get('priority_ivs',()) else '↓' if k in row.get('negative_ivs',()) else '')+name+' '+str(mon['ivs'][k]) for k,name in zip(STAT_KEYS,TITLES)]
            for part in (values[:3],values[3:]):label(content,literal(' · '.join(part)),10,MUTED)
            content.bind('<Configure>',lambda e,c=content:[w.configure(wraplength=max(100,e.width)) for w in c.winfo_children()],add='+')
            Tooltip(card,t('capture.candidate_help',missing=len(row.get('missing',[]))))
            def bind(widget,key=sha):
                widget.bind('<Button-1>',lambda _,s=key:self.choose(s),add='+')
                for child in widget.winfo_children():bind(child,key)
            bind(card);card.bind('<Return>',lambda _,s=sha:self.choose(s));card.bind('<space>',lambda _,s=sha:self.choose(s))
        if not self.rows:label(self.cards,t('capture.waiting_candidates'),11,MUTED)
