"""Single-preparation, bounded wild-search pool with one verified winner.

Only the supervisor restores a selected branch. Stop is checked after teardown,
before restore and again before capture. Losing branches are never merged.
"""

from .paths import session_paths
from pathlib import Path
import hashlib,os,subprocess,time,uuid
from .acquisition import read_json,write_json
from .acquisition_play import AcquisitionAttention,JobPaused
from .capture_target import CaptureTarget
from .autocatch import prepare_hunt,run_autocatch,verified_enemy
from .models import read_inventory,read_roster_uids
from .operations import clone_session
from .search_candidates import CandidateStore,rank_candidates
from .search_processes import stop_children
from .i18n import t
from .search_budget import SearchBudget


def check_roster(game,original):
    current=read_roster_uids(game)
    if not set(original)<=current:raise AcquisitionAttention(t('capture.roster_changed'))


def search(player,config):
    game=player.g;worker=player.w;target=CaptureTarget.parse(config,game.root)
    # The path, PC team and healing are prepared once, before forking any core.
    from .telemetry import read_walk_state
    if read_walk_state(game).get('on_bike'):
        from .search_transport import set_bicycle
        set_bicycle(player,False)
    prepared=prepare_hunt(player,config);worker.safe_point()
    if prepared['selected']['method']=='land_mons':
        from .grass_search import prepare_grass
        from .search_odds import wild_odds
        # A timed quality search does not end at its first eligible encounter.
        # Treat its horizon as unknown; do not select walking for a long search
        # merely because finding the first matching species is easy.
        expected=None if target.search_seconds is not None else wild_odds(target,game.root,encounter=prepared['selected']['probability']/100)['expected_encounters']
        prepared['grass_frontier']=prepare_grass(player,prepared['selected'],movement=config.get('search_movement','auto'),expected_encounters=expected,workers=target.search_workers);worker.safe_point()
    baseline=game.capture_save(metadata=False);baseline.publish(game.root/'search-frontier');root=session_paths(game.root).workspaces.root/'search-workers'/uuid.uuid4().hex;root.mkdir(parents=True)
    store=CandidateStore(game.root,'wild',retention=32);history=store.load(lambda mon:target.assess(mon,game.root)) if config.get('_resume_search') else [];offered={v['sha256']:v for v in history}
    budget=SearchBudget(target.search_seconds,remaining=config.get('_remaining_seconds'));auto_accept=False;finish_reason=None
    best=history[0] if history else None;children=[];winner=None;attention=None;accept=False;began=time.monotonic();last_report=0;values=[]
    last_beat=[0]*target.search_workers;last_alive=[began]*target.search_workers
    def rows():
        from .installation_versions import job_identity,require_result
        values=[]
        for folder,_,_ in children:
            value=read_json(folder/'progress.json',{})
            if value:require_result(job_identity(folder),value)
            values.append(value)
        return values
    def preserve(records):
        nonlocal best,history
        for (folder,_,_),record in zip(children,records):
            for candidate in record.get('candidates') or [record.get('best')]:
                if candidate and budget.deadline is not None and candidate.get('seen_at',0)>budget.deadline:continue
                if not candidate or candidate not in rank_candidates([*history,candidate]):continue
                if any(v.get('pokemon',{}).get('uid')==candidate.get('pokemon',{}).get('uid') for v in history):continue
                try:
                    data=CandidateStore(folder,'wild').checkpoint(candidate['sha256']);rated=target.assess(candidate['pokemon'],game.root)
                except (ValueError,OSError,KeyError):continue
                if rated is None:continue
                candidate=dict(rated,sha256=candidate['sha256'],seen_at=candidate.get('seen_at',0));history=store.record(history,candidate,data,top_k=True);best=history[0]
                offered[candidate['sha256']]=candidate
                while len(offered)>32:offered.pop(next(iter(offered)))
    try:
        for lane in range(target.search_workers):
            worker.safe_point();folder=root/str(lane)
            from .installation_versions import pin_job,version_for_job
            pin_job(folder,game.root,'wild_lane')
            version=version_for_job(game.root)
            clone_session(game.root,folder,baseline,installation=folder)
            write_json(folder/'request.json',dict(config=config,prepared=prepared,lane=lane,owner_pid=os.getpid()))
            log=(folder/'worker.log').open('wb')
            try:process=subprocess.Popen([str(version.python),'-I','-B',str(version.worker('wild_search_worker.py')),str(folder)],stdout=log,stderr=log)
            except BaseException:log.close();raise
            children.append((folder,process,log))
        while True:
            worker.safe_point();values=rows();preserve(values);now=time.monotonic()
            if target.search_seconds is not None and budget.deadline is None and all(v.get('heartbeat',0)>0 for v in values):
                budget.start();write_json(root/'deadline.json',dict(at=budget.deadline))
                worker.event('wild_search_budget_started',dict(seconds=budget.allowance,deadline=budget.deadline))
            attention=next((i for i,v in enumerate(values) if v.get('status')=='attention'),None)
            if attention is not None:break
            found=[i for i,v in enumerate(values) if v.get('status')=='found']
            if found:
                # Prefer the best weighted match already published, deterministically.
                winner=max(found,key=lambda i:(target.assess(values[i].get('pokemon'),game.root) or {}).get('rank',[-1]));finish_reason='perfect' if target.search_seconds is not None else 'match';break
            if target.search_seconds is not None and (budget.expired() or any(v.get('status')=='budget_done' for v in values) or best and target.should_capture(best['pokemon'],game.root)):
                finish_reason='time_budget' if budget.expired() or any(v.get('status')=='budget_done' for v in values) else 'perfect'
                accept=True;auto_accept=True;break
            published_on_exit=False
            for i,((folder,process,_),record) in enumerate(zip(children,values)):
                if record.get('heartbeat',0)>last_beat[i]:last_beat[i]=record['heartbeat'];last_alive[i]=now
                if process.poll() is not None:
                    # The child can publish its final atomic record between
                    # rows() and poll(). Re-read after observing process exit.
                    fresh=read_json(folder/'progress.json',{})
                    if fresh.get('status') in ('found','attention','budget_done'):
                        published_on_exit=True;break
                    raise AcquisitionAttention(t('search.worker_exited',lane=i+1))
                if now-last_alive[i]>30:raise AcquisitionAttention(t('search.worker_stalled',lane=i+1))
            if published_on_exit:continue
            if now-last_report>.25:
                count=sum(v.get('attempts',0) for v in values);elapsed=now-began
                worker.update(stage=t('capture.searching',count=count,workers=target.search_workers),search=dict(search_seconds=target.search_seconds,remaining=budget.remaining(),budget_started=budget.deadline is not None,finish_reason=finish_reason,attempts=count,seconds=elapsed,rate=count/max(.001,elapsed),workers=target.search_workers,transport=(prepared.get('grass_frontier')or{}).get('movement'),unique_attempts=sum(v.get('unique_attempts',v.get('attempts',0)) for v in values),best=best,candidates=history,lanes=[dict(lane=i+1,pid=v.get('pid'),cpu_seconds=v.get('cpu_seconds',0),seconds=v.get('seconds',0),mode=v.get('mode'),attempts=v.get('attempts',0),status=v.get('status','starting')) for i,v in enumerate(values)]))
                try:worker.search_preview=(children[0][0]/'screen.ppm').read_bytes()
                except OSError:pass
                last_report=now
            time.sleep(.015)
    except JobPaused:
        budget.freeze()
        if getattr(worker,'accept_best',False):accept=True;worker.accept_best=False
        else:raise
    finally:
        budget.freeze()
        (root/'stop').touch();stop_children(children);values=rows();preserve(values);worker.search_preview=None
        if children:
            from .persistence import SaveSnapshot
            field=children[0][0]/'resume-frontier'
            if all((field/n).is_file() for n in ('FireRed.state','FireRed.sav')):
                SaveSnapshot((field/'FireRed.state').read_bytes(),(field/'FireRed.sav').read_bytes(),0,time.time()).publish(game.root/'search-frontier')
        # Preserve the last metrics/best on pause, without adopting a late winner.
        count=sum(v.get('attempts',0) for v in values);elapsed=time.monotonic()-began
        worker.update(search=dict(search_seconds=target.search_seconds,remaining=budget.remaining(),budget_started=budget.deadline is not None,finish_reason=finish_reason,attempts=count,seconds=elapsed,rate=count/max(.001,elapsed),workers=target.search_workers,transport=(prepared.get('grass_frontier')or{}).get('movement'),unique_attempts=sum(v.get('unique_attempts',v.get('attempts',0)) for v in values),best=best,candidates=history,lanes=[dict(lane=i+1,pid=v.get('pid'),cpu_seconds=v.get('cpu_seconds',0),seconds=v.get('seconds',0),mode=v.get('mode'),attempts=v.get('attempts',0),status=v.get('status')) for i,v in enumerate(values)]))
    worker.safe_point()
    if accept and any(v.get('status')=='attention' for v in values):
        attention=next(i for i,v in enumerate(values) if v.get('status')=='attention');accept=False
    if accept:
        if auto_accept:
            eligible=[v for v in history if target.matches(v['pokemon'],game.root)]
            if not eligible:
                worker.event('wild_search_budget_unmet',dict(seconds=target.search_seconds,candidates=len(history)))
                raise AcquisitionAttention(t('capture.budget_no_candidate'))
            sha=max(eligible,key=lambda v:v['rank'])['sha256']
        else:sha=getattr(worker,'selected_candidate',None) or (best or {}).get('sha256')
        selected=next((v for v in history if v['sha256']==sha),None) or offered.get(sha)
        if not selected:raise AcquisitionAttention(t('search.no_best'))
        game.restore_checkpoint(store.checkpoint(sha))
        reset=getattr(worker,'reset_pacing',None)
        if reset:reset()
        try:check_roster(game,prepared['initial'])
        except (AcquisitionAttention,ValueError):
            game.restore_checkpoint(baseline.state)
            if reset:reset()
            raise
        if prepared.get('grass_frontier'):
            from .grass_search import settle_encounter
            settle_encounter(player,selected['pokemon']['uid'])
        enemy=verified_enemy(player.state())
        if not enemy or (target.assess(enemy,game.root) or {}).get('pokemon')!=selected['pokemon']:raise AcquisitionAttention(t('capture.result_mismatch'))
        worker.safe_point();worker.update(accepted_partial=bool(selected.get('missing')),selection_reason=finish_reason or 'manual_choice',accepted_score=selected['score'],accepted_target_score=selected['target_score']);worker.event('wild_candidate_accepted',dict(sha256=sha,pokemon=enemy,score=selected['score'],target_score=selected['target_score']))
        worker.event('wild_search_selection',dict(reason=finish_reason or 'manual_choice',score=selected['score'],pokemon=enemy,seconds=target.search_seconds))
        relaxed=dict(config,min_ivs=dict.fromkeys(enemy['ivs'],0),exact_ivs=False,search_seconds=None,search_workers=1)
        return run_autocatch(player,relaxed,prepared=prepared)
    selected=attention if attention is not None else winner
    if selected is None:raise AcquisitionAttention(t('search.no_result'))
    record=values[selected];name='attention.state' if attention is not None else 'found.state';data=(children[selected][0]/name).read_bytes()
    if hashlib.sha256(data).hexdigest()!=record.get('sha256'):raise AcquisitionAttention(t('capture.result_mismatch'))
    worker.safe_point();game.restore_checkpoint(data)
    reset=getattr(worker,'reset_pacing',None)
    if reset:reset()
    try:check_roster(game,prepared['initial'])
    except (AcquisitionAttention,ValueError):
        game.restore_checkpoint(baseline.state)
        if reset:reset()
        raise
    if attention is not None:raise AcquisitionAttention(record.get('error') or t('capture.result_mismatch'))
    mon=record.get('pokemon');owned=read_inventory(game);actual=next((m for m in owned['party']+owned['boxes'] if m['uid']==(mon or {}).get('uid')),None)
    if actual is None or actual['uid'] in prepared['initial'] or not target.matches(actual,game.root):raise AcquisitionAttention(t('capture.result_mismatch'))
    worker.verified_catch=actual
    worker.safe_point();worker.event('wild_search_finished',dict(workers=target.search_workers,attempts=sum(v.get('attempts',0) for v in values),seconds=time.monotonic()-began,winner=selected,pokemon=actual))
    return actual
