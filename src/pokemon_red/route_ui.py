"""Local FireRed encounter probabilities; every exact map has its own table."""
from . import localized_tk as tk
import webbrowser
from .catalog import catalog,species
from .pokemon_ui import detail_window,show_species
from .sprites import sprite
from .ui import BG,CARD,TEXT,MUTED,GREEN,Button,label
from .zones import zone_spec
from .types_ui import Badges,TYPE_INFO
from .encounters import level_label
from .tooltips import Tooltip

def show_zone(panel,key):
    root=panel.monitor.folder;data=catalog(root);info=data['routes'][key];name=zone_spec(root)['zones'].get(key,{}).get('label',key)
    body=detail_window(panel,'zone','Встречи · '+name,690);label(body,name,23,GREEN,bold=True);label(body,('Пещерный этаж' if info.get('terrain')=='cave' else 'Обычная трава')+' · FireRed',11,MUTED).pack_configure(pady=(4,12))
    grid=tk.Frame(body,bg=BG);grid.pack(fill='x');grid.columnconfigure((0,1),weight=1,uniform='encounters')
    for i,row in enumerate(info['population']):
        sp=species(row['species_id'],root);cell=tk.Frame(grid,bg=CARD,padx=8,pady=8);cell.grid(row=i//2,column=i%2,sticky='nsew',padx=(0 if i%2==0 else 5,5 if i%2==0 else 0),pady=(0,9))
        image=sprite(cell,root,sp['id']);portrait=tk.Label(cell,image=image,bg=CARD,cursor='hand2');portrait.image=image;portrait.pack(side='left');portrait.bind('<Button-1>',lambda _,n=sp['id']:show_species(panel,n))
        content=tk.Frame(cell,bg=CARD);content.pack(side='left',fill='x',expand=True);Button(content,sp['name'],lambda n=sp['id']:show_species(panel,n),variant='ghost',height=26,anchor='w').pack(fill='x')
        chance=label(content,f"{row['probability']:g}% · Lv {level_label(row)}",12,GREEN,bold=True)
        Tooltip(chance,"Доли среди всех встреч:\n"+"\n".join(f"Lv {lv} — {weight:g}%" for lv,weight in sorted(row['levels'].items(),key=lambda p:int(p[0]))))
        hp=label(content,f"HP {row['hp_min']}–{row['hp_max']}",10,MUTED)
        Tooltip(hp,'HP по уровням, IV 0–31, без EV:\n'+'\n'.join(f"Lv {lv}: {v['min']}–{v['max']} HP" for lv,v in sorted(row['hp_by_level'].items(),key=lambda p:int(p[0]))))
        weakness=', '.join(TYPE_INFO[int(t)][1]+' ×'+str(int(v)) for t,v in row['weaknesses'].items())
        label(content,'Слабости: '+(weakness or 'нет'),10,MUTED,wraplength=220)
        badges=Badges(content,labels=False);badges.configure(width=70);badges.set(sp['type_ids']);badges.pack(fill='x')
    label(body,'HP — возможный диапазон без EV. Слабости показаны по типам; способности могут менять результат. Для выбора команды проверяются варианты способностей. Проценты — доля вида среди обычных встреч, а не шанс боя на каждом шаге. Участки одной карты используют общую таблицу. У каждого этажа Mt. Moon своя таблица.',11,MUTED,wraplength=550).pack_configure(pady=(8,10))
    Button(body,'Источник таблицы ↗',lambda:webbrowser.open('https://github.com/pret/pokefirered/blob/ce6406d8c2eaf46d543c8a2606de0c3cb1951982/src/data/wild_encounters.json'),variant='ghost').pack(anchor='w')
