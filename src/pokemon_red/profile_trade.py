"""Closed-profile exchanges: isolated cores and a recoverable two-sided commit.

No live session is taken over. Commit intent is durable before either original
changes; reopening either profile first completes a pending paired publication.
"""

from .paths import bind_installation
from contextlib import contextmanager
from pathlib import Path
import fcntl,hashlib,json,shutil,time,uuid,os
from .profiles import Profiles
from .editions import edition,rom_sha1
from .acquisition import read_json,write_json
from .persistence import SaveSnapshot,publish_checkpoint,sync_directory,atomic_bytes

def hashes(folder):
    return {n:hashlib.sha256((Path(folder)/'Data'/n).read_bytes()).hexdigest() if (Path(folder)/'Data'/n).exists() else None for n in ('FireRed.state','FireRed.sav')}

def rows_for(library,identifiers):
    store=Profiles(library);by_id={r['id']:r for r in store.list()}
    if len(identifiers)!=2 or len(set(identifiers))!=2 or any(i not in by_id for i in identifiers):raise ValueError('Выберите два разных прохождения')
    return [dict(by_id[i],folder=store.folder(by_id[i])) for i in identifiers]

@contextmanager
def locks(rows):
    handles=[]
    try:
        for row in sorted(rows,key=lambda r:str(r['folder'])):
            handle=(row['folder']/'Data/.session.lock').open('a');handles.append(handle)
            try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError as error:raise RuntimeError('Прохождение «'+row['name']+'» открыто. Сначала вернитесь в меню из его окна.') from error
        yield
    finally:
        for handle in reversed(handles):handle.close()

def clone(source,target):
    (target/'Data').mkdir(parents=True)
    bind_installation(target,source)
    (target/'Data/FireRed.gba').symlink_to(os.path.relpath((source/'Data/FireRed.gba').resolve(),(target/'Data').resolve()))
    write_json(target/'Data/game.json',dict(game=edition(source).id))
    for name in ('FireRed.state','FireRed.sav'):
        path=source/'Data'/name
        if path.exists():shutil.copyfile(path,target/'Data'/name)

def folder_for(library,key):
    if not isinstance(key,str) or len(key)!=32 or any(c not in '0123456789abcdef' for c in key):raise ValueError('Некорректный обмен')
    return Path(library)/'Sessions/profile-trades'/key

def pending(library,identifier=None):
    found=[]
    for path in (Path(library)/'Sessions/profile-trades').glob('*/journal.json'):
        row=read_json(path,{})
        if row.get('commit_intent') and row.get('status')!='committed' and (identifier is None or identifier in row.get('profiles',[])):found.append(path.parent.name)
    return found

def snapshot_at(folder):
    meta=read_json(folder/'snapshot.json',{})
    for name,digest in meta.get('files',{}).items():
        if name not in ('FireRed.state','FireRed.sav','summary.json','preview.png') or hashlib.sha256((folder/name).read_bytes()).hexdigest()!=digest:raise RuntimeError('Повреждена подготовленная сторона обмена')
    if not {'FireRed.state','FireRed.sav'}<=meta.get('files',{}).keys():raise RuntimeError('Неполная подготовленная сторона обмена')
    return SaveSnapshot((folder/'FireRed.state').read_bytes(),(folder/'FireRed.sav').read_bytes(),meta['frame'],meta['captured_at'],(folder/'summary.json').read_bytes(),(folder/'preview.png').read_bytes())

def stage_snapshot(snapshot,folder):
    snapshot.publish(folder)
    atomic_bytes(folder/'summary.json',snapshot.summary,durable=True);atomic_bytes(folder/'preview.png',snapshot.preview,durable=True)
    write_json(folder/'snapshot.json',dict(frame=snapshot.frame,captured_at=snapshot.captured_at,files={n:hashlib.sha256((folder/n).read_bytes()).hexdigest() for n in ('FireRed.state','FireRed.sav','summary.json','preview.png')}))
    sync_directory(folder)

def commit(library,key,rows,journal):
    """Locks are held by caller. May be retried after either publication failed."""
    folder=folder_for(library,key);snapshots=[snapshot_at(folder/f'after-{i}') for i in range(2)]
    for i,row in enumerate(rows):
        if edition(row['folder']).id!=journal['games'][i]:raise RuntimeError('Игра прохождения изменилась во время обмена')
        final={n:hashlib.sha256(blob).hexdigest() for n,blob in (('FireRed.state',snapshots[i].state),('FireRed.sav',snapshots[i].sram))}
        # A crash can occur between SRAM and state publication. Each component
        # must be either the old or the prepared value; no unrelated overwrite.
        current=hashes(row['folder'])
        if any(current[n] not in (journal['before'][i][n],final[n]) for n in final):raise RuntimeError('Сохранение изменилось вне обмена; обе резервные копии сохранены')
    for i,row in enumerate(rows):
        publish_checkpoint(snapshots[i],row['folder']/'Data',rom_sha1(row['folder']),backup=True)
        journal['published']=i+1;write_json(folder/'journal.json',journal)
    journal.update(status='committed',completed_at=time.time());write_json(folder/'journal.json',journal)
    return dict(id=key,profiles=journal['profiles'],backup=[str(row['folder']/'Data/backups/actions'/('profile-trade-'+key)) for row in rows])

