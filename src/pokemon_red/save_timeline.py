"""Compressed, time-based rollback of committed saves; writer-thread only.

FireRed.state remains the authoritative commit. Sidecar metadata is accepted
only when its SHA-256 matches that file. Failed staging never rotates history.
"""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,logging,math,shutil,time,uuid,zlib
from .persistence import atomic_bytes,sync_directory

AGES=(5,15,30,60,300,600,1800)
LABELS={5:'5 секунд',15:'15 секунд',30:'30 секунд',60:'1 минута',300:'5 минут',600:'10 минут',1800:'30 минут'}
MAX_STATE=16*1024*1024

def digest(data):return hashlib.sha256(data).hexdigest()
def verify_snapshot(snapshot, data):
    """Accept detached snapshots captured by earlier loaded SDK classes too."""
    for name, expected in (('FireRed.state',snapshot.state),('FireRed.sav',snapshot.sram)):
        if digest((Path(data)/name).read_bytes())!=digest(expected):
            raise OSError(f'Не подтверждена запись {name}; игра остаётся открытой')

def read_json(path):
    try:return json.loads(Path(path).read_text())
    except (OSError,ValueError):return None

class SaveTimeline:
    def __init__(self,data):self.data=Path(data);self.folder=self.data/'rewind'
    def current(self,*,verify=True):
        row=read_json(self.data/'save-info.json')
        if not isinstance(row,dict):return None
        try:
            if not math.isfinite(float(row['captured_at'])) or not math.isfinite(float(row.get('history_time',0))) or row.get('history_time',0)<0:return None
            if row.get('summary') is not None and not isinstance(row['summary'],dict):return None
            if verify and digest((self.data/'FireRed.state').read_bytes())!=row['sha256']:return None
        except (OSError,KeyError,ValueError,TypeError):return None
        return dict(row,directory=self.data,is_current=True,state_path=self.data/'FireRed.state')
    def records(self):
        result=[]
        for f in self.folder.glob('*/metadata.json'):
            if f.parent.is_symlink():continue
            row=read_json(f)
            if not isinstance(row,dict):continue
            try:
                if not math.isfinite(float(row['captured_at'])) or not math.isfinite(float(row.get('history_time',0))):continue
                if not isinstance(row['sha256'],str) or len(row['sha256'])!=64 or not isinstance(row['rom_sha1'],str):continue
                if not (f.parent/'state.z').is_file():continue
            except (KeyError,TypeError,ValueError):continue
            result.append(dict(row,directory=f.parent,is_backup=True,id='rewind-'+f.parent.name,state_path=f.parent/'state.z'))
        return sorted(result,key=lambda r:r['captured_at'],reverse=True)
    def archive(self,state,rom_sha1):
        sha=digest(state);old=self.current(verify=False)
        if not old or old.get('sha256')!=sha:
            stamp=(self.data/'FireRed.state').stat().st_mtime
            old=dict(captured_at=stamp,created_at=datetime.fromtimestamp(stamp,timezone.utc).isoformat(),summary=None,frame=None,history_time=0)
        # Retry after a failed write must not create another copy of the commit.
        folder=self.folder/(str(int(old['captured_at']*1_000_000))+'-'+sha[:16])
        if (folder/'metadata.json').is_file():return
        stage=self.folder/('.pending-'+uuid.uuid4().hex);stage.mkdir(parents=True)
        try:
            metadata={k:v for k,v in old.items() if k not in ('directory','state_path','is_current','is_backup','id')}
            metadata.update(name='Автосохранение',rom_sha1=rom_sha1,sha256=sha,state_size=len(state))
            atomic_bytes(stage/'state.z',zlib.compress(state,1),durable=True)
            preview=self.data/'save-preview.png'
            if preview.is_file():
                image=preview.read_bytes()
                if digest(image)==old.get('preview_sha256'):atomic_bytes(stage/'preview.png',image,durable=True)
            atomic_bytes(stage/'metadata.json',json.dumps(metadata,ensure_ascii=False).encode(),durable=True)
            stage.rename(folder);sync_directory(self.folder);sync_directory(self.data)
        finally:
            if stage.exists():shutil.rmtree(stage)
    def describe(self,snapshot,rom_sha1,*,captured_at=None,history_time=0):
        stamp=snapshot.captured_at if captured_at is None else captured_at
        try:summary=json.loads(snapshot.summary) if snapshot.summary else None
        except ValueError:summary=None
        row=dict(name='Актуальное автосохранение',captured_at=stamp,created_at=datetime.fromtimestamp(stamp,timezone.utc).isoformat(),frame=snapshot.frame,rom_sha1=rom_sha1,sha256=digest(snapshot.state),summary=summary,
                 history_time=history_time,producer=snapshot.producer,active_seconds=snapshot.active_seconds)
        if snapshot.preview:
            atomic_bytes(self.data/'save-preview.png',snapshot.preview,durable=True);row['preview_sha256']=digest(snapshot.preview)
        atomic_bytes(self.data/'save-info.json',json.dumps(row,ensure_ascii=False).encode(),durable=True)
    def prune(self,anchor):
        rows=self.records();rows.sort(key=lambda r:r.get('history_time',0),reverse=True);keep={r['id'] for r in rows if r.get('history_time',0)>=anchor-max(AGES)}
        oldest=next((r for r in rows if r.get('history_time',0)<=anchor-max(AGES)),None)
        if oldest:keep.add(oldest['id'])
        if len(keep)>512:
            anchors={r['id'] for age in AGES if (r:=next((r for r in rows if r.get('history_time',0)<=anchor-age),None))}
            keep=anchors|{r['id'] for r in rows[:512-len(anchors)]}
        for row in rows:
            if row['id'] not in keep:shutil.rmtree(row['directory'])
    def anchors(self):
        current=self.current();records=self.records()
        if not current:return [(age,None) for age in AGES]
        stamp=current.get('history_time',0);records=[r for r in records if r['sha256']!=current['sha256']];records.sort(key=lambda r:r.get('history_time',0),reverse=True)
        # The capture timer has small scheduling jitter. A 4.99-second-old
        # checkpoint is the 5-second point, rather than jumping back 10 seconds.
        return [(age,next((dict(r,age_seconds=stamp-r.get('history_time',0)) for r in records if r.get('history_time',0)<=stamp-age+.25),None)) for age in AGES]
    @staticmethod
    def restore_bytes(directory,rom_sha1):
        directory=Path(directory);row=read_json(directory/'metadata.json')
        if not row or row.get('rom_sha1')!=rom_sha1:raise ValueError('Копия создана для другой версии игры')
        raw=(directory/'state.z').read_bytes()
        if len(raw)>MAX_STATE:raise ValueError('Повреждённая резервная копия')
        try:
            decoder=zlib.decompressobj();state=decoder.decompress(raw,MAX_STATE+1)
            if len(state)>MAX_STATE or not decoder.eof or decoder.unused_data or digest(state)!=row['sha256']:raise ValueError('Контрольная сумма резервной копии не совпадает')
        except zlib.error as error:raise ValueError('Повреждённая резервная копия') from error
        return state

