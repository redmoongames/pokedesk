"""Bounded process pool; each core and result stays in private worker Data."""

from .paths import session_paths, bind_installation
from pathlib import Path
import json,subprocess,time,uuid,hashlib,os
from .starter_candidates import assess,load as load_candidates,record
from .starter_checkpoint import valid_frontier
from .persistence import atomic_bytes
from .acquisition_play import JobPaused
from .acquisition import read_json,write_json
from .i18n import t
from .telemetry import read_party_mon,symbols

class LaneHealth:
    def __init__(self,count,now,timeout=15):
        self.timeout=timeout;self.last=[now]*count;self.attempts=[0]*count
    def check(self,values,processes,now):
        for i,(value,process) in enumerate(zip(values,processes)):
            attempts=value.get('attempts',0)
            if attempts>self.attempts[i]:self.attempts[i]=attempts;self.last[i]=now
            if value.get('status') in ('found','error'):continue
            if value.get('status')=='stopped':raise RuntimeError(t('search.worker_exited',lane=i+1))
            if process.poll() is not None:raise RuntimeError(t('search.worker_exited',lane=i+1))
            if now-self.last[i]>self.timeout:raise RuntimeError(t('search.worker_stalled',lane=i+1))

from .search_processes import stop_children


def search(game,config,worker,progress,*,benchmark_seconds=None):
    if not valid_frontier(game):raise RuntimeError(t('search.invalid_frontier'))
    count=config.search_workers
    if type(count) is not int or not 1<=count<=4:raise ValueError(t('odds.invalid_workers'))
    base=progress.get('attempts',0);base_seconds=progress.get('search_seconds',0);began=time.monotonic()
    root=session_paths(game.root).workspaces.root/'search-workers'/uuid.uuid4().hex;root.mkdir(parents=True)
    initial=game.capture_save(metadata=False).state;children=[];winner=None;last_report=0;health=LaneHealth(count,began);accept_best=False
    progress.pop('best',None);progress.pop('candidates',None)
    history=load_candidates(game.root,config);best=history[0] if history else None;best_path=game.root/'Data/starter-best.state'
    def pick_best(values):
        choices=[v['best'] for v in values if v.get('best')]
        if best:choices.append(best)
        return max(choices,key=lambda v:v['rank']) if choices else None
    def preserve_best(values):
        nonlocal best,history
        selected=pick_best(values)
        if selected and (not best or selected['rank']>best['rank']):
            path=next((folder/'best.state' for (folder,_,_),v in zip(children,values) if v.get('best',{}).get('sha256')==selected['sha256']),None)
            if path and path.is_file():
                data=path.read_bytes()
                if hashlib.sha256(data).hexdigest()==selected['sha256']:
                    history=record(game.root,history,selected,data);best=selected
        if best:progress.update(best=best,candidates=history)
    python=session_paths(game.root).installation.python
    def rows():
        from .installation_versions import job_identity,require_result
        values=[]
        for folder,process,log in children:
            value=read_json(folder/'progress.json',{})
            if value:require_result(job_identity(folder),value)
            values.append(value)
        return values
    def update(values):
        progress['attempts']=base+sum(v.get('attempts',0) for v in values);progress['search_seconds']=base_seconds+time.monotonic()-began
    try:
        for lane in range(count):
            worker.safe_point()
            folder=root/str(lane);(folder/'Data').mkdir(parents=True)
            from .installation_versions import pin_job,version_for_job
            pin_job(folder,game.root,'starter_lane')
            version=version_for_job(game.root)
            (folder/'Data/FireRed.gba').symlink_to(os.path.relpath((game.root/'Data/FireRed.gba').resolve(),(folder/'Data').resolve()))
            if (game.root/'Data/game.json').exists():(folder/'Data/game.json').write_bytes((game.root/'Data/game.json').read_bytes())
            (folder/'Data/FireRed.state').write_bytes(initial)
            write_json(folder/'request.json',dict(config=config.json(),lane=lane,lanes=count,benchmark_seconds=benchmark_seconds,owner_pid=os.getpid(),supervisor_pid=getattr(worker,'parent_pid',None)))
            log=(folder/'worker.log').open('wb')
            process=subprocess.Popen([str(version.python),'-I','-B',str(version.worker('starter_search_worker.py')),str(folder)],stdout=log,stderr=log)
            children.append((folder,process,log))
        while True:
            worker.safe_point();values=rows();update(values)
            if not benchmark_seconds:health.check(values,[p for _,p,_ in children],time.monotonic())
            failed=next((v for v in values if v.get('status')=='error'),None)
            if failed:raise RuntimeError(t('search.parallel_failed',reason=failed.get('error','')))
            found=[(v.get('first_match_seconds',1e20),i) for i,v in enumerate(values) if v.get('status')=='found']
            if found:winner=min(found)[1];break
            if all(process.poll() is not None for _,process,_ in children):
                if benchmark_seconds:break
                raise RuntimeError(t('search.parallel_failed',reason=t('search.no_result')))
            if time.monotonic()-last_report>.5:
                elapsed=time.monotonic()-began;preserve_best(values)
                detail=dict(seconds=elapsed,total_seconds=base_seconds+elapsed,attempts=progress['attempts'],session_attempts=progress['attempts']-base,rate=(progress['attempts']-base)/max(.001,elapsed),workers=count,best=best,candidates=history,lanes=[dict(lane=i+1,attempts=v.get('attempts',0),status=v.get('status','starting')) for i,v in enumerate(values)])
                worker.update(stage=t('search.parallel_progress',count=progress['attempts'],workers=count),prologue=progress,search_workers=count,search=detail)
                last_report=time.monotonic()
            time.sleep(.015)
    except JobPaused:
        if getattr(worker,'accept_best',False):accept_best=True;worker.accept_best=False
        else:raise
    finally:
        (root/'stop').touch()
        stop_children(children)
        values=rows();update(values)
        preserve_best(values)
        # Resume from the earliest unfinished lane. Ahead-of-frontier candidates
        # can be retried after cancellation; no pending candidate is accepted.
        available=[(v.get('next_index',0),i) for i,v in enumerate(values) if v and (children[i][0]/'frontier.state').is_file()]
        if available:game.restore_checkpoint((children[min(available)[1]][0]/'frontier.state').read_bytes())
        else:game.restore_checkpoint(initial)
    # Cancellation can arrive while child processes are shutting down. Keep the
    # pre-gift frontier in that case instead of importing a late winner.
    worker.safe_point()
    stats=dict(seconds=time.monotonic()-began,workers=count,attempts=sum(v.get('attempts',0) for v in values),lanes=values,folder=str(root))
    stats['candidates_per_second']=stats['attempts']/max(.001,stats['seconds'])
    if benchmark_seconds:return None,stats
    if accept_best:
        if not best:raise RuntimeError(t('search.no_best'))
        chosen=getattr(worker,'selected_candidate',None);candidate=next((v for v in history if v['sha256']==chosen),None) if chosen else best
        if not candidate:raise RuntimeError(t('search.no_best'))
        path=game.root/'Data/starter-candidates'/(candidate['sha256']+'.state')
        if not path.is_file():path=best_path
        data=path.read_bytes()
        if hashlib.sha256(data).hexdigest()!=candidate['sha256']:raise RuntimeError(t('prologue.final_mismatch'))
        game.restore_checkpoint(data);mon=read_party_mon(game,symbols(game.root)['gPlayerParty'],0)
        if mon['uid']!=candidate['pokemon']['uid'] or not assess(config,mon):raise RuntimeError(t('prologue.final_mismatch'))
        progress.update(accepted_uid=mon['uid'],starter_uid=mon['uid'],found=mon,search_stats=stats);return mon,stats
    if winner is None:raise RuntimeError(t('search.no_result'))
    game.restore_checkpoint((children[winner][0]/'found.state').read_bytes());mon=read_party_mon(game,symbols(game.root)['gPlayerParty'],0)
    if not config.matches(mon) or mon['uid']!=values[winner]['uid']:raise RuntimeError(t('prologue.final_mismatch'))
    progress.update(starter_uid=mon['uid'],found=mon,search_stats=stats)
    return mon,stats