def recover(library,key):
    folder=folder_for(library,key);journal=read_json(folder/'journal.json',{})
    if not journal.get('commit_intent') or journal.get('status')=='committed':return None
    rows=rows_for(library,journal['profiles'])
    with locks(rows):return commit(library,key,rows,journal)

def recover_all(library):
    errors=[]
    for key in pending(library):
        try:recover(library,key)
        except Exception as error:errors.append(str(error))
    return errors

def inspect(library,identifiers):
    """Runs on a worker. UI receives detached party/PC records and fingerprints."""
    from tempfile import TemporaryDirectory
    from .engine import Game
    from .models import read_inventory
    rows=rows_for(library,identifiers);result=[]
    with locks(rows),TemporaryDirectory(prefix='Pokemon trade preview ') as tmp:
        for i,row in enumerate(rows):
            if pending(library,row['id']):raise RuntimeError('Сначала нужно завершить восстановление предыдущего обмена')
            target=Path(tmp)/str(i);clone(row['folder'],target)
            with Game(target) as game:
                inventory=read_inventory(game)
                if not inventory.get('ready'):raise ValueError('Сначала начните игру и сохраните прохождение «'+row['name']+'»')
                result.append(dict(id=row['id'],game=edition(row['folder']).name,name=row['name'],inventory=inventory,fingerprint=hashes(row['folder'])))
    return result

def exchange(library,identifiers,uids,expected,*,roundtrip=False,progress=lambda text:None):
    from .engine import Game
    from .journey import Journey
    from .models import read_inventory
    from .trade import perform_trade
    library=Path(library).resolve();rows=rows_for(library,identifiers);key=uuid.uuid4().hex;folder=folder_for(library,key)
    class Worker:
        def heartbeat(self):pass
        def safe_point(self):pass
        def event(self,*args):pass
        def update(self,**values):progress(values.get('stage','Обмен'))
    worker=Worker()
    with locks(rows):
        if len(uids)!=2 or len(expected)!=2:raise ValueError('Выберите Pokémon с обеих сторон')
        if any(pending(library,row['id']) for row in rows):raise RuntimeError('Не завершён предыдущий обмен')
        before=[hashes(row['folder']) for row in rows]
        if before!=expected:raise RuntimeError('Сохранение изменилось после выбора Pokémon. Обновите список.')
        folder.mkdir(parents=True)
        journal=dict(id=key,profiles=list(identifiers),games=[edition(r['folder']).id for r in rows],before=before,uids=list(uids),roundtrip=bool(roundtrip),status='preparing',commit_intent=False,created_at=time.time())
        write_json(folder/'journal.json',journal)
        try:
            for i,row in enumerate(rows):clone(row['folder'],folder/str(i))
            with Game(folder/'0') as a,Game(folder/'1') as b:
                games=(a,b)
                from .trade_adapters import preflight
                reasons=preflight(a,b)
                if reasons:raise ValueError('\n'.join(reasons))
                for i,game in enumerate(games):
                    inv=read_inventory(game);owned=inv['party']+inv['boxes']
                    if uids[i] not in {m['uid'] for m in owned} or len(owned)<2:raise ValueError('На каждой стороне нужны выбранный Pokémon и хотя бы один запасной')
                    snap=game.capture_save();backup=rows[i]['folder']/'Data/backups/actions'/('profile-trade-'+key);stage_snapshot(snap,backup)
                    progress('Готовим '+edition(game.root).name+' к обмену')
                    p=Journey(game,worker);p.center();p.ensure_party(uids[i])
                    if len(p.state()['party'])<2:p.ensure_party(next(m['uid'] for m in owned if m['uid']!=uids[i]))
                    p.heal();p.save_game()
                received=perform_trade(a,b,uids[0],uids[1],worker)
                if roundtrip:perform_trade(a,b,uids[1],uids[0],worker)
                for i,game in enumerate(games):stage_snapshot(game.capture_save(),folder/f'after-{i}')
            if [hashes(r['folder']) for r in rows]!=before:raise RuntimeError('Исходные сохранения изменились; результат оставлен в отдельных копиях')
            journal.update(status='committing',commit_intent=True);write_json(folder/'journal.json',journal)
            result=commit(library,key,rows,journal);result['received']=received;return result
        except Exception as error:
            journal.update(status='recovery_required' if journal['commit_intent'] else 'failed',error=str(error));write_json(folder/'journal.json',journal);raise
