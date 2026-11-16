from .i18n import t,format_number
from .entity_names import nature_name
"""Three compact rows of paired stats, with inline IV/EV and hover details."""
from . import localized_tk as tk
from .ui import BG,CARD,TEXT,MUTED,GREEN,RED,label
from .tooltips import Tooltip
from .natures import nature_effect

STATS=(('hp','HP'),('attack','ATK'),('defense','DEF'),('special_attack','SP ATK'),('special_defense','SP DEF'),('speed','SPEED'))
STAT_NAMES=dict(hp='Здоровье',attack='Атака',defense='Защита',special_attack='Специальная атака',special_defense='Специальная защита',speed='Скорость')
HIDDEN_STATS=(('ivs','IV','#829cb7'),('evs','EV','#a192b6'))

class StatValues(tk.Frame):
    def __init__(self,parent):
        super().__init__(parent,bg=BG)
        self.stats={};self.values={};self.hints={};self.names={};self.name_hints={};self.cells={};self.group_labels={};self.label_hints={};self.stat_hints={}
        self.columnconfigure((0,1),weight=1,uniform='stats')
        for i,(key,title) in enumerate(STATS):
            box=tk.Frame(self,bg=CARD,padx=8,pady=4);box.grid(row=i//2,column=i%2,sticky='ew',padx=(0 if i%2==0 else 4,0),pady=(0,4 if i//2<2 else 0));box.columnconfigure(2,weight=1);self.cells[key]=box
            self.names[key]=label(box,title,8,MUTED,bold=True,pack=False,bd=0,padx=0,pady=0);self.names[key].grid(row=0,column=0,sticky='w')
            self.name_hints[key]=Tooltip(self.names[key],title+' — '+STAT_NAMES[key])
            self.stats[key]=label(box,'—',12,TEXT,bold=True,pack=False,bd=0,padx=0,pady=0);self.stats[key].grid(row=0,column=1,sticky='w',padx=(6,7))
            self.stat_hints[key]=Tooltip(self.stats[key])
            self.values[key]={};self.hints[key]={};self.group_labels[key]={};self.label_hints[key]={}
            for column,(group,abbreviation,color) in enumerate(HIDDEN_STATS,3):
                meta=tk.Frame(box,bg=CARD);meta.grid(row=0,column=column,sticky='e',padx=(5 if group=='evs' else 0,0))
                caption=label(meta,abbreviation,8,color,pack=False,bd=0,padx=0,pady=0);caption.pack(side='left',padx=(0,2))
                value=label(meta,'—',9,color,pack=False,bd=0,padx=0,pady=0);value.pack(side='left')
                self.values[key][group]=value;self.hints[key][group]=Tooltip(value);self.group_labels[key][group]=caption;self.label_hints[key][group]=Tooltip(caption)
        self.hp_hint=self.stat_hints['hp']
    def set(self,mon):
        nature=nature_effect(mon.get('nature'))
        for key,title in STATS:
            modifier=nature['modifiers'].get(key,0) if nature else 0
            color=GREEN if modifier>0 else RED if modifier<0 else None
            self.names[key].configure(text=title+(' ↑' if modifier>0 else ' ↓' if modifier<0 else ''),fg=color or MUTED)
            value=mon.get('max_hp','—') if key=='hp' else mon.get('stats',{}).get(key,'—')
            stage=mon.get('stages',{}).get(key)
            self.stats[key].configure(text=str(value)+(f' ({stage:+d})' if stage else ''),fg=color or TEXT)
            if key=='hp':effect='HP не зависит от характера (0%).'
            elif nature is None:effect='Нет данных о характере.'
            elif modifier:effect=t('pokemon.nature_effect',name=nature_name(mon['nature']),modifier=f'{modifier:+d}%',multiplier='×'+format_number(1.1 if modifier>0 else 0.9,decimals=1))
            else:effect=t('pokemon.nature_neutral',name=nature_name(mon['nature']))
            for hint in (self.name_hints[key],self.stat_hints[key]):
                tooltip=title+' — '+STAT_NAMES[key]+'\n'+effect
                if key=='hp' and hint is self.hp_hint:tooltip='Максимум HP: '+str(mon.get('max_hp','—'))+'\nТекущее здоровье: '+str(mon.get('hp','—'))+'\n'+effect
                if hint.text!=tooltip:hint.hide();hint.text=tooltip
            for group,abbreviation,_ in HIDDEN_STATS:
                value=(mon.get(group) or {}).get(key);text=str(value) if value is not None else '—';self.values[key][group].configure(text=text)
                description='Врождённое значение.' if group=='ivs' else 'Очки усилий, накопленные этим Pokémon.'
                tooltip=abbreviation+' · '+STAT_NAMES[key]+': '+(text if value is not None else 'нет данных')+'\n'+description
                for hint in (self.hints[key][group],self.label_hints[key][group]):
                    if hint.text!=tooltip:hint.hide();hint.text=tooltip
