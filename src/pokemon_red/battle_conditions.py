"""Read-only Gen III restrictions; primary ailments do not themselves trap."""
def move_blockers(mon,attack):
    """Selection restrictions from a detached live BattleMon, never guessed PP."""
    number=attack.get('id',0);reasons=[]
    if not number:reasons.append('empty')
    if attack.get('current_pp',attack.get('pp',0))<=0:reasons.append('no_pp')
    if number and number==mon.get('disabled_move'):reasons.append('disable')
    if mon.get('status2',0)&(1<<31) and number==mon.get('last_move') and number!=165:reasons.append('torment')
    if mon.get('taunt_turns',0) and not attack.get('power',0):reasons.append('taunt')
    if mon.get('encore_turns',0) and number!=mon.get('encored_move'):reasons.append('encore')
    if mon.get('held_item')==186 and mon.get('choice_move',0) not in (0,0xffff,number):reasons.append('choice_band')
    if number in mon.get('imprisoned_moves',[]):reasons.append('imprison')
    reasons.extend(attack.get('unusable_reasons',[]))
    if attack.get('usable') is False and not reasons:reasons.append('unavailable')
    return sorted(set(reasons))

def switch_blockers(state):
    battle=state.get('battle') or {};allies=battle.get('allies',[])
    if not allies or allies[0].get('hp',0)<=0:return []
    own=allies[0];s2=own.get('status2',0);s3=own.get('status3',0);reasons=[]
    if s2&0xe000:reasons.append('binding')
    if s2&(1<<26):reasons.append('escape_prevention')
    if s3&(1<<10):reasons.append('ingrain')
    reasons.extend(passive_switch_blockers(own,battle.get('enemies',[])))
    return sorted(set(reasons))

def passive_switch_blockers(own,enemies):
    """Shared live/planning rules for trapping abilities, without volatile effects."""
    reasons=[]
    for foe in enemies:
        if foe.get('hp',0)<=0:continue
        aid=foe.get('ability_id')
        if aid==23:reasons.append('shadow_tag')
        if aid==71 and 2 not in own.get('types',[]) and own.get('ability_id')!=26:reasons.append('arena_trap')
        if aid==42 and 8 in own.get('types',[]):reasons.append('magnet_pull')
    return sorted(set(reasons))

def escape_blockers(state,current):
    # Run Away / Smoke Ball bypass the ordinary RUN restrictions, but never
    # grant permission to switch a bound Pokémon to a different party member.
    if current and (current.get('ability_id')==50 or current.get('held_item')==194):return []
    return switch_blockers(state)