def rotate_session_backups(sessions):
    # Keep retention paths out of the current commit's metadata scope.
    for path in sorted(sessions.glob('*.state'))[:-10]:path.unlink()

def publish(snapshot,data,rom_sha1,*,backup=False,on_warning=None):
    def ancillary(stage, operation):
        try:operation()
        except Exception as error:
            message=f'{stage}: {error}'
            logging.getLogger(__name__).warning(message,exc_info=True)
            if on_warning:on_warning(message)
    data=Path(data);timeline=SaveTimeline(data);path=data/'FireRed.state';previous=path.read_bytes() if path.is_file() else None
    old=timeline.current(verify=False)
    if old and previous is not None and old.get('sha256')!=digest(previous):old=None
    if previous is not None and previous==snapshot.state:
        # Pausing or closing an unchanged game must not age out its rollback.
        try:verify_snapshot(snapshot,data)
        except OSError:
            # Repair an interrupted SRAM export without changing the checkpoint.
            snapshot.publish(data);verify_snapshot(snapshot,data)
        if not timeline.current():ancillary('Метаданные сохранения',lambda:timeline.describe(snapshot,rom_sha1,captured_at=path.stat().st_mtime))
        return path
    if previous is not None:
        ancillary('История сохранений',lambda:timeline.archive(previous,rom_sha1))
        if backup:
            sessions=data/'backups/sessions'
            ancillary('Резервная копия',lambda:atomic_bytes(sessions/f'FireRed-{time.time_ns()}.state',previous,durable=True))
    clock=(old or {}).get('history_time',0)
    if snapshot.active_seconds is not None:
        elapsed=snapshot.active_seconds-((old or {}).get('active_seconds') or 0) if old and old.get('producer')==snapshot.producer else snapshot.active_seconds
    else:elapsed=max(0,snapshot.captured_at-(old or {}).get('captured_at',snapshot.captured_at))
    clock+=max(0,elapsed)
    result=snapshot.publish(data)  # The state is published last, as before.
    verify_snapshot(snapshot,data)
    ancillary('Метаданные сохранения',lambda:timeline.describe(snapshot,rom_sha1,history_time=clock))
    ancillary('Очистка истории',lambda:timeline.prune(clock))
    if backup:ancillary('Очистка резервных копий',lambda:rotate_session_backups(data/'backups/sessions'))
    return result
