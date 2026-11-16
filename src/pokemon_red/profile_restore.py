"""Validate and restore a profile checkpoint before opening its live session."""
from pathlib import Path
from datetime import datetime,timezone
import fcntl,json,os,uuid
from .engine import Game,ROM_SHA1
from .slots import Slots
from .editions import rom_sha1
from .persistence import atomic_bytes,publish_checkpoint,sync_directory
from .save_timeline import SaveTimeline,digest

def restore_profile(folder,record):
    folder=Path(folder);data=folder/'Data'
    with (data/'.session.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as error:raise RuntimeError('Это прохождение уже открыто. Сначала вернись в меню из его окна.') from error
        slots=Slots(folder)
        candidate=slots.prepare_backup(record['directory']) if record.get('is_backup') else slots.prepare_load(record['id'])
        with candidate:
            snapshot=candidate.capture_save()
        backup=None;current=data/'FireRed.state'
        if current.is_file() or (data/'FireRed.sav').is_file():
            # Preserve the exact old commit, even if its sidecar is missing.
            info=SaveTimeline(data).current() or {}
            if current.is_file():raw=current.read_bytes()
            else:
                with Game(folder,resume=False) as previous:
                    if not previous.lib.pokemon_load_save(previous.handle,os.fsencode(data/'FireRed.sav')):raise RuntimeError('Не удалось сохранить текущую картриджную сессию')
                    raw=previous.capture_save(metadata=False).state
            backup=data/'backups/actions'/('menu-restore-'+uuid.uuid4().hex)
            metadata=dict(name='Перед загрузкой из меню',created_at=datetime.now(timezone.utc).isoformat(),rom_sha1=rom_sha1(folder),
                          summary=info.get('summary'),telemetry=info.get('summary'),sha256=digest(raw))
            atomic_bytes(backup/'FireRed.state',raw,durable=True)
            if (data/'FireRed.sav').is_file():atomic_bytes(backup/'FireRed.sav',(data/'FireRed.sav').read_bytes(),durable=True)
            preview=data/'save-preview.png'
            if preview.is_file():
                image=preview.read_bytes()
                if digest(image)==info.get('preview_sha256'):atomic_bytes(backup/'preview.png',image,durable=True)
            atomic_bytes(backup/'metadata.json',json.dumps(metadata,ensure_ascii=False).encode(),durable=True)
            sync_directory(backup.parent);sync_directory(backup.parent.parent);sync_directory(data)
        publish_checkpoint(snapshot,data,rom_sha1(folder))
        return dict(frame=snapshot.frame,backup=backup)
