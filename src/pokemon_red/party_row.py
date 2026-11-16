"""Compact party row: selectable data, pixel portrait and explicit open action."""
from . import localized_tk as tk
from .i18n import t,get_locale,subscribe,unsubscribe
from .entity_names import pokemon_name
from .ui import BG,TEXT,MUTED,GREEN,AMBER,RED,BLUE,Button,Meter,label
from .sprites import sprite
from .types_ui import Badges,types_for
from .statuses import status_info,show_status
from .catalog import catalog,species
from .tooltips import Tooltip


def party_row_signature(mon):
    return tuple(mon.get(key) for key in ('uid','species_id','nickname','species','level','hp','max_hp','experience','exp_to_next_level','status_code','status','shiny'))+(tuple(mon.get('types') or mon.get('type_ids') or ()),)


class PartyRow(tk.Frame):
    def __init__(self,parent,root,command):
        super().__init__(parent,bg=BG,pady=9)
        self.root_path=root;self.command=command;self.mon=None;self._signature=None
        portrait_box=tk.Frame(self,bg=BG,width=64,height=64);portrait_box.pack(side='left',padx=(0,10));portrait_box.pack_propagate(False)
        self.portrait=tk.Label(portrait_box,bg=BG,cursor='hand2')
        self.portrait.pack(expand=True);self.portrait.bind('<Button-1>',lambda _:self.invoke())
        self.open_button=Button(self,'›',self.invoke,variant='ghost',width=30,height=38)
        self.open_button.pack(side='right',padx=(8,0));self.open_hint=Tooltip(self.open_button)
        body=tk.Frame(self,bg=BG);body.pack(side='left',fill='x',expand=True)
        top=tk.Frame(body,bg=BG);top.pack(fill='x')
        self.level=label(top,'',11,MUTED,pack=False);self.level.pack(side='right',padx=(8,0))
        self.status=Button(top,'',self.inspect_status,variant='ghost',width=26,height=23)
        self.status_hint=Tooltip(self.status)
        self.name=label(top,'',13,TEXT,bold=True,pack=False,height=1);self.name.pack(side='left',fill='x',expand=True)
        self.name_hint=Tooltip(self.name)
        meta=tk.Frame(body,bg=BG);meta.pack(fill='x',pady=(1,2))
        self.hp_text=label(meta,'',11,TEXT,pack=False);self.hp_text.pack(side='right',padx=(8,0))
        self.types=Badges(meta);self.types.pack(side='left',fill='x',expand=True)
        self.hp=Meter(body,height=5);self.hp.pack(fill='x')
        self.xp=Meter(body,height=3,color=BLUE);self.xp.pack(fill='x',pady=(4,0));self.xp_hint=Tooltip(self.xp)
        self.bind('<Destroy>',lambda e:unsubscribe(self) if e.widget is self else None,add='+');subscribe(self)
    def invoke(self):
        if self.mon:self.command()
    def inspect_status(self):
        if self.mon:
            if status_info(self.mon,self.root_path):show_status(self,self.mon,self.root_path)
            else:self.invoke()
    def locale_changed(self):
        self._signature=None
        if self.mon and self.winfo_exists():self.set(self.mon)
    def set(self,mon):
        signature=(get_locale(),party_row_signature(mon));self.mon=mon
        if signature==self._signature:return
        self._signature=signature
        self.photo=sprite(self,self.root_path,mon['species_id'],shiny=mon.get('shiny',False),gray=mon['hp']<=0)
        self.portrait.configure(image=self.photo or '')
        name=pokemon_name(mon);self.name.configure(text=name);self.name_hint.text=name
        self.level.configure(text=t('design.level',level=mon['level']))
        ratio=mon['hp']/max(1,mon['max_hp']);color=GREEN if ratio>.5 else AMBER if ratio>.2 else RED
        self.hp_text.configure(text=f"{mon['hp']} / {mon['max_hp']} HP",fg=color if ratio<=.5 else TEXT)
        self.hp.set(ratio,color);self.types.set(types_for(mon,self.root_path))
        info=species(mon['species_id'],self.root_path);curve=catalog(self.root_path)['growth'][info['growth']];level=mon['level']
        fraction=1 if level>=100 else (mon.get('experience',curve[level])-curve[level])/max(1,curve[level+1]-curve[level])
        self.xp.set(fraction);self.xp_hint.text=t('design.next_level',xp=mon.get('exp_to_next_level',0))
        self.open_hint.text=str(t('design.open_pokemon',name=name))+'\n'+str(self.xp_hint.text)
        status=status_info(mon,self.root_path)
        if status:
            self.status.configure(text=status['glyph'],fg=status['color']);self.status.pack(side='right',padx=(4,0));self.status_hint.text=status['name']
        elif mon.get('shiny'):
            self.status.configure(text='✦',fg=AMBER);self.status.pack(side='right',padx=(4,0));self.status_hint.text='Shiny Pokémon'
        else:self.status.pack_forget()
