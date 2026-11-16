"""Exclusive main-window operations with detached workers and durable backups."""

from .paths import session_paths, resource, bind_installation
from pathlib import Path
import fcntl
import hashlib
import json
import os,signal
import shutil
import subprocess
import time
import uuid
from .acquisition import write_json,read_json
from .editions import rom_sha1
from .persistence import atomic_bytes,publish_checkpoint,SaveSnapshot
from .engine import ROM_SHA1

TERMINAL={'ready','paused','cancelled','attention','error'}

def clone_session(project,folder,snapshot,*,installation=None):
    project=Path(project).resolve();folder=Path(folder).resolve();(folder/'Data').mkdir(parents=True);(folder/'checkpoints').mkdir()
    bind_installation(folder,installation or project)
    (folder/'Data/FireRed.gba').symlink_to(os.path.relpath(project/'Data/FireRed.gba',folder/'Data'));snapshot.publish(folder/'Data')
    if (project/'Data/game.json').exists():shutil.copy2(project/'Data/game.json',folder/'Data/game.json')
    return folder

class MainOperation:
    POLL_INTERVAL=.15
    def next_poll_at(self):
        return self.last_poll+self.POLL_INTERVAL if self.job is not None else None

    def __init__(self,monitor):
        self.m=monitor;self.job=None;self.process=None;self.last_poll=0;self.last_screen=None;self.result=None;self.lock=None;self.commit_future=None;self.prepare_future=None;self.cancel_preparation=False;self.cancel_requested_at=None;self.speed_limit=None;self.status={};self.restart_requested=False;self.stop_sent=False;self.finish_search_requested=False;self.spec_config={};self.best_requested=False
        from .catch_lifecycle import context_path
        self.catch_context=read_json(context_path(monitor.folder),{})
        self.context_position=None;self.context_revision=0;self.finish_search_requested=False
        self.execution=None;self.generation=None
        from collections import deque
        self.retired_searches=deque(maxlen=256)
    @property
    def active(self):return self.job is not None
    def begin(self,kind,config):
        if self.active:raise ValueError('Основная игра уже занята')
        try:return self._begin(kind,config)
        except Exception:
            if self.process is None:
                self.job=None
                if self.lock:self.lock.close();self.lock=None
            raise
    def _begin(self,kind,config):
        m=self.m
        if self.active or m.session_transition or m.closing or m.pending_start or m.critical_save_pending():raise ValueError('Сначала заверши текущее действие или сохранение')
        if kind not in ('local','trade','delivery','delivery_source','encounter','prologue'):raise ValueError('Неизвестная операция')
        if kind=='prologue':
            from .new_game_config import NewGameConfig
            from .editions import edition
            from .i18n import t
            marker=read_json(m.folder/'Data/new-game.json',{})
            if not marker or marker.get('status')=='complete':raise ValueError(t('prologue.not_new_game'))
            use_best=bool(config.get('use_best'));self.best_requested=use_best
            config=dict(NewGameConfig.parse(marker['config'],edition(m.folder).id).json(),_progress=marker.get('progress',{}),_locale=m.settings['language'],_use_best=use_best,_candidate_sha=config.get('candidate_sha'))
        if kind=='encounter':
            from .encounter_capture import validate
            config=dict(config,target_uid=validate(m))
        if kind=='local' and config.get('species_id') and config.get('schema_version')!=2:
            from .capture_target import catchable_species
            if config['species_id'] not in catchable_species(m.folder):
                from .i18n import t
                raise ValueError(t('capture.not_in_game'))
        if kind=='local' and config.get('schema_version')==2:
            source=config.get('_resume_search') or config.get('_saved_candidate',{}).get('operation_id')
            if source in self.retired_searches:
                from .i18n import t
                raise ValueError(t('capture.search_finished'))
            if config.get('_saved_candidate'):
                from .wild_search_history import candidate_request
                saved,_=candidate_request(m.folder,config['_saved_candidate'])
                config=dict({k:v for k,v in saved['config'].items() if not k.startswith('_')},_saved_candidate=dict(config['_saved_candidate']))
            elif config.get('_resume_search'):
                from .wild_search_history import saved_search
                saved=saved_search(m.folder,config['_resume_search'],verify=True)
                config=dict({k:v for k,v in saved['config'].items() if not k.startswith('_')},_resume_search=saved['id'],_remaining_seconds=saved.get('remaining'))
            from .capture_target import CaptureTarget
            from .automatic_speed import speed_cap
            target=CaptureTarget.parse(config,m.folder);config=dict(config,**target.as_dict())
            from .capture_target import candidates
            if not candidates(target,m.folder):
                from .i18n import t
                raise ValueError(t('capture.not_in_game'))
            speed_cap(config.get('max_auto_speed',12));config=dict(config,_locale=m.settings['language'])
        self.speed_limit=16 if kind=='prologue' else config.get('max_auto_speed',12) if kind=='encounter' or kind=='local' and config.get('schema_version')==2 else None
        self.lock=(m.folder/'Data/.main-operation.lock').open('a')
        try:fcntl.flock(self.lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:self.lock.close();self.lock=None;raise ValueError('Основная сессия уже занята')
        m.automation.stop('Управление передано ловле / обмену');m.pending_start=None;m.pause(save=False);m.keys.clear();m.game.advance(0,0)
        snapshot=m.game.capture_save()
        rollback_slot=None
        if kind=='local' and (config.get('_saved_candidate') or config.get('_resume_search')):
            from .i18n import t
            rollback_slot=m.slots.capture(m.game,t('capture.rollback_slot'))
        from .starter_checkpoint import valid_frontier
        recover_frontier=kind=='prologue' and config.get('_progress',{}).get('phase')=='search' and not valid_frontier(m.game)
        job=session_paths(m.folder).workspaces.root/'operations'/uuid.uuid4().hex;job.mkdir(parents=True)
        self.status={};self.restart_requested=False;self.stop_sent=False;self.finish_search_requested=False;self.spec_config=config
        self.job=job;self.result=None;self.frame=snapshot.frame;self.game=m.game;self.kind=kind;self.last_screen=None;self.cancel_preparation=False;self.cancel_requested_at=None
        self.execution=None
        self.generation=getattr(m.game,'state_generation',None)
        # Capture is on the core owner; durable copies and fsync are detached.
        def backup_before_prepare():
            if rollback_slot:rollback_slot.publish()
            backup=job/'before-main';snapshot.publish(backup)
            write_json(backup/'manifest.json',{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in backup.iterdir()})
            for p in backup.iterdir():p.chmod(0o444)
            backup.chmod(0o555)
        backup_future=m.submit_write(backup_before_prepare,critical=True)
        def prepare():
            backup_future.result()
            if self.cancel_preparation:raise RuntimeError('Operation preparation cancelled')
            from .installation_versions import pin_job
            execution=pin_job(job,m.folder,kind)
            backup=job/'before-main'
            work_snapshot=snapshot
            if recover_frontier:
                from .starter_checkpoint import recover
                work_snapshot=recover(m.folder,config)
            if kind=='local' and config.get('_resume_search'):
                from .wild_search_history import resume_snapshot,operation_folder
                from .search_candidates import CandidateStore
                _,work_snapshot=resume_snapshot(m.folder,config['_resume_search'])
            clone_session(m.folder,job/'main',work_snapshot,installation=job)
            if kind=='local' and config.get('_resume_search'):
                CandidateStore(operation_folder(m.folder,config['_resume_search'])/'main','wild').copy_to(job/'main')
            spec=dict(schema_version=1,id=job.name,kind=kind,config=config,execution=execution,project=os.path.relpath(m.folder,job),frame=snapshot.frame,created_at=time.time(),main_backup=str(backup),base_state_sha256=hashlib.sha256(snapshot.state).hexdigest(),rollback_slot=rollback_slot.slot_id if rollback_slot else None)
            write_json(job/'operation.json',spec)
            write_json(job/'status.json',dict(status='running',stage='Резервная копия готова'))
            write_json(job/'command.json',dict(command='run'))
            if kind=='prologue':
                from .starter_candidates import copy_saved
                copy_saved(m.folder,job/'main')
            if kind=='prologue':write_json(job/'main/Data/prologue-checkpoint.json',dict(prologue=config.get('_progress',{}),main_hashes={n:hashlib.sha256((job/'main/Data'/n).read_bytes()).hexdigest() for n in ('FireRed.state','FireRed.sav')}))
            if kind=='local' and config.get('schema_version')==2:
                write_json(m.folder/'Sessions/acquisition/local-slot.json',dict(config=config,status='running',pokemon=None))
            return execution
        from .installation_versions import submit_preparation
        try:self.prepare_future=submit_preparation(prepare,notify=getattr(getattr(m,'transport',None),'wake',lambda:None))
        except Exception:
            self.finish();raise
        m.notice='Готовим резервную копию · F9 — отменить';m.update_panel();return job.name
    def launch(self):
        m=self.m;job=self.job
        python=session_paths(job).installation.python
        with (job/'worker.log').open('ab',buffering=0) as log:self.process=subprocess.Popen([str(python),'-I','-B','-u',str(resource(job,'src/pokemon_red/operation_worker.py')),str(job)],cwd=job,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
        m.notice='Управление у автоматики · F9 — остановить';m.update_panel()
    def command(self,command,*,requested_at=None):
        if command=='finish_search' or command.startswith('finish_search:'):
            return self.end_search(command.partition(':')[2] or None)
        if command in ('pause','cancel'):self.restart_requested=False
        candidate_sha=None
        if command.startswith('use_candidate:'):
            candidate_sha=command.partition(':')[2]
            if len(candidate_sha)!=64 or any(c not in '0123456789abcdef' for c in candidate_sha):raise ValueError('Invalid candidate')
            command='use_best'
        if command=='use_best':self.best_requested=True
        if command=='restart_search':
            if getattr(self,'kind',None)!='prologue':raise ValueError('No starter search')
            self.restart_requested=True;command='pause'
        if getattr(self,'kind',None) in ('encounter','prologue','local') and command in ('pause','cancel'):self.cancel_requested_at=min(self.cancel_requested_at or float('inf'),requested_at or time.time())
        if self.prepare_future is not None:
            if command in ('pause','cancel'):self.cancel_preparation=True
            return
        if self.job:write_json(self.job/'command.json',dict(command=command,candidate_sha=candidate_sha,requested_at=requested_at or time.time()))
    def poll(self):
        if not self.job or time.monotonic()-self.last_poll<self.POLL_INTERVAL:return
        if self.prepare_future is not None:
            if not self.prepare_future.done():return
            try:
                self.execution=self.prepare_future.result()
                if self.cancel_preparation or self.m.game is not self.game or self.m.game.frame!=self.frame or getattr(self.m.game,'state_generation',None)!=self.generation:
                    raise RuntimeError('Запуск отменён · управление возвращено')
                self.launch()
            except Exception as error:
                self.m.notice=str(error);self.result=dict(status='cancelled' if self.cancel_preparation else 'error',stage=str(error),operation_id=self.job.name,kind=self.kind,applied=False);self.finish()
            finally:self.prepare_future=None
            return
        if self.commit_future is not None:
            if not self.commit_future.done():return
            try:
                self.commit_future.result()
                if self.kind=='delivery':
                    self.m.game.load_state(self.job/'main/Data/FireRed.state');self.m.last_state=None;self.m.refresh_state()
                self.result['applied']=True
            except Exception as error:
                self.result.update(status='attention',stage='Ошибка записи: '+str(error),applied=False);self.m.notice=self.result['stage']
                if self.kind=='delivery':
                    from .item_delivery import recover_commits,queue_folder
                    try:
                        recover_commits(self.m.folder)
                        result=read_json(self.job/'result.json',{});row=read_json(queue_folder(self.m.folder,result['delivery_job'])/'job.json',{})
                        if row.get('last_operation')==self.job.name:
                            self.m.game.load_state(self.job/'main/Data/FireRed.state');self.m.last_state=None;self.m.refresh_state();self.result['applied']=True
                    except Exception:pass
            self.commit_future=None;self.finish();return
        self.last_poll=time.monotonic();state=read_json(self.job/'status.json',{});self.status=state
        if getattr(self,'kind',None) in ('prologue','local') and self.cancel_requested_at and self.process.poll() is None:
            elapsed=time.time()-self.cancel_requested_at
            if elapsed>7:os.killpg(self.process.pid,signal.SIGKILL)
            elif elapsed>3 and not self.stop_sent:self.process.terminate();self.stop_sent=True
        self.m.notice=state.get('stage','Выполняем действие')
        if getattr(self,'kind',None)=='prologue':self.speed_limit=state.get('speed_limit',16)
        try:self.last_screen=(self.job/'screen.ppm').read_bytes()
        except OSError:pass
        code=self.process.poll()
        if code is None:return
        if getattr(self,'kind',None) in ('prologue','local'):
            try:os.killpg(self.process.pid,signal.SIGKILL)
            except ProcessLookupError:pass
        if getattr(self,'kind',None)=='prologue' and not (self.job/'result.json').is_file():
            checkpoint=read_json(self.job/'main/Data/prologue-checkpoint.json',{})
            manifest=checkpoint.get('main_hashes',{})
            if set(manifest)=={'FireRed.state','FireRed.sav'} and all(hashlib.sha256((self.job/'main/Data'/n).read_bytes()).hexdigest()==digest for n,digest in manifest.items()):
                from .i18n import t
                write_json(self.job/'result.json',dict(pokemon=None,prologue=checkpoint['prologue'],main_hashes=manifest))
                state=dict(state,status='paused',stage=t('search.recovered'),prologue=checkpoint['prologue'])
        if state.get('status') not in TERMINAL:state=dict(state,status='error',stage='Процесс прерван; основная игра сохранена в резервной копии')
        spec=read_json(self.job/'operation.json',{});kind=spec['kind'];apply=kind in ('local','prologue') and (self.job/'result.json').is_file() or kind!='delivery_source' and state.get('status')=='ready'
        if spec.get('config',{}).get('_saved_candidate'):
            # A stopped/failed capture must not import an old timeline. A catch
            # already verified by the worker is published as ready, even on F9.
            apply=state.get('status')=='ready' and bool(read_json(self.job/'result.json',{}).get('pokemon'))
        try:
            if apply:
                if self.m.game is not self.game or self.m.game.frame!=self.frame or getattr(self.m.game,'state_generation',None)!=self.generation:raise ValueError('Основная игра изменилась во время операции; результат сохранён отдельно')
                result=read_json(self.job/'result.json',{});manifest=result.get('main_hashes',{})
                from .installation_versions import require_result
                require_result(self.execution,result)
                for name,digest in manifest.items():
                    if Path(name).name!=name or hashlib.sha256((self.job/'main/Data'/name).read_bytes()).hexdigest()!=digest:raise ValueError('Не совпали контрольные суммы результата')
                if not {'FireRed.state','FireRed.sav'}<=manifest.keys():raise ValueError('Неполный результат операции')
                if spec['config'].get('_saved_candidate'):
                    from .wild_search_history import candidate_request
                    from .i18n import t
                    from .capture_target import CaptureTarget
                    saved,selected=candidate_request(self.m.folder,spec['config']['_saved_candidate'])
                    rated=CaptureTarget.parse(saved['config'],self.m.folder).assess(result.get('pokemon') or {},self.m.folder)
                    if not rated or rated['pokemon']!=selected['pokemon']:raise ValueError(t('capture.result_mismatch'))
                if kind=='prologue' and state['status']=='ready':
                    from .new_game_config import NewGameConfig
                    from .i18n import t
                    mon=result.get('pokemon') or {};accepted=result.get('prologue',{}).get('accepted_uid')
                    explicit=(self.best_requested or spec['config'].get('_progress',{}).get('accepted_uid')==accepted) and accepted==mon.get('uid') and mon.get('checksum_valid') and mon.get('species_id')==spec['config']['species_id']
                    if result.get('prologue',{}).get('phase')!='complete' or not (NewGameConfig.parse(spec['config']).matches(mon) or explicit):raise ValueError(t('prologue.final_mismatch'))
                if kind=='encounter':
                    if not result.get('verified') or result.get('pokemon',{}).get('uid')!=spec['config']['target_uid']:raise ValueError('Не подтверждена поимка текущего Pokémon')
                    if self.cancel_requested_at is not None and self.cancel_requested_at<=result.get('caught_at',float('inf')):
                        self.m.notice='Автопоимка выключена · исходная встреча восстановлена';self.result=dict(status='cancelled',applied=False,kind=kind);self.finish();return
                    self.m.safety_notice=None
                if kind=='delivery':
                    from .item_delivery import queue_folder
                    config=spec['config'];row=read_json(queue_folder(self.m.folder,config['delivery_job'])/'job.json',{})
                    if (not result.get('verified') or result.get('delivery_job')!=config['delivery_job'] or result.get('sequence')!=config['sequence']
                            or result['sequence']!=row.get('delivered',0)+1 or result.get('courier_uid')!=config['courier_uid']
                            or result.get('item_id',14)!=config.get('item_id',14) or result.get('item_id',14)!=row.get('item_id',14)
                            or result.get('quantity_after')!=result.get('quantity_before',-2)+1):
                        raise ValueError('Не подтверждена завершённая пара доставки')
                if kind=='trade':
                    donor=Path(result['donor']);expected=self.m.folder/'Sessions/acquisition'/spec['config']['donor_job']
                    if donor.resolve()!=expected.resolve():raise ValueError('Изменилась сессия донора')
                    if hashlib.sha256((donor/'Data/FireRed.state').read_bytes()).hexdigest()!=result['donor_before_sha256']:raise ValueError('Сохранение донора изменилось; обмен оставлен в операции')
                    if set(result.get('donor_hashes',{}))!={'FireRed.state','FireRed.sav'}:raise ValueError('Неполный результат второй стороны')
                    for name,digest in result['donor_hashes'].items():
                        if hashlib.sha256((self.job/'donor/Data'/name).read_bytes()).hexdigest()!=digest:raise ValueError('Повреждено сохранение второй стороны')
                    write_json(self.job/'commit.json',dict(status='committing',result=result))
                if kind=='delivery':
                    # Keep the live core unchanged until the durable pair and receipt exist.
                    snapshot=SaveSnapshot((self.job/'main/Data/FireRed.state').read_bytes(),(self.job/'main/Data/FireRed.sav').read_bytes(),state.get('frame',0),time.time())
                else:
                    if spec['config'].get('_saved_candidate'):self.m.history.change_timeline('saved_candidate',spec['config']['_saved_candidate']['operation_id'])
                    elif spec['config'].get('_resume_search'):self.m.history.change_timeline('resume_search',spec['config']['_resume_search'])
                    self.m.game.load_state(self.job/'main/Data/FireRed.state')
                    snapshot=self.m.game.capture_save()
                operation_job=self.job
                def commit():
                    if kind=='delivery':
                        from .item_delivery import commit_delivery
                        commit_delivery(self.m.folder,operation_job,result,snapshot)
                    else:publish_checkpoint(snapshot,self.m.folder/'Data',rom_sha1(self.m.folder),backup=True)
                    if kind=='prologue':
                        if result.get('prologue',{}).get('phase')=='search':
                            from .starter_checkpoint import store
                            store(self.m.folder,snapshot,spec['config'])
                        from .starter_candidates import copy_saved
                        copy_saved(operation_job/'main',self.m.folder)
                        write_json(self.m.folder/'Data/new-game.json',dict(config={k:v for k,v in spec['config'].items() if not k.startswith('_')},status='complete' if state['status']=='ready' else 'paused',progress=result.get('prologue',{})))
                    if kind=='local' and spec['config'].get('schema_version')==2 and state['status']=='ready' and result.get('pokemon'):
                        from .catch_lifecycle import close_receipt
                        source=spec['config'].get('_saved_candidate',{}).get('operation_id') or spec['config'].get('_resume_search')
                        close_receipt(self.m.folder,operation_job.name,'caught')
                        if source:close_receipt(self.m.folder,source,'caught')
                    if kind=='local' and spec['config'].get('schema_version')==2:
                        write_json(self.m.folder/'Sessions/acquisition/local-slot.json',dict(config=spec['config'],status=state['status'],pokemon=result.get('pokemon'),stage=state.get('stage')))
                    if kind=='trade':
                        for name,digest in result['donor_hashes'].items():
                            data=(operation_job/'donor/Data'/name).read_bytes()
                            if hashlib.sha256(data).hexdigest()!=digest:raise ValueError('Повреждено сохранение второй стороны')
                            atomic_bytes(donor/'Data'/name,data,durable=True)
                        old=read_json(donor/'status.json',{});write_json(donor/'status.json',dict(old,status='transferred',transfer_ready=False,stage='Перенесён в основную игру',transfer_operation=operation_job.name))
                        write_json(operation_job/'commit.json',dict(status='committed',received_uid=result['pokemon']['uid']))
                # Ordered after previous GUI writes; no core is touched by writer.
                self.commit_future=self.m.submit_write(commit,critical=True)
                if kind!='delivery':self.m.last_state=None;self.m.refresh_state()
                self.m.notice=state.get('stage','Готово')
            else:self.m.notice=state.get('stage','Операция остановлена · исходное сохранение сохранено')
            self.result=dict(state,operation_id=self.job.name,kind=kind,config=spec['config'],rollback_slot=spec.get('rollback_slot'),applied=bool(apply) and self.commit_future is None,result=read_json(self.job/'result.json',{}))
        except Exception as error:self.result=dict(status='attention',stage=str(error),operation_id=self.job.name,kind=kind,applied=False);self.m.notice=str(error)
        if self.commit_future is not None:return
        self.finish()
    def finish(self):
        try:self.retain_catch_context()
        except Exception as error:
            from .i18n import t
            self.m.notice=t('capture.lifecycle_problem',reason=str(error))
            self.result=dict(self.result or {},status='attention',stage=self.m.notice)
        restart=self.restart_requested;self.restart_requested=False
        self.m.paused=True;self.m.keys.clear();self.job=None;self.kind=None;self.last_screen=None;self.process=None
        if self.lock:self.lock.close();self.lock=None
        self.m.update_panel()
        if getattr(self.m,'close_after_operation',False):self.m.close_after_operation=False;self.m.close()
        elif restart:self.begin('prologue',{})
    def restore_catch_context(self):
        # One asynchronous migration for searches created before lifecycle support.
        if self.catch_context:return
        from .wild_search_history import saved_searches
        revision=self.context_revision
        def loaded(rows):
            if self.active or self.catch_context or self.context_revision!=revision or not rows:return
            row=rows[0]
            self.catch_context=dict(id=row['id'],state='paused',paused_at=row.get('paused_at') or time.time(),manual_steps=0,config=row['config'],search=dict(candidates=row['candidates'],attempts=row['attempts']),stage='')
            self.context_position=None;self._persist_catch_context()
        self.m.submit_write(lambda:saved_searches(self.m.folder,limit=1),success=loaded)
    def _persist_catch_context(self):
        from copy import deepcopy
        from .catch_lifecycle import persist_context
        context=deepcopy(self.catch_context);self.context_revision+=1
        self.m.submit_write(lambda:persist_context(self.m.folder,context),coalesce='catch-context')
        self.m.update_panel()
    def _close_search(self,identifier,reason):
        from .catch_lifecycle import close_receipt
        self.retired_searches.append(identifier)
        self.m.submit_write(lambda:close_receipt(self.m.folder,identifier,reason))
        if self.catch_context.get('id')==identifier:
            self.catch_context={};self.context_position=None;self._persist_catch_context()
        if (self.result or {}).get('operation_id')==identifier:
            self.result=dict(self.result,search={});self.status=dict(self.status,search={})
        self.context_revision+=1;self.m.update_panel()
    def end_search(self,identifier=None):
        from .wild_search_history import operation_folder
        from .i18n import t
        identifier=identifier or (self.job.name if self.active and self.kind=='local' else self.catch_context.get('id'))
        if not identifier:return
        operation_folder(self.m.folder,identifier)  # Validate before any mutation.
        if self.active:
            if self.kind!='local' or self.job.name!=identifier:raise ValueError(t('capture.stop_before_choose'))
            self.finish_search_requested=True;self.command('cancel');return
        self._close_search(identifier,'dismissed');self.m.notice=t('capture.search_finished')
    def retain_catch_context(self):
        cfg=getattr(self,'spec_config',{})
        if getattr(self,'kind',None)!='local' or cfg.get('schema_version')!=2:return
        result=self.result or {};identifier=self.job.name
        if result.get('status')=='ready' and result.get('applied'):
            source=cfg.get('_saved_candidate',{}).get('operation_id') or cfg.get('_resume_search')
            if source:self._close_search(source,'caught')
            old=self.catch_context.get('id')
            if old and old not in (source,identifier):self._close_search(old,'superseded')
            self._close_search(identifier,'caught');return
        if self.finish_search_requested:
            old=self.catch_context.get('id')
            if old and old!=identifier:self._close_search(old,'dismissed')
            self._close_search(identifier,'dismissed')
            from .i18n import t
            self.result=dict(self.result or {},stage=t('capture.search_finished'),search={});self.m.notice=t('capture.search_finished');return
        # Failed/aborted candidate capture leaves the original paused search open.
        if cfg.get('_saved_candidate'):return
        old=self.catch_context.get('id')
        if old and old!=identifier:self._close_search(old,'continued' if cfg.get('_resume_search')==old else 'superseded')
        self.catch_context=dict(id=identifier,state='paused',paused_at=time.time(),manual_steps=0,config={k:v for k,v in cfg.items() if not k.startswith('_')},search=result.get('search',{}),stage=result.get('stage',''))
        self.context_position=None;self._persist_catch_context()
    def observe_catch_context(self,state):
        if self.active or self.m.automation.running or not self.catch_context:return
        from .catch_lifecycle import observe
        previous_steps=self.catch_context.get('manual_steps',0)
        self.context_position,expired=observe(self.catch_context,state,self.context_position,generation=self.m.game.state_generation)
        if expired:
            from .i18n import t
            self._close_search(self.catch_context['id'],'manual_travel' if self.catch_context.get('manual_steps',0)>=100 else 'idle_timeout');self.m.notice=t('capture.search_expired')
        elif self.catch_context.get('manual_steps',0)!=previous_steps:self._persist_catch_context()

    def prologue_config(self,patch=None):
        from .new_game_config import NewGameConfig
        from .editions import edition
        from .i18n import t
        path=self.m.folder/'Data/new-game.json';marker=read_json(path,{})
        if not marker:raise ValueError(t('prologue.not_new_game'))
        if patch is None:
            from .starter_candidates import load
            candidates=load(self.m.folder,NewGameConfig.parse(marker['config']))
            return dict(marker,best=candidates[0] if candidates else None,candidates=candidates)
        if marker.get('status')=='complete':raise ValueError(t('prologue.not_new_game'))
        if self.active or self.m.critical_save_pending():raise ValueError(t('search.pause_first'))
        if marker.get('progress',{}).get('phase','intro') not in ('intro','laboratory','choice','search'):raise ValueError(t('search.too_late'))
        allowed={'gender','shiny','nature','natures','min_ivs','priority_ivs','search_workers'}
        if set(patch)-allowed:raise ValueError(t('search.filters_only'))
        cfg=NewGameConfig.parse(dict(marker['config'],**patch),edition(self.m.folder).id)
        marker=dict(marker,config=cfg.json(),status='paused')
        return self.m.submit_write(lambda:write_json(path,marker),critical=True)

    def close(self):
        if self.active:self.command('cancel')
