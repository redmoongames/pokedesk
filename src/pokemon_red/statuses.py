from .entity_names import pokemon_name
"""FireRed status reference used by cards, live details and the shared catalog."""
STATUS_RULES={
 'paralysis':dict(name='Паралич',glyph='ϟ',color='#efd47c',description='Скорость снижается до ¼ обычной. В каждом ходу есть 25% вероятности, что Pokémon не сможет выполнить приём. Лечение: Pokémon Center, Parlyz Heal и подходящие ягоды/приёмы.'),
 'poison':dict(name='Отравление',glyph='☠',color='#c58ae6',description='В конце хода теряется ⅛ максимального HP (не меньше 1). В FireRed отравление также отнимает HP при ходьбе и может привести к потере сознания. Лечение: Pokémon Center, Antidote и подходящие ягоды/приёмы.'),
 'toxic':dict(name='Сильное отравление',glyph='☠',color='#d39cf0',description='Урон в бою нарастает: 1/16, 2/16, 3/16 максимального HP и далее. Переключение сбрасывает счётчик. Лечение: Pokémon Center, Antidote и подходящие ягоды/приёмы.'),
 'burn':dict(name='Ожог',glyph='♨',color='#ed9a71',description='В конце хода теряется ⅛ максимального HP. Обычный физический урон уменьшается вдвое; Guts отменяет этот штраф. Лечение: Pokémon Center, Burn Heal и подходящие ягоды/приёмы.'),
 'freeze':dict(name='Заморозка',glyph='❄',color='#8dd5e7',description='Обычные действия заблокированы до оттаивания. Каждый ход есть 20% вероятности оттаять; некоторые огненные атаки и особые приёмы тоже снимают заморозку. Лечение: Pokémon Center, Ice Heal и подходящие ягоды/приёмы.'),
 'sleep':dict(name='Сон',glyph='Zz',color='#a6b3e9',description='Обычные приёмы недоступны до пробуждения. Некоторые приёмы, например Sleep Talk и Snore, работают во сне. Лечение: Pokémon Center, Awakening и подходящие ягоды/приёмы.'),
 'fainted':dict(name='Без сознания',glyph='×',color='#f29498',description='HP равен нулю. Pokémon не может сражаться и не получает XP за победу. Восстановление: Pokémon Center, Revive или другой подходящий предмет.')}

def status_key(mon):
    if mon.get('hp',1)<=0:return 'fainted'
    value=mon.get('status_code',0)
    if value&7:return 'sleep'
    if value&0x80:return 'toxic'
    if value&8:return 'poison'
    if value&0x10:return 'burn'
    if value&0x20:return 'freeze'
    if value&0x40:return 'paralysis'
    return {'Сон':'sleep','Отравление':'poison','Ожог':'burn','Заморозка':'freeze','Паралич':'paralysis','Без сознания':'fainted'}.get(mon.get('status'))

def status_info(mon,folder=None):
    key=status_key(mon)
    if key is None:return None
    if folder is not None:
        from .catalog import catalog
        return catalog(folder)['mechanics']['statuses'].get(key)
    return STATUS_RULES.get(key)

def show_status(master,mon,folder=None):
    from . import localized_tk as tk
    from .ui import BG,MUTED,label
    key=status_key(mon)
    if not key:return
    # Same versioned entry is persisted in the portable reference database.
    info=status_info(mon,folder);root=master._root();window=getattr(root,'_status_popup',None)
    if window is None or not window.winfo_exists():window=tk.Toplevel(master);root._status_popup=window;window.geometry('480x310');window.configure(bg=BG);window.minsize(420,260)
    for child in window.winfo_children():child.destroy()
    window.title('Статус · '+info['name']);body=tk.Frame(window,bg=BG,padx=20,pady=18);body.pack(fill='both',expand=True)
    label(body,info['glyph']+'  '+info['name'],22,info['color'],bold=True);label(body,pokemon_name(mon),11,MUTED).pack_configure(pady=(5,16));label(body,info['description'],13,wraplength=430);label(body,'Правила FireRed · поколение III',10,MUTED).pack_configure(pady=(16,0));window.deiconify();window.lift()
