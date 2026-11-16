"""Verified reusable donors shared by a library's playthroughs."""

from .paths import session_paths
from pathlib import Path
import fcntl,time,os
from .acquisition import read_json,write_json
from .engine import ROOT

POCKETS={1:('items',42),2:('key',30),3:('balls',13),4:('tmhm',58),5:('berries',43)}

def library_root(project):
    project=Path(project).resolve()
    return session_paths(project).library

def registry(project):return library_root(project)/'Sessions/item-sources/catalog.json'

def provider(project,item):
    row=read_json(registry(project),{}).get(str(item))
    if not row:return None
    path=Path(row.get('template',''))
    if path.is_absolute() or '..' in path.parts or not str(path).startswith('Sessions/item-sources/'):raise ValueError('Некорректный путь донора предметов')
    return dict(row,directory=library_root(project)/path)

def generic_product(item,project=None):
    from .item_catalog import items
    root=Path(project) if project else ROOT
    if type(item) is not int or not 1<=item<=374:raise ValueError('Неизвестный предмет')
    info=items(root).get(item)
    if not info or not info['holdable'] or 121<=item<=132 or item==5:raise ValueError('Этот предмет нельзя автоматически передать с Pokémon')
    pocket,capacity=POCKETS[info['pocket_id']]
    row=dict(title=info['title']+' · '+info['name'].title(),name=info['name'].title(),pocket=pocket,capacity=capacity,hint=info['description'],source='Копия вашего прохождения')
    if project:
        source=provider(project,item)
        if source:row.update(source,template=source['template'])
    return row

def bag_quantity(inventory,item):return sum(r['quantity'] for r in inventory.get('items',[]) if r['id']==item and r['pocket']!='pc')

def can_prepare(project,item,inventory):
    from .editions import edition
    if edition(project).family=='hoenn':return 'Создание донора предметов пока проверено только в FireRed и LeafGreen'
    try:info=generic_product(item,project)
    except ValueError as e:return str(e)
    if info['pocket']=='berries':return 'Передача ягод через мешочек пока не поддерживается'
    if bag_quantity(inventory,item)<1:return 'Нужен хотя бы один экземпляр в сумке для создания донора'
    return None

def register(project,item,folder,donor_uid,stock,game):
    library=library_root(project);folder=Path(folder).resolve();relative=folder.relative_to(library)
    destination=registry(project);destination.parent.mkdir(parents=True,exist_ok=True)
    with (destination.parent/'.catalog.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        rows=read_json(destination,{});rows[str(item)]=dict(template=str(relative),donor_uid=donor_uid,stock=stock,game=game,created_at=time.time(),source='Копия прохождения · запас '+str(stock))
        write_json(destination,rows)

def clone_donor(project,template,target):
    from .operations import clone_session
    from .persistence import SaveSnapshot
    from .editions import rom_path
    library=library_root(project);template=Path(template);meta=read_json(template/'metadata.json',{});game=meta.get('game','firered')
    snapshot=SaveSnapshot((template/'FireRed.state').read_bytes(),(template/'FireRed.sav').read_bytes(),0,time.time())
    result=clone_session(library,target,snapshot)
    if game!='firered':
        (result/'Data/FireRed.gba').unlink();(result/'Data/FireRed.gba').symlink_to(os.path.relpath(rom_path(library,game).resolve(),(result/'Data').resolve()));write_json(result/'Data/game.json',dict(game=game))
    return result

def availability(project,item,inventory):
    """Cheap UI hint; the worker verifies hashes before using any donor."""
    from .editions import edition
    if edition(project).family=='hoenn':return False,'Автосбор предметов пока проверен только в FireRed и LeafGreen'
    from .item_delivery import PRODUCTS
    try:generic_product(item,project)
    except ValueError as error:return False,str(error)
    source=provider(project,item)
    template=source['directory'] if source else library_root(project)/PRODUCTS[item]['template'] if item in PRODUCTS else None
    if template and (template/'manifest.json').is_file():return True,'Готовый донор · исходный запас восстанавливается после каждой доставки'
    reason=can_prepare(project,item,inventory)
    return (False,reason) if reason else (True,'Донор будет создан из копии текущего прохождения · нужен один предмет в сумке')


def courier_conflicts(project,item):
    from .item_delivery import PRODUCTS
    source=provider(project,item)
    template=source['directory'] if source else library_root(project)/PRODUCTS[item]['template'] if item in PRODUCTS else None
    if not template:return set()
    path=template/'metadata.json'
    if not path.is_file():return set()
    return _source_uids(str(path),path.stat().st_mtime_ns)

from functools import lru_cache
@lru_cache(maxsize=64)
def _source_uids(path,modified):
    return frozenset(m['uid'] for m in read_json(Path(path),{}).get('state',{}).get('party',[]) if m.get('uid'))
