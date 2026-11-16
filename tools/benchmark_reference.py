"""Paired reference loading, journal contention and fixed-frame native workload.

Select an old/new prepared project with --project. Every mutable database/save
is private temporary data; no live profile is opened. Report timings, not FPS or
XP extrapolations. Native samples restore the same fixture before each run.
"""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import statistics
import sys
import tempfile
import threading
import time


def stats(values):
    values=sorted(values)
    return dict(n=len(values),median_ms=statistics.median(values),
                p95_ms=values[min(len(values)-1,int(len(values)*.95))],max_ms=max(values))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--fixture-project',type=Path,help='Private ROM/fixture installation for immutable code')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--repetitions',type=int,default=11)
    parser.add_argument('--native',action='store_true')
    args=parser.parse_args();project=args.project.resolve();fixtures=(args.fixture_project or project).resolve()
    if args.repetitions<1:parser.error('Repetitions must be positive')
    sys.path.insert(0,str(project/'src'))
    from pokemon_red.database import load_reference,connect
    from pokemon_red.catalog import catalog
    new=importlib.util.find_spec('pokemon_red.reference_pack') is not None
    if new:
        from pokemon_red.reference_pack import _read
    def cold(root):
        catalog.cache_clear()
        if new:_read.cache_clear()
        at=time.perf_counter();data=load_reference(root)
        return (time.perf_counter()-at)*1000,data
    fresh=[];existing=[];contended=[];raw=[];native=[]
    with tempfile.TemporaryDirectory(prefix='Pokemon reference benchmark ') as temporary:
        base=Path(temporary)
        for repeat in range(args.repetitions):
            root=base/str(repeat);root.mkdir();(root/'vendor').symlink_to(project/'vendor',target_is_directory=True)
            ms,data=cold(root);fresh.append(ms)
            journal_created=(root/'Data/history.sqlite3').exists()
            existing.append(cold(root)[0])
            db=connect(root)
            db.execute('CREATE TABLE IF NOT EXISTS reference_meta(key TEXT PRIMARY KEY,value TEXT)')
            db.execute("INSERT OR REPLACE INTO reference_meta VALUES('version','stale')");db.commit();db.close()
            # This reproduces the old implicit rebuild competing with a journal
            # writer; the new reader must remain independent of this database.
            import sqlite3
            lock=sqlite3.connect(root/'Data/history.sqlite3',check_same_thread=False)
            lock.execute('BEGIN IMMEDIATE');timer=threading.Timer(.25,lock.commit);timer.start()
            try:ms,_=cold(root);contended.append(ms)
            finally:timer.join();lock.close()
            raw.append(dict(repetition=repeat+1,fresh_ms=fresh[-1],existing_ms=existing[-1],
                            stale_journal_writer_ms=ms,journal_created_by_reference=journal_created))
        shared=base/'shared';shared.mkdir();(shared/'vendor').symlink_to(project/'vendor',target_is_directory=True)
        catalog(shared);at=time.perf_counter()
        for _ in range(10000):catalog(shared)
        cached_ms=(time.perf_counter()-at)*1000
        at=time.perf_counter();models=[]
        for number in range(30):
            root=base/f'profile-{number}';root.mkdir();(root/'vendor').symlink_to(project/'vendor',target_is_directory=True)
            models.append(catalog(root))
        profiles_ms=(time.perf_counter()-at)*1000
        if args.native:
            from pokemon_red.engine import Game
            from pokemon_red.telemetry import read_state
            root=base/'native';root.mkdir();(root/'Data').mkdir()
            for name in ('vendor','native','assets'):(root/name).symlink_to(project/name,target_is_directory=True)
            (root/'Data/FireRed.gba').symlink_to(fixtures/'Data/FireRed.gba')
            fixture=fixtures/'tests/fixtures/fire_red/clinic.state'
            with Game(root,resume=False) as game:
                for repeat in range(6):
                    game.load_state(fixture);read_state(game);start_frame=game.frame;at=time.perf_counter()
                    for _ in range(600):game.advance(1);read_state(game)
                    elapsed=(time.perf_counter()-at)*1000
                    if game.frame-start_frame!=600:raise RuntimeError('Frame count changed')
                    if repeat:native.append(elapsed)  # One fixed warmup.
    tree=hashlib.sha256()
    for path in sorted((project/'src/pokemon_red').glob('*.py')):
        tree.update(path.name.encode()+b'\0'+path.read_bytes()+b'\0')
    report=dict(schema=1,pack_reader=new,repetitions=args.repetitions,
                fresh=stats(fresh),existing=stats(existing),stale_journal_writer=stats(contended),
                cached_10000_calls_ms=cached_ms,profiles_30_ms=profiles_ms,
                unique_reference_objects=len({id(data) for data in models}),rows=raw,
                native_600_frames_with_telemetry=stats(native) if native else None,
                source_sha256=tree.hexdigest(),note='Private synthetic journals; 250ms writer hold. Native is an unpaced fixed-frame workload, not a full grind cycle.')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))


if __name__=='__main__':main()
