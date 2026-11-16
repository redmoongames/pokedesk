"""Version-aware offline Russian item reference and original 24-pixel sprites."""

from .paths import resource
from functools import lru_cache
import json
from . import localized_tk as tk
from pathlib import Path

@lru_cache
def items(root):
    from .telemetry import symbols,decode_text
    from .catalog import catalog
    from .editions import edition
    from .move_reference import category_text,power_text,accuracy_text
    from .types_ui import TYPE_INFO
    root=Path(root);records=json.loads((resource(root,'vendor/catalog/item-catalog.json')).read_text())['items']
    reference=json.loads((resource(root,'vendor/catalog/item-reference-ru.json')).read_text())['items']
    rom=(root/'Data/FireRed.gba').read_bytes();sy=symbols(root);table=sy['gItems']-0x8000000;result={};game=edition(root)
    tm=sy.get('sTMHMMoves',sy.get('gTMHMMoves',0))-0x8000000
    for entry in records:
        item=entry['id']
        if not item or '?' in entry['name']:continue
        raw=rom[table+44*item:table+44*item+44]
        if len(raw)!=44 or int.from_bytes(raw[14:16],'little')!=item:continue
        article=reference[str(item)];record=dict(entry,**article)
        name=decode_text(raw[:14]);ptr=int.from_bytes(raw[20:24],'little')-0x8000000
        record.update(name=name,description_en=decode_text(rom[ptr:ptr+700]) if 0<=ptr<len(rom) else '',price=int.from_bytes(raw[16:18],'little'),pocket_id=raw[26],holdable=not raw[24] and bool(item))
        if game.family=='hoenn':record.update(available_firered=True,availability_note='Предмет '+game.label)
        if 289<=item<=346 and 0<=tm<len(rom):
            move_id=int.from_bytes(rom[tm+2*(item-289):tm+2*(item-288)],'little');move=catalog(root)['moves'].get(str(move_id))
            if move:
                record.update(move_id=move_id,title=article['title']+' · '+move['name'].title())
                teach='TM расходуется при успешном обучении; повторный экземпляр нужен для другого покемона.' if item<=338 else 'HM не расходуется. Забыть HM-приём можно у удалителя приёмов; применение вне боя требует соответствующего допуска и значка.'
                record['description']='Обучает совместимого покемона приёму '+move['name'].title()+'. '+move['description']+' '+ ' '.join(move.get('reference',{}).get('details',[]))+'\n'+f"Тип: {TYPE_INFO[move['type_id']][0]} · {category_text(move)} · сила: {power_text(move)} · точность: {accuracy_text(move)} · PP: {move['pp']}.\n"+teach
        result[item]=record
    return result

def item_icon(master,root,item_id,scale=2):
    owner=master._root();cache=getattr(owner,'_item_sprites',None)
    if cache is None:cache={};owner._item_sprites=cache
    key=(str(root),item_id,scale)
    if key not in cache:
        path=resource(root,f'assets/items/{item_id}.png')
        if not path.is_file():path=resource(root,'assets/items/0.png')
        photo=tk.PhotoImage(master=owner,file=str(path));cache[key]=photo.zoom(scale) if scale!=1 else photo
    return cache[key]
