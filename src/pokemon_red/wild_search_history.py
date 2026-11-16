"""Persistent wild encounter alternatives, scoped to an immutable operation.

These are encounters, not owned Pokémon. Opening one changes the timeline;
MainOperation first publishes a named slot containing the current timeline.
"""
from pathlib import Path
from .acquisition import read_json
from .search_candidates import CandidateStore,valid_hash
from .capture_target import CaptureTarget
from .i18n import t

TERMINAL={'ready','paused','cancelled','attention','error'}

def operation_folder(root,identifier):
    if not isinstance(identifier,str) or len(identifier)!=32 or any(c not in '0123456789abcdef' for c in identifier):raise ValueError(t('capture.saved_invalid'))
    parent=(Path(root)/'Sessions/operations').resolve();folder=(parent/identifier).resolve()
    if folder.parent!=parent:raise ValueError(t('capture.saved_invalid'))
    return folder

def saved_search(root,identifier,*,verify=False):
    folder=operation_folder(root,identifier);spec=read_json(folder/'operation.json',{});status=read_json(folder/'status.json',{})
    if spec.get('kind')!='local' or spec.get('config',{}).get('schema_version')!=2 or spec['config'].get('_saved_candidate'):raise ValueError(t('capture.saved_invalid'))
    from .catch_lifecycle import expired,PAUSED_TTL
    lifecycle=read_json(folder/'lifecycle.json',{})
    if not lifecycle.get('paused_at') and not lifecycle.get('state'):
        lifecycle=dict(lifecycle,paused_at=status.get('updated_at') or (folder/'status.json').stat().st_mtime)
    if lifecycle.get('state')=='closed' or expired(lifecycle):raise ValueError(t('capture.search_finished'))
    if status.get('status')=='ready' and read_json(folder/'result.json',{}).get('pokemon'):raise ValueError(t('capture.search_finished'))
    from .editions import edition
    if edition(folder/'main').id!=edition(root).id:raise ValueError(t('capture.saved_wrong_game'))
    target=CaptureTarget.parse(spec['config'],root);store=CandidateStore(folder/'main','wild');rows=[]
    for row in store.rows():
        try:
            rated=target.assess(row['pokemon'],root);sha=row['sha256']
            if not rated or not valid_hash(sha):continue
            if verify:store.checkpoint(sha)
            elif not (store.folder/(sha+'.state')).is_file() and not store.best_state.is_file():continue
            rows.append(dict(rated,sha256=sha))
        except (OSError,KeyError,TypeError,ValueError):continue
    return dict(id=identifier,created_at=spec.get('created_at',0),config=spec['config'],status=status.get('status'),paused_at=lifecycle.get('paused_at'),expires_at=(lifecycle['paused_at']+PAUSED_TTL if lifecycle.get('paused_at') is not None else None),candidates=rows,attempts=(status.get('search') or {}).get('attempts',0),remaining=(status.get('search') or {}).get('remaining'),pokemon=read_json(folder/'result.json',{}).get('pokemon'))

def saved_searches(root,*,limit=None):
    parent=Path(root)/'Sessions/operations'
    folders=sorted((p for p in parent.iterdir() if p.is_dir()),key=lambda p:p.stat().st_mtime_ns,reverse=True) if parent.is_dir() else []
    result=[]
    for folder in folders:
        try:row=saved_search(root,folder.name)
        except (OSError,ValueError,KeyError,TypeError):continue
        if row['candidates'] or row['status'] in ('paused','attention'):result.append(row)
        if limit and len(result)>=limit:break
    return result

def candidate_request(root,reference):
    if not isinstance(reference,dict) or set(reference)!={'operation_id','sha256'}:raise ValueError(t('capture.saved_invalid'))
    row=saved_search(root,reference['operation_id'],verify=True)
    selected=next((r for r in row['candidates'] if r['sha256']==reference['sha256']),None)
    if selected is None:raise ValueError(t('capture.saved_missing'))
    return row,selected

def resume_snapshot(root,identifier):
    """Restore the prepared field, not a caught branch or the manual timeline.

    Older searches kept the same immutable frontier in their lane-zero clone.
    New searches publish an explicit frontier pair before spawning any lane.
    """
    from .persistence import SaveSnapshot
    import time
    row=saved_search(root,identifier,verify=True);main=operation_folder(root,identifier)/'main'
    folders=[main/'search-frontier']
    pools=main/'search-workers'
    if pools.is_dir():folders.extend(p/'0/Data' for p in sorted(pools.iterdir(),reverse=True) if p.is_dir())
    for folder in folders:
        if all((folder/name).is_file() for name in ('FireRed.state','FireRed.sav')):
            return row,SaveSnapshot((folder/'FireRed.state').read_bytes(),(folder/'FireRed.sav').read_bytes(),0,time.time())
    raise ValueError(t('capture.resume_missing'))

def expected_candidate(game,reference,source_root):
    from .models import read_inventory
    row,selected=candidate_request(source_root,reference);target=CaptureTarget.parse(row['config'],game.root)
    inv=read_inventory(game);mon=next((m for m in inv['party']+inv['boxes'] if m.get('uid')==selected['pokemon']['uid']),None)
    rated=target.assess(mon,game.root) if mon else None
    return mon if rated and rated['pokemon']==selected['pokemon'] else None

def catch_saved(player,reference,source_root):
    from .models import read_inventory
    from .autocatch import verified_enemy
    from .grass_search import settle_encounter
    from .hunt_planning import choose_hunter
    from .acquisition_play import AcquisitionAttention
    p=player;g=p.g;row,selected=candidate_request(source_root,reference);target=CaptureTarget.parse(row['config'],g.root)
    p.w.safe_point();g.restore_checkpoint(CandidateStore(operation_folder(source_root,row['id'])/'main','wild').checkpoint(selected['sha256']))
    reset=getattr(p.w,'reset_pacing',None)
    if reset:reset()
    p.w.safe_point();settle_encounter(p,selected['pokemon']['uid']);enemy=verified_enemy(p.state());rated=target.assess(enemy,g.root) if enemy else None
    if not rated or rated['pokemon']!=selected['pokemon']:raise AcquisitionAttention(t('capture.result_mismatch'))
    before=read_inventory(g);uids={m['uid'] for m in before['party']+before['boxes']}
    if enemy['uid'] in uids:raise AcquisitionAttention(t('capture.result_mismatch'))
    hunter=choose_hunter(before)
    if hunter:p.capture_policy='venusaur';p.capture_hunter=hunter['uid']
    p.w.update(stage=t('capture.saved_catching'),candidate_phase='catching',accepted_partial=bool(selected.get('missing')))
    p.w.event('saved_candidate_restored',dict(source_operation=row['id'],sha256=selected['sha256'],pokemon=selected['pokemon']))
    p.battle('catch');mon=expected_candidate(g,reference,source_root);after=read_inventory(g)
    if not mon or not uids<={m['uid'] for m in after['party']+after['boxes']}:raise AcquisitionAttention(t('capture.result_mismatch'))
    p.w.event('saved_candidate_caught',dict(source_operation=row['id'],pokemon=mon));return mon
