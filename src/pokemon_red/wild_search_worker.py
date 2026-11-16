"""One low-priority wild-search lane. Every core belongs to this process."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import hashlib,json,os,signal,time,resource
from pokemon_red.engine import Game
from pokemon_red.journey import Journey
from pokemon_red.autocatch import run_autocatch
from pokemon_red.acquisition import read_json,write_json
from pokemon_red.acquisition_play import JobPaused
from pokemon_red.persistence import atomic_bytes
from pokemon_red.search_candidates import CandidateStore
from pokemon_red.worker_pacing import FramePacer
from pokemon_red.search_budget import SearchDeadline


class Lane:
    def __init__(self,folder):
        self.job=Path(folder);self.request=read_json(self.job/'request.json',{});self.config=self.request['config'];self.game=None
        self.deadline=None;self.stop=False;self.next_stop_check=0;self.next_report=0;self.beat=0;self.attempts=0;self.best=None;self.history=[];self.sample=[];self.seen=set();self.unique_attempts=0;self.current_encounter_uid=None
        self.searching=False;self.started=time.monotonic();self.cpu_started=time.process_time()
        self.pacer=FramePacer(self.config.get('max_auto_speed',12));self.store=CandidateStore(self.job,'wild')
        self.status=dict(status='starting',lane=self.request['lane'],attempts=0,heartbeat=0,sample=[])
    def event(self,code,details):
        with (self.job/'events.jsonl').open('a') as file:file.write(json.dumps(dict(code=code,details=details),ensure_ascii=False)+'\n')
    def update(self,**values):self.status.update(values)
    def before_frame(self):
        if self.stop or os.getppid()!=self.request['owner_pid']:raise JobPaused()
        now=time.monotonic()
        if now>=self.next_stop_check:
            self.next_stop_check=now+.01
            if (self.job.parent/'stop').exists():self.stop=True;raise JobPaused()
            if self.config.get('search_seconds') is not None and self.deadline is None:
                self.deadline=read_json(self.job.parent/'deadline.json',{}).get('at')
        if self.deadline is not None and now>=self.deadline:raise SearchDeadline()
    def heartbeat(self):
        self.before_frame()
        # Read revocation before every frame and before every pacing sleep.
        if self.game and not self.searching:self.pacer.step(self.game.frame,generation=self.game.state_generation)
        now=time.monotonic()
        if now<self.next_report:return
        self.next_report=now+.25;self.beat+=1
        self.status.update(heartbeat=self.beat,attempts=self.attempts,best=self.best,candidates=self.history,sample=self.sample,unique_attempts=self.unique_attempts,pid=os.getpid(),cpu_seconds=time.process_time()-self.cpu_started,seconds=time.monotonic()-self.started,rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,mode='grass_frontier' if self.searching else 'ordinary',updated_at=time.time(),frame=self.game.frame if self.game else None)
        write_json(self.job/'progress.json',self.status)
        if self.game and self.request['lane']==0:atomic_bytes(self.job/'screen.ppm',b'P6\n240 160\n255\n'+self.game.rgb())
    def safe_point(self):self.heartbeat()
    def candidate(self,target,mon):
        seen_at=time.monotonic()
        if self.deadline is not None and seen_at>=self.deadline:raise SearchDeadline()
        if not self.searching and self.current_encounter_uid==mon['uid']:return
        self.attempts+=1
        if mon['uid'] not in self.seen:
            self.unique_attempts+=1
            if len(self.sample)<256:self.sample.append(mon['uid'])
        if len(self.seen)<100000:self.seen.add(mon['uid'])
        candidate=target.assess(mon,self.game.root)
        from pokemon_red.search_candidates import rank_candidates
        if candidate and candidate in rank_candidates([*self.history,candidate]):
            data=self.game.capture_save(metadata=False).state;candidate=dict(candidate,sha256=hashlib.sha256(data).hexdigest(),seen_at=seen_at)
            self.history=self.store.record(self.history,candidate,data,top_k=True);self.best=self.history[0]
    def reset_pacing(self):self.pacer=FramePacer(self.config.get('max_auto_speed',12))
    def run(self):
        signal.signal(signal.SIGTERM,lambda *_:setattr(self,'stop',True));signal.signal(signal.SIGINT,lambda *_:setattr(self,'stop',True))
        try:os.nice(10)
        except OSError:pass
        with Game(self.job) as game:
            self.game=game;self.status['status']='running'
            try:
                player=Journey(game,self)
                # Ordinary idle frames diversify encounter timing; no RNG, PID,
                # IV, roster or story flag is edited to manufacture a result.
                if self.request['prepared'].get('grass_frontier'):
                    from pokemon_red.grass_search import sample_grass
                    mon=sample_grass(player,self.config,self.request['prepared'])
                else:
                    player.advance(17*(self.request['lane']+1))
                    mon=run_autocatch(player,self.config,prepared=self.request['prepared'])
                self.safe_point();data=game.capture_save(metadata=False).state
                atomic_bytes(self.job/'found.state',data,durable=True)
                self.status.update(status='found',pokemon=mon,sha256=hashlib.sha256(data).hexdigest(),found_at=time.monotonic())
            except SearchDeadline:self.status['status']='budget_done'
            except JobPaused:self.status['status']='stopped'
            except Exception as error:
                data=game.capture_save(metadata=False).state;atomic_bytes(self.job/'attention.state',data,durable=True)
                self.status.update(status='attention',attention_kind='safety',error=str(error),sha256=hashlib.sha256(data).hexdigest())
            finally:
                if getattr(self,'resume_snapshot',None):self.resume_snapshot.publish(self.job/'resume-frontier')
                self.status.update(attempts=self.attempts,best=self.best,candidates=self.history,sample=self.sample,unique_attempts=self.unique_attempts,pid=os.getpid(),cpu_seconds=time.process_time()-self.cpu_started,seconds=time.monotonic()-self.started,heartbeat=self.beat+1,updated_at=time.time())
                write_json(self.job/'progress.json',self.status)
        return 0

if __name__=='__main__':
    from pokemon_red.installation_versions import validate_worker
    validate_worker(Path(sys.argv[1]))
    raise SystemExit(Lane(sys.argv[1]).run())
