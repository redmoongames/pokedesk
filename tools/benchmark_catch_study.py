"""Reproducible private-copy wild-search study. No writes to the supplied save.

Usage: bundled-python benchmark_catch.py --project ROOT --save SAVE_DIR --out OUT
Worker mode is internal and always receives its own cloned Data.
"""
from pathlib import Path
import argparse,sys,json,shutil,time,os,subprocess,hashlib,random,statistics

def arguments():
 p=argparse.ArgumentParser();p.add_argument('--project',type=Path,required=True);p.add_argument('--save',type=Path);p.add_argument('--out',type=Path,required=True);p.add_argument('--worker',type=Path);p.add_argument('--only-mode');p.add_argument('--species',type=int,default=43);p.add_argument('--route',default='Route14');p.add_argument('--count',type=int,default=0);p.add_argument('--workers',type=int,nargs='+',default=[4]);p.add_argument('--caps',type=int,nargs='+',default=[4,8,12,16]);p.add_argument('--paced',action='store_true');p.add_argument('--seconds',type=float,default=12);p.add_argument('--repeats',type=int,default=3);p.add_argument('--part',choices=('smoke','scale','movement','capped','budget'),default='scale');return p.parse_args()
a=arguments();a.project=a.project.resolve();a.out=a.out.resolve();sys.path.insert(0,str(a.project/'src'))
from pokemon_red.engine import Game
from pokemon_red.journey import Journey
from pokemon_red.acquisition import read_json,write_json
from pokemon_red.operations import clone_session
from pokemon_red.grass_search import prepare_grass
from pokemon_red.autocatch import prepare_hunt
from pokemon_red.models import STAT_KEYS,read_roster_uids
from pokemon_red.wild_search_worker import Lane
from pokemon_red.acquisition_play import JobPaused
from pokemon_red.search_processes import stop_children
from pokemon_red.engine_runtime import EngineRuntime

class StudyLane(Lane):
 def heartbeat(self):
  if self.searching and self.game:
   key=(self.game.state_generation,self.game.frame)
   if key!=getattr(self,'bench_frame_key',None):self.executed_frames=getattr(self,'executed_frames',0)+1;self.bench_frame_key=key
   if self.request.get('pace_sampling'):self.pacer.step(self.executed_frames)
  super().heartbeat()
 def candidate(self,target,mon):
  super().candidate(target,mon)
  if mon['uid'] not in self.sample and len(self.sample)<20000:self.sample.append(mon['uid'])
  budget=self.request.get('budget')
  if not budget:return
  warm=self.request.get('warmup',20)
  if self.attempts==warm:
   write_json(self.job/'ready.json',dict(pid=os.getpid()))
   while not (self.job.parent/'start.json').exists():self.before_frame();time.sleep(.005)
   from pokemon_red.worker_pacing import FramePacer
   self.pacer=FramePacer(self.config.get('max_auto_speed',12));self.bench_frame_start=self.executed_frames
   self.bench_cpu=time.process_time();self.bench_hash=hashlib.sha256();self.bench_unique=set()
  elif self.attempts>warm:
   self.bench_hash.update(mon['uid'].encode()+bytes(mon['ivs'].values()));self.bench_unique.add(mon['uid'])
   if self.attempts==warm+budget:
    write_json(self.job/'complete.json',dict(finished=time.monotonic(),cpu_seconds=time.process_time()-self.bench_cpu,count=budget,executed_frames=self.executed_frames-self.bench_frame_start,fingerprint=self.bench_hash.hexdigest(),unique=len(self.bench_unique),pid=os.getpid()))
    raise JobPaused()


if a.worker:
 raise SystemExit(StudyLane(a.worker).run())

class PrepWorker:
 def before_frame(self):pass
 def heartbeat(self):pass
 def safe_point(self):pass
 def event(self,*args):pass
 def update(self,**kw):pass

def root_at(path,save):
 (path/'Data').mkdir(parents=True,exist_ok=True)
 for name in ('native','vendor','assets','runtime','Bots','src'):
  if not (path/name).exists():(path/name).symlink_to(a.project/name)
 if not (path/'Data/FireRed.gba').exists():(path/'Data/FireRed.gba').symlink_to(a.project/'Data/FireRed.gba')
 for name in ('FireRed.state','FireRed.sav'):
  (path/'Data'/name).unlink(missing_ok=True);shutil.copy2(save/name,path/'Data'/name)
 write_json(path/'Data/settings.json',dict(language='en',sound_enabled=False,autosave_enabled=True,scale=1))
 return path

