"""Independent playthrough roots; legacy Data stays in place during migration."""

from .paths import bind_installation
from pathlib import Path
from datetime import datetime,timezone
import fcntl,json,os,shutil,uuid
from contextlib import contextmanager
from .persistence import atomic_bytes,sync_directory
from .save_timeline import SaveTimeline,read_json,digest
from .editions import EDITIONS,edition_id,rom_path,available,validate_rom
from .i18n import t

LEGACY='00000000000000000000000000000001'

class Profiles:
    def __init__(self,root):
        self.root=Path(root).resolve();self.path=self.root/'Data/profiles.json'
    def list(self,*,deleted=False):
        with self._lock():return [r for r in self._read() if bool(r.get('deleted_at'))==deleted]
    def get(self,identifier):
        with self._lock():return dict(self._find(self._read(),identifier))
    @staticmethod
    def _find(rows,identifier,*,deleted=False):
        row=next((r for r in rows if r['id']==identifier and bool(r.get('deleted_at'))==deleted),None)
        if row is None:raise ValueError(t('sessions.missing'))
        return row
    @contextmanager
    def _lock(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.path.with_suffix('.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            yield
    def _read(self):
        try:data=json.loads(self.path.read_text())
        except FileNotFoundError:
            data=dict(format=1,profiles=[dict(id=LEGACY,name='Прохождение 1',root='.')])
            self._write(data['profiles'])
        except (ValueError,UnicodeError) as error:raise ValueError('Повреждён список прохождений. Сохранения остаются на диске.') from error
        if not isinstance(data,dict) or data.get('format')!=1 or not isinstance(data.get('profiles'),list):raise ValueError('Повреждён список прохождений. Данные сохранений остаются на диске.')
        for row in data['profiles']:
            self.folder(row);row.setdefault('game','firered');edition_id(row['game'])
        return data['profiles']
    def _write(self,rows):atomic_bytes(self.path,json.dumps(dict(format=1,profiles=rows),ensure_ascii=False,indent=2).encode(),durable=True)
    def folder(self,row):
        identifier=row.get('id','')
        if len(identifier)!=32 or any(c not in '0123456789abcdef' for c in identifier):raise ValueError('Некорректный идентификатор прохождения')
        rel='.' if identifier==LEGACY else 'Profiles/'+identifier
        if row.get('root')!=rel:raise ValueError('Некорректный путь прохождения')
        folder=(self.root/rel).resolve()
        if folder!=self.root and not folder.is_relative_to((self.root/'Profiles').resolve()):raise ValueError('Путь прохождения находится вне проекта')
        return folder
    def create(self,name=None,*,game='firered',prologue=None):
        edition_id(game)
        if prologue is not None:
            from .new_game_config import NewGameConfig
            prologue=NewGameConfig.parse(prologue,game).json()
        if game!='firered':
            if not available(self.root,game):raise ValueError('Сначала подключите локальный ROM '+EDITIONS[game].label)
            validate_rom(rom_path(self.root,game).read_bytes(),game)
        with self._lock():return self._create(name,game,prologue)
    def _create(self,name=None,game='firered',prologue=None,*,populate=None):
        rows=self._read();identifier=uuid.uuid4().hex;row=dict(id=identifier,name=(name or f'Прохождение {len(rows)+1}').strip()[:64],root='Profiles/'+identifier,game=game)
        folder=self.folder(row);(folder/'Data').mkdir(parents=True)
        try:
            bind_installation(folder,self.root,kind='profile')
            (folder/'Data/FireRed.gba').symlink_to(os.path.relpath(rom_path(self.root,game),folder/'Data'))
            atomic_bytes(folder/'Data/game.json',json.dumps(dict(game=game,rom_sha1=EDITIONS[game].sha1)).encode(),durable=True)
            if prologue is not None:
                atomic_bytes(folder/'Data/new-game.json',json.dumps(dict(config=prologue,status='pending',progress=dict(phase='intro',attempts=0))).encode(),durable=True)
            settings=self.root/'Data/settings.json'
            if settings.is_file():shutil.copy2(settings,folder/'Data/settings.json')
            # A progressed hunting template belongs to its trainer, not a new save.
            source=self.root/'templates'/EDITIONS[game].name/'ALEX-before-starter-v1'
            if source.is_dir():shutil.copytree(source,folder/'templates'/EDITIONS[game].name/'ALEX-before-starter-v1')
            if populate is not None:populate(folder)
            for directory in (folder/'Data',folder,folder.parent):sync_directory(directory)
            self._write(rows+[row])
        except BaseException:
            shutil.rmtree(folder);raise
        return row
    def rename(self,identifier,name):
        name=name.strip()
        if not name or len(name)>64:raise ValueError('Название должно содержать от 1 до 64 символов')
        with self._lock():
            rows=self._read();row=self._find(rows,identifier);row['name']=name;self._write(rows)
    @contextmanager
    def _available(self,row):
        """Hold the same lock as the owner, restore and exchange until publication."""
        with (self.folder(row)/'Data/.session.lock').open('a') as lock:
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError as error:raise RuntimeError(t('sessions.busy')) from error
            from .profile_trade import pending
            if pending(self.root,row['id']):raise RuntimeError(t('sessions.pending_trade'))
            yield
    def archive(self,identifier):
        # A durable tombstone is reversible even for the legacy profile whose
        # Data also contains the shared ROM and application preferences.
        with self._lock():
            rows=self._read();row=self._find(rows,identifier)
            with self._available(row):
                row['deleted_at']=datetime.now(timezone.utc).isoformat();self._write(rows)
        return dict(row)
    def restore(self,identifier):
        with self._lock():
            rows=self._read();row=self._find(rows,identifier,deleted=True)
            with self._available(row):
                del row['deleted_at'];self._write(rows)
        return dict(row)
    def duplicate(self,identifier,name):
        """Publish a new profile only after all closed-save payloads are durable.

        Save history and preferences belong to the copy. Runtime jobs, analytics,
        locks, caches and global profile registry do not. Shared assets remain
        relative links created by _create, including when copying legacy Data.
        """
        name=name.strip()
        if not name or len(name)>64:raise ValueError(t('sessions.invalid_name'))
        with self._lock():
            row=self._find(self._read(),identifier);source=self.folder(row)/'Data'
            with self._available(row):
                def populate(folder):
                    target=folder/'Data'
                    paths=[source/n for n in ('FireRed.state','FireRed.sav','save-info.json','save-preview.png','settings.json','new-game.json','starter-best.json','starter-best.state','starter-candidates.json','starter-frontier.state','starter-frontier.sav','starter-frontier.json','training.json')]
                    for directory in ('slots','rewind','backups','starter-candidates'):
                        base=source/directory
                        if base.is_symlink():raise ValueError(t('sessions.unsafe_copy'))
                        if base.exists():paths.extend([base,*base.rglob('*')])
                    for path in paths:
                        if path.is_symlink():raise ValueError(t('sessions.unsafe_copy'))
                        if not path.exists():continue
                        destination=target/path.relative_to(source)
                        if path.is_dir():destination.mkdir(parents=True,exist_ok=True)
                        elif path.is_file():atomic_bytes(destination,path.read_bytes(),durable=True)
                        else:raise ValueError(t('sessions.unsafe_copy'))
                    for directory in sorted((d for d in target.rglob('*') if d.is_dir()),key=lambda d:len(d.parts),reverse=True):sync_directory(directory)
                return self._create(name,row.get('game','firered'),populate=populate)
    def busy(self,row):
        path=self.folder(row)/'Data/.session.lock'
        with path.open('a') as lock:
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:return True
        from .profile_trade import pending
        return bool(pending(self.root,row['id']))
    def summary(self,row):
        folder=self.folder(row);timeline=SaveTimeline(folder/'Data');metadata=timeline.current();busy=self.busy(row)
        if metadata is None and busy:return dict(row,metadata=dict(summary=None,captured_at=None),preview=b'',busy=True)
        if metadata is None:
            # Read an independent core on this worker, never the running session.
            if (folder/'Data/FireRed.state').is_file() or (folder/'Data/FireRed.sav').is_file():
                from .engine import Game
                with Game(folder) as game:
                    from .save_metadata import capture
                    game.advance(1)
                    summary,image=capture(game)
                    stamp=(folder/'Data/FireRed.state').stat().st_mtime if (folder/'Data/FireRed.state').exists() else (folder/'Data/FireRed.sav').stat().st_mtime
                    metadata=dict(summary=json.loads(summary),captured_at=stamp,created_at=datetime.fromtimestamp(stamp,timezone.utc).isoformat())
                    return dict(row,metadata=metadata,preview=image,busy=busy)
            metadata=dict(summary=None,captured_at=None)
        image=b'';preview=folder/'Data/save-preview.png'
        if preview.is_file():
            raw=preview.read_bytes()
            if digest(raw)==metadata.get('preview_sha256'):image=raw
        return dict(row,metadata=metadata,preview=image,busy=busy)
