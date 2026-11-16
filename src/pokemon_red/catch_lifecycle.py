"""Bounded paused-search context. Pure movement policy and writer-only receipts.

Closing a search retires its alternatives, never the player's save or backups.
Checkpoints stay on disk for diagnostics; they are no longer selectable.
"""
import time
from .acquisition import read_json,write_json

MANUAL_STEP_LIMIT=100
PAUSED_TTL=24*60*60

def context_path(root):return root/'Sessions/acquisition/wild-context.json'

def expired(context,now=None):
    return (context.get('manual_steps',0)>=MANUAL_STEP_LIMIT or
            context.get('paused_at') is not None and (time.time() if now is None else now)-context['paused_at']>=PAUSED_TTL)

def observe(context,state,previous,*,generation,now=None):
    """Count observed manual tile travel, never elapsed frames or battle input.

    A generation reset establishes a new origin; it is not a teleport distance.
    Manhattan distance also counts tiles crossed between ordinary UI snapshots.
    Loops entirely between snapshots can be undercounted: expiry is conservative.
    """
    if not context or context.get('state')!='paused':return previous,False
    position=state.get('position',{});name=state.get('map',{}).get('name')
    if state.get('in_battle') or 'x' not in position or not name:return None,expired(context,now)
    point=(generation,name,position['x'],position['y'])
    if previous and previous[0]==generation:
        distance=abs(point[2]-previous[2])+abs(point[3]-previous[3]) if point[1]==previous[1] else 1
        context['manual_steps']=context.get('manual_steps',0)+distance
    return point,expired(context,now)

def close_receipt(root,identifier,reason):
    # Called by FileWriter, or by an isolated worker/test; never by Tk.
    from .wild_search_history import operation_folder
    folder=operation_folder(root,identifier)
    if read_json(folder/'lifecycle.json',{}).get('state')=='closed':return
    now=time.time();write_json(folder/'lifecycle.json',dict(state='closed',reason=reason,closed_at=now))
    import json
    with (folder/'events.jsonl').open('a') as file:file.write(json.dumps(dict(time=now,code='wild_search_closed',details=dict(reason=reason,operation_id=identifier)))+'\n')

def persist_context(root,context):
    if context and context.get('state')=='paused':
        from .wild_search_history import operation_folder
        write_json(operation_folder(root,context['id'])/'lifecycle.json',dict(state='paused',paused_at=context['paused_at'],manual_steps=context.get('manual_steps',0)))
    write_json(context_path(root),context)
