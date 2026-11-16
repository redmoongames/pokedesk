"""Pure reporting, invariants and performance comparisons. No emulator or UI."""
import hashlib
import json
import statistics
from pathlib import Path


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def terminal_snapshot(info, script):
    # Events can arrive before the owner's first running snapshot is published.
    return info.get('script')==script and info.get('status') in ('finished','attention','error','stopped') and not info.get('running')


def user_revocation(frames):
    return any(Path(f.filename).name=='gui.py' and f.name in ('take_control','emergency_stop','recover_input') for f in frames)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def signature(state):
    return dict(map=state['map'], position={k:state['position'][k] for k in ('x','y')}, money=state['money'],
        party=[dict(uid=m['uid'], species=m['species_id'], level=m['level'], xp=m['experience'],
                    hp=m['hp'], status=m['status_code'], moves=[(a['id'],a['current_pp']) for a in m['moves']])
               for m in state['party']])


def fixture_fingerprint(state):
    value=dict(signature(state),frame=state['frame'],in_battle=state['in_battle'],
               callback=state['controls']['callback'],decision=state.get('decision'))
    if state['in_battle']:
        battle=state.get('battle') or {}
        for side in ('allies','enemies'):
            value[side]=[{key:m.get(key) for key in ('species_id','level','hp','ability_id','party_slot','status_code','status2','status3')} for m in battle.get(side,[])]
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def summarize(values):
    median=statistics.median(values)
    mad=statistics.median(abs(x-median) for x in values)
    return dict(n=len(values), median=median, mad=mad, minimum=min(values), maximum=max(values),
                cv=statistics.stdev(values)/statistics.mean(values) if len(values)>1 else None)


def compare(current, baseline, *, relative=.15, absolute=.02):
    """Require a material increase beyond observed dispersion, not a lone spike."""
    if current['n']<3 or baseline['n']<3:
        return dict(status='insufficient_samples')
    if current['cv'] is None or current['cv']>.10 or baseline['cv'] is None or baseline['cv']>.10:
        return dict(status='unstable_measurement')
    allowance=max(baseline['median']*relative, absolute, 3*(baseline['mad']+current['mad']))
    delta=current['median']-baseline['median']
    return dict(status='regression' if delta>allowance else 'passed',
                delta=delta, allowance=allowance, ratio=current['median']/baseline['median'])


def tree_hash(root, names=('src','Bots','tools/regression','tests','main.py','show_stats.py','Run.command','Check.command','AGENTS.md','README.md')):
    h=hashlib.sha256()
    for name in names:
        base=Path(root)/name
        for file in ([base] if base.is_file() else sorted(base.rglob('*.py'))):
            h.update(str(file.relative_to(root)).encode());h.update(file.read_bytes())
    return h.hexdigest()


def atomic_json(path, data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    temp.replace(path)
