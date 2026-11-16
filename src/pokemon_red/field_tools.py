"""Owned field-move capabilities. Availability is separate from automation support."""
TOOLS={'cut':dict(move=15,badge=2,automatic=True,name='Cut'),'surf':dict(move=57,badge=5,automatic=False,name='Surf'),'strength':dict(move=70,badge=4,automatic=False,name='Strength'),'fly':dict(move=19,badge=3,automatic=False,name='Fly'),'flash':dict(move=148,badge=1,automatic=False,name='Flash')}

def knows(mon,move):return any(a['id']==move for a in mon.get('moves',[])) and not mon.get('is_egg') and mon.get('checksum_valid',True)
def teleport_slot(mon):return next((i for i,a in enumerate(mon.get('moves',[])) if a['id']==100 and a.get('current_pp',a.get('max_pp',a.get('pp',0)))>0),None) if mon else None

def choose_runner(owned,trainee):
    candidates=[m for m in owned if m['uid']!=trainee and (knows(m,100) or m.get('ability_id')==50 or m.get('held_item')==194)]
    return min(candidates,key=lambda m:(0 if m['species_id']==64 and knows(m,100) else 1 if knows(m,100) else 2,-m.get('stats',{}).get('speed',0),m['uid']),default=None)

def available(owned,badges,game='firered'):
    from .field_rules import rules
    required=rules(game)['badges']
    return {k:dict(v,badge=required[k],unlocked=required[k] in badges,providers=[m['uid'] for m in owned if knows(m,v['move'])]) for k,v in TOOLS.items()}

def cut_grid(grid,enabled):
    if not enabled:return grid
    from .field_rules import tree
    cuts={(o['x'],o['y']) for o in grid.get('objects',[]) if tree(o,grid)}
    # Keep objects as hazards: only a precise single step may approach/cut a tree.
    return dict(grid,obstacles=[p for p in grid.get('obstacles',[]) if tuple(p) not in cuts],cut_enabled=True)

def party_cut(grid,party):return cut_grid(grid,grid.get('cut_badge',2) in grid.get('field_badges',[]) and any(knows(m,15) for m in party))


def utility_team(inventory,required,*,pinned=(),preferred=()):
    """Minimum extra utility providers for ONE leg, respecting six party slots.

    A single Pokémon can cover several moves. No learning, item use, mail
    removal or game flags are inferred. Unsupported executors fail explicitly.
    """
    required=sorted(set(required));owned=[m for m in inventory.get('party',[])+inventory.get('boxes',[]) if m.get('checksum_valid',True) and not m.get('is_egg')]
    by_uid={m['uid']:m for m in owned};current=[m['uid'] for m in inventory.get('party',[])]
    pinned=list(dict.fromkeys([u for u in pinned if u]+[m['uid'] for m in inventory.get('party',[]) if 121<=m.get('held_item',0)<=132]))
    if len(pinned)>6 or any(u not in by_uid for u in pinned):raise ValueError('Недоступен обязательный Pokémon или занято больше шести слотов')
    from .field_rules import rules
    field_badges=rules(inventory.get('game','firered'))['badges']
    for key in required:
        if key not in TOOLS or not TOOLS[key]['automatic']:raise ValueError('Полевое действие пока не автоматизировано: '+key)
        if field_badges[key] not in inventory.get('field_badges',[]):raise ValueError('Нет значка для '+TOOLS[key]['name'])
    def mask(uid):return sum(1<<i for i,k in enumerate(required) if knows(by_uid[uid],TOOLS[k]['move']))
    full=(1<<len(required))-1;initial=0
    for u in pinned:initial|=mask(u)
    # DP over a small capability bitmask, not combinations of every PC monster.
    def score(ids):return (len(ids),sum(u not in current for u in ids),sum(u not in preferred for u in ids),-sum(by_uid[u].get('level',0) for u in ids),tuple(ids))
    choices={initial:[]}
    for uid in sorted(by_uid):
        if uid in pinned or not mask(uid):continue
        for covered,ids in list(choices.items()):
            result=covered|mask(uid);candidate=[*ids,uid]
            if len(pinned)+len(candidate)>6:continue
            if result not in choices or score(candidate)<score(choices[result]):choices[result]=candidate
    if full not in choices:raise ValueError('Нет команды до шести Pokémon для полевых действий: '+', '.join(required))
    extra=choices[full];team=list(dict.fromkeys([*pinned,*extra]))
    for uid in [*preferred,*current]:
        if uid in by_uid and uid not in team and len(team)<6:team.append(uid)
    if not any(by_uid[u].get('hp',1)>0 for u in team):raise ValueError('В дорожном отряде нет боеспособного Pokémon')
    providers={k:next(u for u in team if knows(by_uid[u],TOOLS[k]['move'])) for k in required}
    return dict(team_uids=team,utility_uids=list(dict.fromkeys(providers.values())),providers=providers,required_tools=required)
