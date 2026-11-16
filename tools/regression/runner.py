"""One command: unit contracts, native fixed states and performance regression gate."""
from pathlib import Path
from datetime import datetime
from collections import defaultdict
import argparse
import json
import os
import platform
import random
import shutil
import signal
import subprocess
import sys
import tempfile
import time

from .model import atomic_json,compare,require,sha,summarize,tree_hash,fixture_fingerprint

MANDATORY={'walk','menu','rpc','battle','portals','complex-travel','heal','trap','faint','poison-faint','learning','learning-attention','takeover'}


def child(command, log, timeout):
    """Every child owns a process group; timeout/interrupt also retires its bots."""
    with Path(log).open('w') as stream:
        process=subprocess.Popen(command,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
        try:return process.wait(timeout=timeout)
        except (subprocess.TimeoutExpired,KeyboardInterrupt):
            try:os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            process.wait()
            raise


def validate_manifest(project, manifest):
    require(manifest['schema']==2,'Unsupported fixture manifest schema')
    require(sha(project/'Data/FireRed.gba')==manifest['rom_sha256'],'FireRed ROM does not match the fixtures')
    folder=project/'tests/fixtures/fire_red'
    for name,meta in manifest['fixtures'].items():
        file=(folder/meta['file']).resolve()
        require(file.is_relative_to(folder.resolve()),'Fixture path escapes bank')
        require(sha(file)==meta['sha256'],'Fixture hash mismatch: '+name)
        require(len(meta.get('initial_fingerprint',''))==64,'Fixture has no semantic fingerprint: '+name)
    ids=[c['id'] for c in manifest['cases']]
    require(len(ids)==len(set(ids)),'Duplicate case IDs')
    require(MANDATORY<=set(ids),'Required regression cases are missing')
    for case in manifest['cases']:require(case['fixture'] in manifest['fixtures'],'Unknown case fixture')
    for case in manifest['cases']:
        if case['id'] in MANDATORY:
            require(case['kind']==case['id'].replace('-','_'),'Required case points to a different scenario')
            expected={'learning-attention':'attention','takeover':'stopped'}.get(case['id'],'finished')
            require(case.get('expected_status','finished')==expected,'Required case has wrong expected outcome')
    metrics={c['id']:c.get('performance') for c in manifest['cases']}
    for name in ('walk','menu','rpc','battle','portals','complex-travel','heal','learning'):
        require(metrics.get(name)==('move_accept_seconds' if name=='battle' else 'seconds'),'Required performance metric missing: '+name)


def environment(project, manifest):
    definitions=project/'tools/regression'
    suite=__import__('hashlib').sha256()
    suite.update(json.dumps(manifest,sort_keys=True).encode())
    for name in ('worker.py','scenarios.py','model.py'):suite.update((definitions/name).read_bytes())
    return dict(machine=platform.machine(),cpu=subprocess.check_output(['/usr/sbin/sysctl','-n','machdep.cpu.brand_string'],text=True).strip(),
                macos=platform.mac_ver()[0],python=platform.python_version(),rom=manifest['rom_sha256'],core=sha(project/'native/libpokemon.dylib'),suite=suite.hexdigest())


def preflight(project, manifest):
    """A new core is allowed only after real state load/save semantic checks."""
    sys.path.insert(0,str(project/'src'))
    from pokemon_red.engine import Game
    from pokemon_red.telemetry import read_state
    checked=[]
    for name,meta in manifest['fixtures'].items():
        with Game(project,resume=False) as game:
            game.load_state(project/'tests/fixtures/fire_red'/meta['file'])
            game.advance(manifest.get('startup_frames',1))  # SessionController's normal zero-input startup.
            require(fixture_fingerprint(read_state(game))==meta['initial_fingerprint'],'Fixture semantics changed: '+name)
            path=project/'Data/preflight.state';path.write_bytes(game.capture_save(metadata=False).state)
            game.load_state(path)
            require(fixture_fingerprint(read_state(game))==meta['initial_fingerprint'],'Fixture round-trip failed: '+name)
            checked.append(name)
    return dict(status='passed',fixtures=checked,core=sha(project/'native/libpokemon.dylib'),prepared_core=manifest['core_sha256'])


def freeze(project, root):
    for name in ('src','tests','Bots','tools','native','vendor','assets','templates'):
        shutil.copytree(project/name,root/name,ignore=shutil.ignore_patterns('__pycache__'))
    (root/'runtime').symlink_to(project/'runtime')
    if (project/'ROMs').exists():(root/'ROMs').symlink_to(project/'ROMs')
    (root/'Data').mkdir();(root/'Data/FireRed.gba').symlink_to(project/'Data/FireRed.gba')
    for name in ('main.py','show_stats.py','Run.command','Check.command','AGENTS.md','README.md','ITEM_DELIVERY.md'):
        if (project/name).exists():shutil.copy2(project/name,root/name)
    if (project/'Pokemon.app').exists():shutil.copytree(project/'Pokemon.app',root/'Pokemon.app',symlinks=True)


def retain_failed_case(result_path, destination):
    if not result_path.exists():return
    prior=json.loads(result_path.read_text());private=Path(prior.get('private_root','/missing'))
    if private.name.startswith('Pokemon check ') and (private/'Data').exists():
        shutil.copytree(private/'Data',destination,symlinks=True);shutil.rmtree(private)


def gate(summary, baseline):
    # Core/app code are the subjects of performance comparison, not hardware identity.
    comparable=lambda e:{k:v for k,v in e.items() if k!='core'}
    if comparable(baseline.get('environment',{}))!=comparable(summary['environment']):return dict(status='incompatible_baseline',groups={})
    expected=set(summary['performance'])
    if set(baseline.get('performance',{}))!=expected:return dict(status='incomplete_baseline',groups={})
    comparisons={k:compare(value,baseline['performance'][k]) for k,value in summary['performance'].items()}
    status='passed' if all(v['status']=='passed' for v in comparisons.values()) else 'failed' if any(v['status']=='regression' for v in comparisons.values()) else 'needs_review'
    return dict(status=status,groups=comparisons)


def performance_rows(rows, by_id):
    groups=defaultdict(list)
    for row in rows:
        metric=by_id[row['case']].get('performance')
        if row['status']=='passed' and metric:groups[f"{row['case']}@{row['speed']:g}"].append(row[metric])
        if row['status']=='passed' and row['case']=='battle':groups[f"battle-total@{row['speed']:g}"].append(row['seconds'])
    return {key:summarize(values) for key,values in sorted(groups.items())}


def extra_samples(rows, by_id, initial, maximum=9):
    """One fixed quality extension, never discard failures or stop on significance."""
    if initial<3 or initial>=maximum or any(r['status']!='passed' for r in rows):return []
    unstable=set()
    for name,stats in performance_rows(rows,by_id).items():
        if stats['cv'] is not None and stats['cv']>.10:
            case,speed=name.split('@');unstable.add(('battle' if case=='battle-total' else case,float(speed)))
    return [(by_id[case],speed,repeat) for case,speed in sorted(unstable) for repeat in range(initial,maximum)]


def finish(summary, output):
    atomic_json(output/'summary.json',summary)
    text=[f"Status: {summary['status']}",f"Scope: {summary['scope']}",f"Unit tests: {summary.get('unit_status','not_run')}",
          f"Native cases: {len(summary['cases'])}; failed: {sum(r['status']!='passed' for r in summary['cases'])}",
          f"Performance: {summary.get('performance_gate',{}).get('status','not_checked')}",f"Error: {summary.get('error','')}",'']
    for case in summary['cases']:text.append(f"{case['status']:8} {case['name']} {case.get('seconds','')} {case.get('errors','')}")
    text+=['','Performance medians (real seconds):']
    for name,stats in summary['performance'].items():
        cv='not estimated' if stats['cv'] is None else f"{stats['cv']:.3f}"
        text.append(f"{name}: {stats['median']:.6f}, CV={cv}, n={stats['n']}")
    (output/'report.txt').write_text('\n'.join(text)+'\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    project_default=Path(__file__).resolve().parents[2]
    parser.add_argument('--project',type=Path,default=project_default)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--repetitions',type=int,default=3)
    parser.add_argument('--speeds',type=float,nargs='+',default=[8,12,16])
    parser.add_argument('--cases',nargs='+',help='Selected native cases; produces a partial report')
    parser.add_argument('--skip-unit',action='store_true',help='Native-only diagnostic profile')
    parser.add_argument('--quick',action='store_true',help='One repetition, correctness only')
    parser.add_argument('--visible',action='store_true',help='Show test windows (manual input interrupts the suite)')
    parser.add_argument('--baseline',type=Path)
    parser.add_argument('--record-baseline',type=Path,help='Explicitly create a NEW reviewed performance baseline')
    args=parser.parse_args();project=args.project.resolve()
    output=(args.output or project/'docs/checks'/datetime.now().strftime('%Y%m%d-%H%M%S-%f')).resolve()
    require(not output.exists(),'Choose a fresh output directory')
    require(not output.is_relative_to(project/'Data'),'Reports cannot be written into live Data')
    require(args.repetitions>=1 and all(s>0 for s in args.speeds),'Invalid repetitions/speed')
    output.mkdir(parents=True)
    scope='partial' if args.skip_unit or args.cases or args.quick or set(args.speeds)!={8,12,16} else 'full'
    summary=dict(schema=1,status='running',scope=scope,cases=[],performance={},started_at=datetime.now().isoformat(),project=str(project))
    finish(summary,output)
    try:
        manifest=json.loads((project/'tests/fixtures/fire_red/manifest.json').read_text());validate_manifest(project,manifest)
        summary['environment']=dict(environment(project,manifest),ui_mode='visible' if args.visible else 'hidden');summary['source']=tree_hash(project)
        cases=manifest['cases']
        if args.cases:
            require(set(args.cases)<={c['id'] for c in cases},'Unknown requested case')
            cases=[c for c in cases if c['id'] in args.cases]
        if args.record_baseline:
            require(scope=='full' and args.repetitions>=3,'Only a complete full run can create a baseline')
            require(not args.record_baseline.exists(),'Baseline already exists; create a new file for explicit review')
            require(not args.record_baseline.resolve().is_relative_to((project/'Data').resolve()),'Baseline cannot be written into live Data')
        with tempfile.TemporaryDirectory(prefix='Pokemon check source ') as folder:
            frozen=Path(folder);freeze(project,frozen)
            require(tree_hash(frozen)==summary['source'],'Source changed while making snapshot; retry')
            validate_manifest(frozen,manifest)
            summary['fixture_preflight']=preflight(frozen,manifest)
            if not args.skip_unit:
                print('UNIT full test discovery',flush=True)
                code=child([sys.executable,'-I','-B','-m','unittest','discover','-s',str(frozen/'tests')],output/'unit.log',240)
                summary['unit_status']='passed' if code==0 else 'failed'
                require(code==0,'Unit tests failed; see unit.log. Native performance was not measured.')
            tasks=[]
            for spec in cases:
                count=1 if args.quick or not spec.get('performance') else args.repetitions
                for speed in args.speeds:
                    for repeat in range(count):tasks.append((spec,speed,repeat))
            random.Random(20261115).shuffle(tasks)
            initial_count=len(tasks);by_id={c['id']:c for c in cases}
            for index,(spec,speed,repeat) in enumerate(tasks):
                name=f"{spec['id']}-{speed:g}x-r{repeat+1}";print(f"NATIVE {index+1}/{len(tasks)} {name}",flush=True)
                spec_path=output/(name+'.spec.json');atomic_json(spec_path,spec)
                result_path=output/(name+'.json')
                fixture=frozen/'tests/fixtures/fire_red'/manifest['fixtures'][spec['fixture']]['file']
                command=[sys.executable,'-I','-B',str(frozen/'tools/regression/worker.py'),'--project',str(frozen),
                    '--spec',str(spec_path),'--fixture',str(fixture),'--speed',str(speed),'--output',str(result_path)]
                if args.visible:command.append('--visible')
                try:
                    code=child(command,output/(name+'.log'),spec.get('timeout',60)+30)
                    result=json.loads(result_path.read_text()) if result_path.exists() else dict(status='error',errors=['worker produced no result'])
                    if code and result.get('status')=='passed':result.update(status='error',errors=['worker exited unsuccessfully'])
                except subprocess.TimeoutExpired:
                    retain_failed_case(result_path,output/(name+'.Data'))
                    result=dict(status='error',errors=['worker timeout; process group terminated'])
                    atomic_json(result_path,result)
                except KeyboardInterrupt:
                    retain_failed_case(result_path,output/(name+'.Data'))
                    atomic_json(result_path,dict(status='interrupted',errors=['runner interrupted; process group terminated']))
                    raise
                row=dict(name=name,case=spec['id'],speed=speed,status=result['status'],errors=result.get('errors',[result.get('error')] if result.get('error') else []))
                for key in ('seconds','move_accept_seconds','takeover_ack_ms','save_roundtrip'): 
                    if key in result:row[key]=result[key]
                summary['cases'].append(row);finish(summary,output)
                if row['status']=='interrupted':raise KeyboardInterrupt()
                if index+1==initial_count and scope=='full':
                    extension=extra_samples(summary['cases'],by_id,args.repetitions)
                    if extension:
                        tasks.extend(extension)
                        summary['sampling_extension']=dict(reason='CV above 10%; every initial observation retained',maximum_repetitions=9,
                            groups=sorted({f"{s['id']}@{speed:g}" for s,speed,_ in extension}))
                        print(f"QUALITY extending {len(extension)} samples to a fixed total of 9 per noisy group",flush=True)
            require(dict(environment(frozen,manifest),ui_mode='visible' if args.visible else 'hidden')==summary['environment'],'Shared runtime/ROM changed during run')
        summary['performance']=performance_rows(summary['cases'],by_id)
        correct=all(c['status']=='passed' for c in summary['cases']) and summary.get('unit_status','passed')=='passed'
        if not correct:summary['status']='failed';summary['performance_gate']=dict(status='not_evaluated_due_to_correctness_failure')
        elif scope!='full':summary['status']='passed_partial';summary['performance_gate']=dict(status='not_checked_partial_profile')
        elif args.record_baseline:
            stable=all(s['n']>=3 and s['cv']<=.10 for s in summary['performance'].values())
            if stable:
                atomic_json(args.record_baseline,dict(schema=1,environment=summary['environment'],performance=summary['performance'],source=summary['source'],report=str(output)))
                summary['status']='passed';summary['performance_gate']=dict(status='baseline_created',path=str(args.record_baseline))
            else:summary['status']='needs_review';summary['performance_gate']=dict(status='unstable_measurement')
        else:
            baseline=args.baseline or project/'tests/fixtures/fire_red/baseline.json'
            if baseline.exists():summary['performance_gate']=gate(summary,json.loads(baseline.read_text()))
            else:summary['performance_gate']=dict(status='missing_baseline')
            value=summary['performance_gate']['status'];summary['status']='passed' if value=='passed' else 'failed' if value=='failed' else 'needs_review'
    except KeyboardInterrupt:summary['status']='interrupted'
    except Exception as error:summary.update(status='failed',error=str(error))
    summary['finished_at']=datetime.now().isoformat();finish(summary,output)
    print(f"{summary['status']}: {output/'report.txt'}",flush=True)
    raise SystemExit(0 if summary['status'] in ('passed','passed_partial') else 2 if summary['status']=='needs_review' else 130 if summary['status']=='interrupted' else 1)


if __name__=='__main__':main()
