"""Center-to-Center itineraries and ordinary PC preparation for supported tools.

NPC fights and story battles remain explicit handoffs. Planning does not use a
boxed provider until a Center has actually been reached with the current party.
"""
from .training import TrainingProblem
from .field_tools import utility_team


def itinerary(nav,destination,goal=None,*,pinned=(),preferred=()):
    state=nav.t.state();start_map=state['map']['name'];p=state['position'];start=(p['x'],p['y'])
    inventory=nav.tool_inventory
    if inventory is None:raise ValueError('Для дорожного плана нужен текущий инвентарь')
    hubs=nav.spec['hubs'];at_center=any(h['map']==start_map for h in hubs.values());legs=[]
    name,point=start_map,start
    if not at_center:
        key,first=nav.nearest_clinic((destination,goal),before_preparation=True);hub=hubs[key]
        legs.append(dict(source=name,start=list(point),destination=hub['map'],goal=hub['nurse'],clinic=key,prepare=False,required_tools=sorted({a['tool'] for a in first['field_actions']}),plan=first))
        name,point=hub['map'],tuple(hub['nurse'])
    direct=nav.plan(name,point,destination,goal)
    maps=[name,*[e['destination'] for e in direct['links']]]
    # Visit Centers attached to cities on the proved route, in travel order.
    # Every detour is itself cell-verified, including the onward leg.
    stops=[];seen={name,destination}
    for location in maps:
        for key,hub in sorted(hubs.items()):
            if hub['map'] in seen:continue
            if hub['map']==location or any(e['source']==location and e['destination']==hub['map'] for e in nav.spec['links']):
                try:
                    nav.plan(name,point,hub['map'],hub['nurse'],diagnose=False)
                    nav.plan(hub['map'],hub['nurse'],destination,goal,diagnose=False)
                except TrainingProblem:continue
                stops.append((key,hub['map'],hub['nurse']));seen.add(hub['map'])
    for key,target,position in [*stops,(None,destination,goal)]:
        if name==target and (position is None or tuple(position)==tuple(point)):continue
        plan=nav.plan(name,point,target,position);required=sorted({a['tool'] for a in plan['field_actions']})
        roster=utility_team(inventory,required,pinned=pinned,preferred=preferred)
        legs.append(dict(source=name,start=list(point),destination=target,goal=position,clinic=key,prepare=True,required_tools=required,roster=roster,plan=plan))
        name,point=target,tuple(position) if position is not None else tuple(plan['arrival'])
    return dict(destination=destination,goal=goal,legs=legs,policy='center-legs-v1')


def travel_prepared(nav,destination,goal=None,*,pinned=(),preferred=()):
    from .storage import Storage
    from .telemetry import read_field_badges
    # Plans are reviewable/logged before changing the party. At each Center,
    # refresh ownership, badges, NPCs and story flags before the next leg.
    trip=itinerary(nav,destination,goal,pinned=pinned,preferred=preferred)
    nav.bot.event('travel_itinerary','Дорожный план по Pokémon Center',destination=destination,legs=[{k:v for k,v in leg.items() if k!='plan'} for leg in trip['legs']])
    for leg in trip['legs']:
        state=nav.t.state()
        if state['map']['name']!=leg['source']:raise TrainingProblem('itinerary_changed','Изменилась карта дорожного этапа')
        if leg['prepare']:
            inventory=nav.bot.inventory()
            # DirectBot inventory omits badges; use the emulator only when owned.
            if 'field_badges' not in inventory:
                inventory['field_badges']=read_field_badges(nav.t.g) if hasattr(nav.t,'g') else nav.tool_inventory.get('field_badges',[])
            nav.configure_tools(inventory,'owned');nav.reset()
            current=nav.current_plan(leg['destination'],leg['goal']);required={a['tool'] for a in current['field_actions']}
            roster=utility_team(inventory,required,pinned=pinned,preferred=preferred)
            Storage(nav.t).assemble(roster['team_uids'])
            # Confirm the actual party; owned/PC capability is never enough.
            fresh=nav.bot.inventory();fresh['field_badges']=inventory['field_badges'];nav.configure_tools(fresh,'party')
            nav.bot.event('travel_team_ready','Отряд для следующего этапа собран',**roster)
            if hasattr(nav.t,'heal_here'):nav.t.heal_here()
            elif hasattr(nav.t,'g') and hasattr(nav.t,'heal'):nav.t.heal()
            if hasattr(nav.t,'travel_lead'):nav.t.travel_lead()
        else:nav.configure_tools(nav.tool_inventory,'party')
        nav.travel(leg['destination'],leg['goal'])
    return trip
