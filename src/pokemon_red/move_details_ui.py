from .entity_names import display_entity_names as _entity_label
"""Readable, scrollable move articles with offensive Gen III type coverage."""
from . import localized_tk as tk
import webbrowser
from .catalog import catalog,move
from .ui import BG,CARD,TEXT,MUTED,GREEN,BLUE,AMBER,Button,label,card
from .scrolling import Scrollbar
from .types_ui import TYPE_INFO,Badges
from .move_reference import power_text,accuracy_text,category_text,offensive_profile


class ArticleBody(tk.Frame):
    def __init__(self,parent):
        super().__init__(parent,bg=BG);self.pack(fill='both',expand=True)
        self.canvas=tk.Canvas(self,bg=BG,bd=0,highlightthickness=0);scroll=Scrollbar(self,command=self.canvas.yview);scroll.pack(side='right',fill='y');self.canvas.configure(yscrollcommand=scroll.set);self.canvas.pack(side='left',fill='both',expand=True)
        self.body=tk.Frame(self.canvas,bg=BG);self.item=self.canvas.create_window(0,0,window=self.body,anchor='nw');self.labels=[]
        self.body.bind('<Configure>',lambda _:self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>',self.resize)
    def resize(self,event):
        self.canvas.itemconfigure(self.item,width=event.width)
        for widget,margin in self.labels:widget.configure(wraplength=max(220,event.width-margin))
    def text(self,parent,text,size=12,color=TEXT,*,margin=12,**kw):
        widget=label(parent,text,size,color,wraplength=540,**kw);self.labels.append((widget,margin));return widget


def type_line(article,parent,title,types,color):
    if not types:return
    box=card(parent);box.pack(fill='x',pady=(0,6));label(box,title,11,color,bold=True)
    names=' · '.join(TYPE_INFO[t][0] for t in types)
    article.text(box,names,12,margin=36).pack_configure(pady=(5,0))


def show_move(panel,number):
    if hasattr(panel,'open_move'):return panel.open_move(number)
    from .pokemon_ui import detail_window
    m=move(number,panel.monitor.folder)
    if not m:return
    outer=detail_window(panel,'move','Приём · '+_entity_label(m['name']),730);outer.winfo_toplevel().minsize(540,480)
    return build_move(panel,number,outer)


def build_move(panel,number,outer):
    root=panel.monitor.folder;m=move(number,root)
    article=ArticleBody(outer);body=article.body;ref=m.get('reference',{})
    label(body,_entity_label(m['name']),25,bold=True)
    meta=tk.Frame(body,bg=BG);meta.pack(fill='x',pady=(6,14))
    variable=m.get('effect_name') in ('HIDDEN_POWER','WEATHER_BALL','NATURE_POWER')
    if variable:label(meta,'Тип зависит от '+('IV' if m['effect_name']=='HIDDEN_POWER' else 'погоды' if m['effect_name']=='WEATHER_BALL' else 'местности'),12,BLUE,pack=False).pack(side='left',padx=(0,12))
    elif m['type_id']==9:label(meta,'Без обычного типа',12,MUTED,pack=False).pack(side='left',padx=(0,12))
    else:
        badge=Badges(meta);badge.set([m['type_id']]);badge.pack(side='left')
    label(meta,category_text(m),12,MUTED,pack=False).pack(side='left',padx=6)
    article.text(body,m['description'],14,margin=10).pack_configure(pady=(0,16))
    metrics=tk.Frame(body,bg=BG);metrics.pack(fill='x',pady=(0,16));metrics.columnconfigure((0,1,2,3),weight=1,uniform='metrics')
    for i,(title,value) in enumerate([('СИЛА',power_text(m)),('ТОЧНОСТЬ',accuracy_text(m)),('PP',str(m['pp'])),('ПРИОРИТЕТ',f"{m['priority']:+d}")]):
        box=card(metrics);box.grid(row=0,column=i,sticky='nsew',padx=(0,6 if i<3 else 0));label(box,title,9,MUTED);label(box,value,14 if len(value)>7 else 19,bold=True).pack_configure(pady=(4,0))
    profile=offensive_profile(m,catalog(root)['effectiveness']);mode=profile['mode']
    label(body,'Против каких типов',14,bold=True).pack_configure(pady=(0,8))
    if mode=='standard':
        type_line(article,body,'Сильнее · ×2',profile['strong'],GREEN);type_line(article,body,'Слабее · ×½',profile['resisted'],AMBER);type_line(article,body,'Не действует · ×0',profile['immune'],MUTED)
        if not any(profile[k] for k in ('strong','resisted','immune')):article.text(body,'Обычный урон по всем типам.')
        article.text(body,'Для двух типов множители перемножаются: возможны ×4 и ×¼. Здесь показана атака по типам; способности и особые условия могут изменить результат.',10,MUTED,margin=12).pack_configure(pady=(4,14))
    else:
        explanations=dict(status='Не наносит прямого урона: преимущества ×2 и сопротивления ×½ к этому эффекту не применяются. Условия действия описаны ниже.',fixed='Количество отнятых HP задаётся особым правилом; преимущества и сопротивления типов его не умножают.',typeless='В FireRed этот приём не использует обычные множители типов, включая обычные типовые иммунитеты.',variable='Сначала определяется фактический тип приёма. Его нельзя надёжно описать одной постоянной таблицей эффективности.',ohko='При попадании сразу лишает сознания. Преимущество типа не увеличивает эффект; важны уровни, точность и защитные способности.',special='У этого приёма особые правила действия; обычная таблица урона может не описывать результат.')
        article.text(body,explanations[mode],12,margin=12).pack_configure(pady=(0,10))
        type_line(article,body,'Типовой иммунитет',profile['immune'],MUTED)
    label(body,'Как работает',14,bold=True).pack_configure(pady=(6,8))
    for text in ref.get('details',[]):article.text(body,text,12,margin=12).pack_configure(pady=(0,9))
    if mode=='standard':
        stat='Атаку пользователя и Защиту цели' if m['category']=='Physical' else 'Спец. атаку пользователя и Спец. защиту цели'
        article.text(body,'Использует '+stat+'. Совпадение типа приёма с типом пользователя обычно даёт ещё ×1,5 к урону.',11,MUTED).pack_configure(pady=(3,10))
    extra=[]
    if m['category']!='Status':extra.append('Физический контакт: '+('да' if m['flags']&1 else 'нет'))
    if m['priority']:extra.append('Приоритет выше 0 — раньше обычных атак; ниже 0 — позже')
    else:extra.append('При равном приоритете первым обычно ходит более быстрый Pokémon')
    article.text(body,' · '.join(extra)+'.',11,MUTED).pack_configure(pady=(4,10))
    article.text(body,'FireRed · поколение III. Числа взяты из игры; категория урона зависит от типа приёма.',10,MUTED).pack_configure(pady=(6,8))
    links=tk.Frame(body,bg=BG);links.pack(fill='x',pady=(0,8))
    Button(links,'Покедекс ↗',lambda:webbrowser.open(ref.get('dex_url','https://pokemondb.net/move/all')),variant='ghost').pack(side='left')
    source=catalog(root).get('move_reference',{}).get('sources',{}).get('pret',{}).get('url','https://github.com/pret/pokefirered')
    Button(links,'Механика FireRed ↗',lambda:webbrowser.open(source),variant='ghost').pack(side='left',padx=5)
    return article
