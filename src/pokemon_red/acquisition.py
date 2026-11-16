"""Isolated, persistent acquisition jobs. Never owns the main game's core/Data."""

from .paths import session_paths, resource, bind_installation
from dataclasses import dataclass, asdict
from pathlib import Path
import hashlib
import json
import os
import subprocess
import time
import uuid
from .persistence import atomic_bytes
from .editions import edition

STARTERS={1:'Bulbasaur',4:'Charmander',7:'Squirtle'}
HOENN_STARTERS={277:'Treecko',280:'Torchic',283:'Mudkip'}
def starters_for(project):return HOENN_STARTERS if edition(project).family=='hoenn' else STARTERS
TERMINAL={'ready','paused','attention','error','cancelled','transferred'}
TEMPLATE='templates/FireRed/ALEX-before-starter-v1'
WILD_TEMPLATE='templates/FireRed/Progressed-hunting-v1'

def template_for(project,template):
    if template not in (TEMPLATE,WILD_TEMPLATE):raise ValueError('Неизвестный шаблон')
    return template.replace('/FireRed/','/'+edition(project).name+'/')

@dataclass(frozen=True)
class AcquisitionConfig:
    species_id: int = 1
    shiny: bool = False
    train: bool = False
    target_level: int = 10
    source: str = 'starter'

    @classmethod
    def parse(cls, data):
        species=data.get('species_id',1);level=data.get('target_level',10);source=data.get('source','starter')
        if source not in ('starter','wild'):raise ValueError('Неизвестный шаблон охоты')
        if type(species) is not int or not 1<=species<=411 or source=='starter' and species not in (STARTERS|HOENN_STARTERS):raise ValueError('Выбери доступного Pokémon')
        if type(level) is not int or not 5 <= level <= 100:raise ValueError('Уровень должен быть от 5 до 100')
        if type(data.get('shiny',False)) is not bool or type(data.get('train',False)) is not bool:raise ValueError('Некорректные переключатели задания')
        if source=='wild' and data.get('train',False):raise ValueError('Докачка дикой добычи пока недоступна')
        return cls(species,data.get('shiny',False),data.get('train',False),level,source)

