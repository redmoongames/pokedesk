"""One low-priority, disjoint lane of ordinary starter timing attempts."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import json,os,signal,time,resource,hashlib
from pokemon_red.starter_candidates import assess
from pokemon_red.starter_checkpoint import valid_frontier
from pokemon_red.i18n import t
from pokemon_red.engine import Game
from pokemon_red.telemetry import symbols,read_party_mon
from pokemon_red.new_game_config import NewGameConfig
from pokemon_red.acquisition import write_json
from pokemon_red.persistence import atomic_bytes

def run(root):
    root=Path(root);job=json.loads((root/'request.json').read_text());cfg=NewGameConfig.parse(job['config'])
    stopped=False
    def stop(*_):
        nonlocal stopped
        stopped=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    try:os.nice(10)
    except OSError:pass
    began=time.monotonic();cpu=time.process_time();attempts=0;next_index=17+job['lane'];stride=17;frontier=None
    stats=dict(status='running',lane=job['lane'],attempts=0,next_index=next_index,pid=os.getpid(),matches=0,first_match_seconds=None,checks={},sample=[])
    benchmark=job.get('benchmark_seconds');last_report=0;last_uid=None;repeated=0
    def parent_alive():
        if job.get('owner_pid') and os.getppid()!=job['owner_pid']:return False
        if job.get('supervisor_pid'):
            try:os.kill(job['supervisor_pid'],0)
            except ProcessLookupError:return False
        return True
    def publish():
        stats.update(attempts=attempts,next_index=next_index,seconds=time.monotonic()-began,cpu_seconds=time.process_time()-cpu,rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        write_json(root/'progress.json',stats)
    try:
        with Game(root) as game:
            sy=symbols(root)
            if not valid_frontier(game):raise RuntimeError(t('search.invalid_frontier'))
            game.advance(next_index);frontier=game.capture_save(metadata=False).state
            while not stopped and parent_alive() and not (root.parent/'stop').exists() and not (benchmark and time.monotonic()-began>=benchmark):
                if game.read8(sy['gPlayerPartyCount']):raise RuntimeError(t('search.invalid_frontier'))
                game.press('A',frames=1,release_frames=3);mon=None
                for frame in range(180):
                    if stopped or (root.parent/'stop').exists():break
                    if game.read8(sy['gPlayerPartyCount']):
                        mon=read_party_mon(game,sy['gPlayerParty'],0)
                        if mon.get('checksum_valid') and mon['species_id']==cfg.species_id:break
                    if frame%12==11:game.press('A',frames=2,release_frames=1)
                    else:game.advance(1)
                if stopped or (root.parent/'stop').exists():break
                if not mon or not mon.get('checksum_valid') or mon['species_id']!=cfg.species_id:raise RuntimeError(t('search.generation_failed'))
                repeated=repeated+1 if mon['uid']==last_uid else 0;last_uid=mon['uid']
                if repeated>=3:raise RuntimeError(t('search.repeated_candidate'))
                attempts+=1
                if len(stats['sample'])<64:stats['sample'].append(mon['uid'])
                candidate=assess(cfg,mon)
                if candidate and ('best' not in stats or candidate['rank']>stats['best']['rank']):
                    data=game.capture_save(metadata=False).state;atomic_bytes(root/'best.state',data);stats['best']=dict(candidate,sha256=hashlib.sha256(data).hexdigest())
                matched=cfg.matches(mon)
                if benchmark:
                    from dataclasses import replace
                    for name,choices in (('any_nature',()),('modest',(15,)),('special_support',(5,10,15,20))):
                        if replace(cfg,nature=None,natures=choices).matches(mon):
                            record=stats['checks'].setdefault(name,dict(matches=0,first_seconds=time.monotonic()-began));record['matches']+=1
                if matched:
                    stats['matches']+=1
                    if stats['first_match_seconds'] is None:stats['first_match_seconds']=time.monotonic()-began
                    if not benchmark:
                        atomic_bytes(root/'found.state',game.capture_save(metadata=False).state)
                        stats.update(status='found',uid=mon['uid'],found_index=next_index);publish();break
                game.restore_checkpoint(frontier);next_index+=stride;game.advance(stride);frontier=game.capture_save(metadata=False).state
                if time.monotonic()-last_report>.25:publish();last_report=time.monotonic()
            if stats['status']!='found':stats['status']='stopped'
            if frontier is not None:atomic_bytes(root/'frontier.state',frontier)
            publish()
    except Exception as error:
        stats.update(status='error',error=str(error))
        if frontier is not None:atomic_bytes(root/'frontier.state',frontier)
        publish();return 1
    return 0

if __name__=='__main__':
    from pokemon_red.installation_versions import validate_worker
    validate_worker(Path(sys.argv[1]))
    raise SystemExit(run(sys.argv[1]))