a.out.mkdir(parents=True,exist_ok=True)
import fcntl
output_lock=(a.out/'benchmark.lock').open('a')
try:fcntl.flock(output_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
except BlockingIOError:raise SystemExit('Another benchmark is already using this --out directory.')
if any(n<1 or n>6 for n in a.workers) or any(c<1 or c>16 for c in a.caps) or a.seconds<=0 or a.repeats<1 or a.count and a.count<max(a.workers):
 raise SystemExit('Use 1-6 workers, caps 1-16, positive seconds/repeats and count >= workers.')
from pokemon_red.editions import edition
if edition(a.project).id!='firered':raise SystemExit('This reproducible study recipe targets FireRed.')
source=hashlib.sha256(Path(__file__).read_bytes())
for path in sorted((a.project/'src').rglob('*.py')):
 source.update(str(path.relative_to(a.project)).encode());source.update(path.read_bytes())
for name in ('native/libpokemon.dylib','native/mgba_libretro.dylib'):
 source.update((a.project/name).read_bytes())
manifest=a.out/'benchmark-version.json';version=source.hexdigest();prior=read_json(manifest,{})
if prior and (prior.get('source_sha256')!=version or prior.get('recipe')!=dict(species=a.species,route=a.route)):
 raise SystemExit('Project or recipe changed. Use a fresh --out directory to avoid mixing versions.')
if not prior and ((a.out/'results.jsonl').exists() or (a.out/'budget-results.jsonl').exists()):
 raise SystemExit('Output lacks version provenance. Use a fresh --out directory.')
write_json(manifest,dict(source_sha256=version,recipe=dict(species=a.species,route=a.route),python=sys.version,pacing_clock='executed_frames',created=time.time()))
fixture=a.out/'fixture'
if not fixture.exists():
 fixture.mkdir()
 if a.save is None:raise SystemExit('--save must name a directory containing FireRed.state and FireRed.sav')
 for name in ('FireRed.state','FireRed.sav'):shutil.copy2(a.save/name,fixture/name)
 write_json(a.out/'source.json',dict(save_sha256=hashlib.sha256((fixture/'FireRed.state').read_bytes()).hexdigest(),source=str(a.save),created=time.time()))

def prepare(mode):
 base=a.out/('base-'+mode)
 if not (base/'prepared.json').exists():
  root_at(base,fixture);cfg=dict(species_id=a.species,gender='any',route=a.route,method='land_mons',min_ivs=dict.fromkeys(STAT_KEYS,31),search_workers=1)
  with Game(base) as game:
   player=Journey(game,PrepWorker());prepared=prepare_hunt(player,cfg)
   try:prepared['grass_frontier']=prepare_grass(player,prepared['selected'],movement=mode)
   except Exception:
    game.save_to(base/'failure');write_json(base/'failure-state.json',player.state());raise
   game.save_to(base/'Data');write_json(base/'prepared.json',prepared)
  print('PREPARED',mode,prepared['grass_frontier'].get('movement'),prepared['grass_frontier']['pair'],flush=True)
 return base

def trial(mode,cap,workers,repeat,pace=False):
 if a.count:return budget_trial(mode,cap,workers,repeat,pace)
 key=f'{a.part}-{mode}-{cap}-{workers}-{repeat}';base=prepare(mode);root=a.out/key;root_at(root,base/'Data');prepared=read_json(base/'prepared.json');pool=root/'pool';pool.mkdir();children=[];rows=[];latency=[];actor=None
 cfg=dict(species_id=a.species,gender='any',route=a.route,method='land_mons',min_ivs=dict.fromkeys(STAT_KEYS,31),priority_ivs=['speed'],search_workers=workers,max_auto_speed=cap)
 try:
  actor=EngineRuntime(root,paused=True);actor.ready.result(10)
  with Game(base) as game:baseline=game.capture_save(metadata=False)
  for lane in range(workers):
   folder=pool/str(lane);clone_session(root,folder,baseline);write_json(folder/'request.json',dict(config=cfg,prepared=prepared,lane=lane,owner_pid=os.getpid(),pace_sampling=pace));log=(folder/'worker.log').open('wb');proc=subprocess.Popen([str(a.project/'runtime/python/cpython-3.12.16-macos-aarch64-none/bin/python3'),'-I','-B',str(Path(__file__).resolve()),'--project',str(a.project),'--out',str(a.out),'--worker',str(folder)],stdout=log,stderr=log);children.append((folder,proc,log))
  def progress():return [read_json(f/'progress.json',{}) for f,_,_ in children]
  deadline=time.monotonic()+30
  while time.monotonic()<deadline:
   rows=progress()
   if any(r.get('status')=='attention' for r in rows):raise RuntimeError(str([(r.get('status'),r.get('error')) for r in rows]))
   if all(r.get('attempts',0)>0 for r in rows):break
   time.sleep(.03)
  else:raise TimeoutError('worker startup')
  # Exclude interpreter startup and initial best-checkpoint burst.
  warm=time.monotonic()+2
  while time.monotonic()<warm:time.sleep(.05)
  initial=progress();start=time.monotonic();next_probe=start
  while time.monotonic()-start<a.seconds:
   rows=progress()
   if any(r.get('status')=='attention' for r in rows):raise RuntimeError(str([(r.get('status'),r.get('error')) for r in rows]))
   if any(p.poll() is not None for _,p,_ in children):raise RuntimeError('worker exited')
   if time.monotonic()>=next_probe:
    at=time.monotonic();actor.submit('clear_keys').result(3);latency.append(time.monotonic()-at);next_probe=time.monotonic()+.5
   time.sleep(.02)
  end=time.monotonic();rows=progress();stop_at=time.monotonic();(pool/'stop').touch();stop_children(children);children=[];stopped=time.monotonic();final=[read_json(f/'progress.json',{}) for f in sorted(pool.iterdir()) if f.is_dir()]
  attempts=sum(r['attempts'] for r in rows)-sum(r['attempts'] for r in initial);sample={uid for r in rows for uid in r.get('sample',[])};oldsample={uid for r in initial for uid in r.get('sample',[])}
  record=dict(key=key,mode=mode,actual_mode=prepared['grass_frontier'].get('movement'),cap=cap,workers=workers,repeat=repeat,paced_sampling=pace,seconds=end-start,attempts=attempts,rate=attempts/(end-start),new_unique=len(sample-oldsample),unique_rate=len(sample-oldsample)/(end-start),stop_seconds=stopped-stop_at,owner_p95_seconds=sorted(latency)[int(.95*(len(latency)-1))],lanes=[{k:r.get(k) for k in ('pid','attempts','cpu_seconds','seconds','unique_attempts','rss_bytes','status','error')} for r in final])
  with Game(root) as game:record['roster_preserved']=set(prepared['initial'])<=read_roster_uids(game)
  write_json(root/'report.json',record)
  with (a.out/'results.jsonl').open('a') as f:f.write(json.dumps(record)+'\n')
  print('RESULT',json.dumps(record),flush=True)
 except Exception as e:
  print('FAILED',key,str(e),flush=True);raise
 finally:
  if children:(pool/'stop').touch();stop_children(children)
  if actor:actor.take_control(close=True);actor.finished.result(20)

def budget_trial(mode,cap,workers,repeat,pace):
 key=f'budget-{int(pace)}-{mode}-{cap}-{workers}-{repeat}-{a.count}'
 base=prepare(mode);root=a.out/key
 if (root/'report.json').exists():return
 if root.exists():root.rename(root.with_name(root.name+'-interrupted-'+str(time.time_ns())))
 root_at(root,base/'Data');prepared=read_json(base/'prepared.json');pool=root/'pool';pool.mkdir(exist_ok=True);children=[];actor=None;latency=[]
 cfg=dict(species_id=a.species,gender='any',route=a.route,method='land_mons',min_ivs=dict.fromkeys(STAT_KEYS,31),priority_ivs=['speed'],search_workers=workers,max_auto_speed=cap)
 try:
  actor=EngineRuntime(root,paused=True);actor.ready.result(10)
  with Game(base) as game:baseline=game.capture_save(metadata=False)
  q,r=divmod(a.count,workers)
  for lane in range(workers):
   folder=pool/str(lane);clone_session(root,folder,baseline);write_json(folder/'request.json',dict(config=cfg,prepared=prepared,lane=lane,owner_pid=os.getpid(),pace_sampling=pace,budget=q+int(lane<r),warmup=20));log=(folder/'worker.log').open('wb');proc=subprocess.Popen([str(a.project/'runtime/python/cpython-3.12.16-macos-aarch64-none/bin/python3'),'-I','-B',str(Path(__file__).resolve()),'--project',str(a.project),'--out',str(a.out),'--worker',str(folder)],stdout=log,stderr=log);children.append((folder,proc,log))
  def check():
   for f,p,_ in children:
    if p.poll() is not None and not (f/'complete.json').exists():raise RuntimeError(str(read_json(f/'progress.json',{})))
  limit=time.monotonic()+120
  while not all((f/'ready.json').exists() for f,_,_ in children):
   check()
   if time.monotonic()>limit:raise TimeoutError('warmup')
   time.sleep(.02)
  start=time.monotonic();write_json(pool/'start.json',dict(start=start));limit=start+600;next_probe=start
  while not all((f/'complete.json').exists() for f,_,_ in children):
   check()
   if time.monotonic()>limit:raise TimeoutError('1000 candidates')
   if time.monotonic()>=next_probe:
    t=time.monotonic();actor.submit('clear_keys').result(3);latency.append(time.monotonic()-t);next_probe=time.monotonic()+1
   time.sleep(.02)
  done=[read_json(f/'complete.json') for f,_,_ in children];elapsed=max(r['finished'] for r in done)-start
  (pool/'stop').touch();stop_children(children);children=[]
  record=dict(key=key,mode=mode,actual_mode=prepared['grass_frontier'].get('movement'),cap=cap,workers=workers,paced_sampling=pace,count=sum(r['count'] for r in done),executed_frames=sum(r['executed_frames'] for r in done),seconds=elapsed,rate=a.count/elapsed,cpu_seconds=sum(r['cpu_seconds'] for r in done),cpu_per_1000=sum(r['cpu_seconds'] for r in done)*1000/a.count,mean_cpu_cores=sum(r['cpu_seconds'] for r in done)/elapsed,fingerprints=[r['fingerprint'] for r in done],lanes=done,owner_p95_seconds=sorted(latency)[int(.95*(len(latency)-1))])
  assert record['count']==a.count
  write_json(root/'report.json',record)
  with (a.out/'budget-results.jsonl').open('a') as f:f.write(json.dumps(record)+'\n')
  print('BUDGET',json.dumps(record),flush=True)
 finally:
  if children:(pool/'stop').touch();stop_children(children)
  if actor:actor.take_control(close=True);actor.finished.result(20)

completed={r['key'] for r in [json.loads(v) for v in (a.out/'results.jsonl').read_text().splitlines()]} if (a.out/'results.jsonl').exists() else set()
if a.part=='budget':cases=[('auto',cap,n,repeat,a.paced) for repeat in range(a.repeats) for cap in a.caps for n in a.workers]
elif a.part=='smoke':cases=[('walk',12,1,0,False),('run',12,1,0,False),('bike',12,1,0,False)]
elif a.part=='movement':cases=[(mode,12,1,repeat,False) for repeat in range(a.repeats) for mode in ('walk','run','bike')]
elif a.part=='capped':cases=[(mode,cap,1,repeat,True) for repeat in range(a.repeats) for cap in (12,16) for mode in ('walk','run','bike')]
else:cases=[('auto',cap,n,repeat,False) for repeat in range(a.repeats) for cap in (12,16) for n in range(1,7)];random.Random(1729).shuffle(cases)
if a.part=='budget':random.Random(6331).shuffle(cases)
for mode,cap,n,repeat,pace in cases:
 if a.only_mode and mode!=a.only_mode:continue
 key=f'{a.part}-{mode}-{cap}-{n}-{repeat}'
 if key not in completed:trial(mode,cap,n,repeat,pace)