def write_json(path, value):
    from .installation_versions import stamp_result
    value=stamp_result(path,value)
    atomic_bytes(Path(path),(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode(),durable=True)

def read_json(path, default=None):
    try:return json.loads(Path(path).read_text())
    except (OSError,ValueError):return default

def verify_template(project,template=TEMPLATE):
    folder=Path(project)/template_for(project,template)
    manifest=read_json(folder/'manifest.json')
    if not manifest or manifest.get('algorithm')!='sha256':raise ValueError('Не найден проверенный шаблон охоты для '+edition(project).name)
    for name,digest in manifest.get('files',{}).items():
        path=folder/name
        if Path(name).name!=name or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
            raise ValueError('Нарушена целостность стартового шаблона: '+name)
    if not all((folder/n).is_file() for n in ('FireRed.state','FireRed.sav','metadata.json')):raise ValueError('Неполный стартовый шаблон')
    return folder

def prepare_job(project, config):
    project=Path(project).resolve();config=AcquisitionConfig.parse(asdict(config) if isinstance(config,AcquisitionConfig) else config)
    if config.source=='starter' and config.species_id not in starters_for(project):raise ValueError('Этот стартовый Pokémon не выдаётся в выбранной игре')
    template_name=WILD_TEMPLATE if config.source=='wild' else TEMPLATE
    template=verify_template(project,template_name)
    if config.source=='wild':
        from .hunting_template import wild_options
        if config.species_id not in wild_options(project):
            from .i18n import t
            raise ValueError(t('capture.not_in_game'))
    if config.source=='wild' and not any(any(m['species_id']==config.species_id for m in r['population']) for r in read_json(template/'metadata.json',{}).get('routes',{}).values()):raise ValueError('Этот Pokémon пока недоступен из шаблона охоты')
    jobs=session_paths(project).workspaces.root/'acquisition';jobs.mkdir(parents=True,exist_ok=True)
    job=jobs/uuid.uuid4().hex;job.mkdir();(job/'Data').mkdir();(job/'checkpoints').mkdir()
    # Copy bytes: copy2 would inherit the template's macOS immutable flag.
    for name in ('FireRed.state','FireRed.sav'):
        atomic_bytes(job/'Data'/name,(template/name).read_bytes(),durable=True)
    from .installation_versions import pin_job
    pin_job(job,project,'acquisition')
    (job/'Data/FireRed.gba').symlink_to(os.path.relpath(project/'Data/FireRed.gba',job/'Data'))
    if (project/'Data/game.json').exists():
        atomic_bytes(job/'Data/game.json',(project/'Data/game.json').read_bytes(),durable=True)
    write_json(job/'Data/settings.json',dict(sound_enabled=False,autosave_enabled=True,autosave_seconds=5,panel_on_start=False,speed=8,scale=2))
    write_json(job/'job.json',dict(schema_version=1,id=job.name,project=os.path.relpath(project,job),created_at=time.time(),config=asdict(config),template=template_name,template_state_sha256=hashlib.sha256((template/'FireRed.state').read_bytes()).hexdigest()))
    write_json(job/'status.json',dict(status='paused',stage='Задание создано',attempts=0,unique_candidates=0,updated_at=time.time()))
    return job

def job_active(row):
    if row.get('status') in TERMINAL:return False
    if not row.get('pid'):return time.time()-row.get('starting_at',0)<10
    try:os.kill(row['pid'],0);return True
    except ProcessLookupError:return False

class AcquisitionManager:
    def __init__(self,project):
        self.project=Path(project).resolve();self.folder=self.project/'Sessions/acquisition';self.processes={}

    def job(self,job_id):
        if not isinstance(job_id,str) or len(job_id)!=32 or any(c not in '0123456789abcdef' for c in job_id):raise ValueError('Некорректное задание')
        job=self.folder/job_id
        if not (job/'job.json').is_file():raise ValueError('Задание не найдено')
        return job

    def jobs(self):
        if not self.folder.exists():return []
        rows=[]
        for folder in self.folder.iterdir():
            spec=read_json(folder/'job.json');state=read_json(folder/'status.json',{})
            if spec and isinstance(spec,dict):rows.append(dict(spec,**state))
        return sorted(rows,key=lambda r:r['created_at'],reverse=True)

    def start(self,config):
        job=prepare_job(self.project,config);self.resume(job.name);return job.name

    def resume(self,job_id):
        job=self.job(job_id);state=read_json(job/'status.json',{})
        if state.get('status') in ('ready','transferred'):raise ValueError('Pokémon уже готов к переносу')
        # The worker enforces an exclusive flock too. Check liveness to avoid a
        # second GUI attaching a competing worker to the same job.
        pid=state.get('pid')
        if not pid and state.get('status') not in TERMINAL and time.time()-state.get('starting_at',0)<10:raise ValueError('Сессия уже запускается')
        if state.get('status') not in TERMINAL and pid:
            try:os.kill(pid,0)
            except ProcessLookupError:pass
            else:raise ValueError('Задание уже выполняется')
        write_json(job/'status.json',dict(state,status='preparing',resume_from=state.get('status'),stage='Запускаем отдельную сессию',pid=None,starting_at=time.time(),updated_at=time.time()))
        write_json(job/'command.json',dict(command='run',token=uuid.uuid4().hex))
        from .installation_versions import job_identity,pin_job,bound_version
        if job_identity(job) is None:pin_job(job,self.project,'acquisition')
        version=bound_version(job);python=version.python
        worker=version.worker('acquisition_worker.py')
        with (job/'worker.log').open('ab',buffering=0) as log:
            process=subprocess.Popen([str(python),'-I','-B','-u',str(worker),str(job)],cwd=job,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True,env=version.environment())
        self.processes[job_id]=process

    def pause(self,job_id):
        write_json(self.job(job_id)/'command.json',dict(command='pause',token=uuid.uuid4().hex))

    def cancel(self,job_id):
        job=self.job(job_id);state=read_json(job/'status.json',{})
        if state.get('status')=='transferred':raise ValueError('Pokémon уже перенесён')
        if job_active(state):write_json(job/'command.json',dict(command='cancel',token=uuid.uuid4().hex))
        else:write_json(job/'status.json',dict(state,status='cancelled',stage='Задание отменено · найденные сохранения оставлены',updated_at=time.time()))

    def poll(self):
        for job_id,p in list(self.processes.items()):
            code=p.poll()
            if code is None:continue
            job=self.job(job_id);state=read_json(job/'status.json',{})
            if state.get('status') not in TERMINAL:
                write_json(job/'status.json',dict(state,status='error',stage='Процесс завершился; сохранения оставлены для продолжения',exit_code=code,updated_at=time.time()))
            del self.processes[job_id]
        rows=self.jobs()
        for row in rows:
            if row.get('status') in TERMINAL or time.time()-row.get('updated_at',0)<10:continue
            pid=row.get('pid')
            if pid:
                try:os.kill(pid,0);continue
                except ProcessLookupError:pass
            state=read_json(self.job(row['id'])/'status.json',{})
            if state.get('updated_at')!=row.get('updated_at'):continue
            write_json(self.job(row['id'])/'status.json',dict(state,status='error',stage='Сессия прервана; можно продолжить с сохранённого этапа',updated_at=time.time()))
        return self.jobs()
