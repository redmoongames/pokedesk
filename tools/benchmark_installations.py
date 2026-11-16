"""Measure installation publication and warm job preparation, without gameplay.

Only disposable workspaces are written. Cold snapshot construction, full reuse
verification and cheap warm lookups are separate metrics. Pair with native and
takeover benchmarks; these measurements do not predict XP throughput.
"""
from pathlib import Path
import argparse
import json
import statistics
import subprocess
import sys
import tempfile
import time


def stats(values):
    values=sorted(values)
    return dict(n=len(values),median_ms=statistics.median(values),
                p95_ms=values[min(len(values)-1,int(len(values)*.95))],max_ms=max(values))


WARM = '''
from pathlib import Path
import json,sys,time
sys.path.insert(0,str(Path(sys.argv[1])/'src'))
from pokemon_red.installation_versions import prepare_bot,version_for_job,loaded_id
from pokemon_red.paths import bind_installation
root=Path(sys.argv[2]);root.mkdir()
bind_installation(root,Path(sys.argv[1]),library=root)
script=root/'custom.py';script.write_text('def run(bot): pass\\n')
(root/'helper.py').write_text('VALUE=1\\n')
at=time.perf_counter()
for _ in range(10000):version_for_job(root)
lookup=(time.perf_counter()-at)*1000
samples=[]
for _ in range(21):
    at=time.perf_counter();prepared=prepare_bot(root,script)
    samples.append((time.perf_counter()-at)*1000)
    assert prepared.execution['release_id']==loaded_id()
print(json.dumps(dict(lookup_10000_ms=lookup,prepare_bot_ms=samples,release_id=loaded_id())))
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--repetitions',type=int,default=7)
    args=parser.parse_args();project=args.project.resolve()
    if args.repetitions<1:parser.error('Repetitions must be positive')
    sys.path.insert(0,str(project/'src'))
    from pokemon_red.installation_versions import prepare_installation
    with tempfile.TemporaryDirectory(prefix='Pokemon installation benchmark ') as temporary:
        base=Path(temporary);at=time.perf_counter()
        version=prepare_installation(project,base/'versions')
        cold=(time.perf_counter()-at)*1000
        manifest=json.loads((version.root/'installation-version.json').read_text())
        reused=[];startup={}
        for _ in range(args.repetitions):
            at=time.perf_counter();again=prepare_installation(project,base/'versions')
            reused.append((time.perf_counter()-at)*1000)
            assert again.id==version.id
        for label,root,python in (('source',project,sys.executable),('pinned',version.root,version.python)):
            samples=[]
            code="import sys;sys.path.insert(0,sys.argv[1]);import pokemon_red.engine_runtime,pokemon_red.automation"
            for _ in range(args.repetitions):
                at=time.perf_counter()
                subprocess.run([str(python),'-I','-B','-c',code,str(root/'src')],check=True,capture_output=True)
                samples.append((time.perf_counter()-at)*1000)
            startup[label]=stats(samples)
        process=subprocess.run([str(version.python),'-I','-B','-c',WARM,str(version.root),str(base/'profile')],check=True,capture_output=True,text=True)
        warm=json.loads(process.stdout)
        report=dict(schema=1,release_id=version.id,cold_publish_ms=cold,
                    verified_reuse=stats(reused),warm_lookup_10000_ms=warm['lookup_10000_ms'],
                    warm_prepare_bot=stats(warm['prepare_bot_ms']),worker_import=startup,
                    files=len(manifest['files']),logical_bytes=sum(row.get('size',0) for row in manifest['files']),
                    note='Private installation and two-module custom script. Includes durable job publication; no game, XP or physical APFS allocation measurement.')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))


if __name__=='__main__':main()
