"""Measure takeover during real 50k-cycle analytics on a private fixture copy.

Accepts an old or new project root for paired comparisons. Never opens the live
profile; all journal rows, saves and simulation frames are disposable.
"""
from pathlib import Path
import argparse
import hashlib
import json
import platform
import statistics
import sys
import tempfile
import threading
import time


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--fixture-project',type=Path,help='Private ROM/fixture installation, separate from immutable code')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--cycles',type=int,default=50000)
    parser.add_argument('--repetitions',type=int,default=7)
    parser.add_argument('--speeds',type=float,nargs='+',default=[8,16])
    args=parser.parse_args();project=args.project.resolve();fixtures=(args.fixture_project or project).resolve()
    if args.cycles<1 or args.repetitions<1:parser.error('Counts must be positive')
    sys.path.insert(0,str(project/'src'))
    from pokemon_red.engine_runtime import EngineRuntime
    from pokemon_red.history import History
    from pokemon_red.engine import Game
    from pokemon_red.telemetry import read_state

    class BenchmarkRuntime(EngineRuntime):
        def __init__(self,*a,**k):
            self.takeover_times={};self.last_forced_publish_ms=0;self.capture_spans=[]
            super().__init__(*a,**k)
        def publish(self,c,*,force=False):
            at=time.perf_counter();result=super().publish(c,force=force)
            if force:self.last_forced_publish_ms=(time.perf_counter()-at)*1000
            return result
        def consume_interrupt(self,c):
            if not self.interrupted.is_set():return super().consume_interrupt(c)
            at=time.perf_counter();result=super().consume_interrupt(c)
            if result:self.takeover_times[self.applied_epoch]=dict(owner_started=at,consume_ms=(time.perf_counter()-at)*1000,publish_ms=self.last_forced_publish_ms)
            return result
        def _dispatch(self,c,method,params):
            if method=='benchmark_reset':
                if not getattr(c,'benchmark_capture_installed',False):
                    original=c.game.capture_save
                    def capture(*a,**k):
                        at=time.perf_counter()
                        try:return original(*a,**k)
                        finally:self.capture_spans.append((at,time.perf_counter()))
                    c.game.capture_save=capture;c.benchmark_capture_installed=True
                c.history._comparisons_cache=None;c.set_speed(params[0]);return
            if method=='benchmark_saved':return dict(frame=c.game.frame,last_saved=c.last_saved_frame,pending=bool(c.pending_writes))
            if method=='history_read':
                if not hasattr(self,'history_service'):self.query_entered.set()
                started=time.perf_counter();result=super()._dispatch(c,method,params)
                self.dispatch_ms=(time.perf_counter()-started)*1000
                self.query_future=result
                self.query_accepted.set()
                return result
            return super()._dispatch(c,method,params)

    rows=[]
    with tempfile.TemporaryDirectory(prefix='Pokemon analytics benchmark ') as temporary:
        root=Path(temporary);(root/'Data').mkdir()
        for name in ('src','native','vendor','assets','runtime','Bots'):(root/name).symlink_to(project/name,target_is_directory=True)
        (root/'Data/FireRed.gba').symlink_to(fixtures/'Data/FireRed.gba')
        (root/'Data/FireRed.state').write_bytes((fixtures/'tests/fixtures/fire_red/clinic.state').read_bytes())
        (root/'Data/settings.json').write_text(json.dumps(dict(sound_enabled=False,panel_on_start=False,speed=8,scale=1,autosave_enabled=True,autosave_seconds=5)))
        history=History(root);db=history.db
        db.execute('INSERT INTO training_runs VALUES(?,?,?,?,?,?,?,?,?,?)',('run','t','t','Route1','adaptive','target',15,'completed','team','{}'))
        body=json.dumps(dict(team=[],clinic='clinic',area=[],context={},speed_intervals=[dict(speed=8)],padding='x'*1024))
        db.executemany('INSERT INTO training_cycles(run_id,number,started_at,ended_at,status,game_seconds,active_seconds,target_xp,team_xp,battles,team_fingerprint,body) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(('run',i,'t','t','completed',120,20,100,100,1,'team',body) for i in range(args.cycles)));db.commit();history.close()
        runtime=BenchmarkRuntime(root,paused=True);runtime.query_entered=threading.Event();runtime.query_accepted=threading.Event()
        try:
            runtime.ready.result(30)
            for speed in args.speeds:
                for repetition in range(args.repetitions):
                    runtime.query_entered.clear();runtime.query_accepted.clear()
                    runtime.submit('benchmark_reset',speed).result(5)
                    frame=runtime.latest.frame;started=time.perf_counter()
                    query=runtime.submit('history_read','comparisons',())
                    if hasattr(runtime,'history_service'):
                        if not runtime.query_accepted.wait(10):raise RuntimeError('Query not accepted')
                        if not runtime.query_future.work_started.wait(30):raise RuntimeError('Worker not aggregating')
                        worker_pid=runtime.query_future.worker_pid
                    else:
                        if not runtime.query_entered.wait(5):raise RuntimeError('Query not started')
                        worker_pid=None
                    busy=not query.done();at=time.perf_counter();epoch=runtime.take_control(pause=False)
                    call_ms=(time.perf_counter()-at)*1000
                    deadline=time.monotonic()+5
                    while runtime.latest.epoch<epoch and time.monotonic()<deadline:time.sleep(.001)
                    ack_ms=(time.perf_counter()-at)*1000
                    if runtime.latest.epoch<epoch:raise RuntimeError('Takeover was not acknowledged')
                    frame_at_ack=runtime.latest.frame;manual_at=time.perf_counter()
                    runtime.submit('manual','B',True).result(5)
                    manual_ms=(time.perf_counter()-manual_at)*1000;manual_during_query=not query.done()
                    runtime.submit('manual','B',False).result(5)
                    values=query.result(30)
                    if sum(row['cycles'] for row in values)!=args.cycles:raise RuntimeError('Historical data was lost')
                    row=dict(speed=speed,repetition=repetition+1,takeover_call_ms=call_ms,takeover_ack_ms=ack_ms,query_total_ms=(time.perf_counter()-started)*1000,dispatch_ms=runtime.dispatch_ms,work_in_progress_at_takeover=busy,worker_pid=worker_pid,frames_before_takeover=frame_at_ack-frame,manual_command_ms=manual_ms,manual_accepted_while_query_running=manual_during_query)
                    detail=runtime.takeover_times.get(epoch,{})
                    row.update(owner_wait_ms=(detail.get('owner_started',at)-at)*1000,consume_ms=detail.get('consume_ms'),forced_publish_ms=detail.get('publish_ms'))
                    row['capture_overlapped_takeover']=any(begin<detail.get('owner_started',at) and end>at for begin,end in runtime.capture_spans)
                    rows.append(row);print(json.dumps(row),flush=True)
            epoch=runtime.take_control(pause=True);deadline=time.monotonic()+5
            while runtime.latest.epoch<epoch and time.monotonic()<deadline:time.sleep(.001)
            runtime.submit('save',True).result(10)
            saved=runtime.submit('benchmark_saved').result(5)
        finally:
            runtime.take_control(close=True);runtime.finished.result(15);runtime.thread.join(2)
        with Game(root) as game:
            restored_frame=game.frame;restored_ready=bool(read_state(game).get('ready'))
            roundtrip=restored_frame==saved['frame'] and restored_ready
    summary=[]
    for speed in args.speeds:
        samples=sorted(row['takeover_ack_ms'] for row in rows if row['speed']==speed)
        summary.append(dict(speed=speed,samples=len(samples),median_ms=statistics.median(samples),p95_ms=samples[min(len(samples)-1,int(.95*len(samples)))],max_ms=max(samples)))
    tree=hashlib.sha256()
    for path in sorted((project/'src/pokemon_red').rglob('*')):
        if path.is_file() and path.suffix in ('.py','.json') and '__pycache__' not in path.parts:
            tree.update(path.relative_to(project).as_posix().encode()+b'\0'+path.read_bytes()+b'\0')
    report=dict(schema=2,takeover_pauses_game=False,cycles=args.cycles,repetitions=args.repetitions,rows=rows,summary=summary,save_roundtrip=roundtrip,saved_frame=saved['frame'],restored_frame=restored_frame,restored_ready=restored_ready,captures=len(runtime.capture_spans),all_queries_in_progress=all(row['work_in_progress_at_takeover'] for row in rows),source_sha256=hashlib.sha256((project/'src/pokemon_red/engine_runtime.py').read_bytes()).hexdigest(),runtime_sha256=tree.hexdigest(),fixture_sha256=hashlib.sha256((fixtures/'tests/fixtures/fire_red/clinic.state').read_bytes()).hexdigest(),native_sha256={name:hashlib.sha256((project/'native'/name).read_bytes()).hexdigest() for name in ('libpokemon.dylib','mgba_libretro.dylib')},environment=dict(machine=platform.machine(),macos=platform.mac_ver()[0],python=platform.python_version()))
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(summary),flush=True)


if __name__=='__main__':main()
