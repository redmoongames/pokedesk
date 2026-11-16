"""Transfer a computed preview to training, then validate it against fresh RAM.

The packet is a cache, never authority to skip live walking/field-move guards.
Legacy scripts without a packet retain ordinary planning at startup.
"""
from copy import deepcopy
from .run_context import RunConfig,digest,team_fingerprint,versions
from .planning_state import geometry_key

SCHEMA=1


def selection_key(inventory,config,root):
    owned=inventory.get('party',[])+inventory.get('boxes',[])
    version=versions(root)
    return digest([RunConfig.parse(config).as_dict(),team_fingerprint(owned),
        [(m['uid'],m.get('location'),m.get('box'),m.get('box_slot'),m.get('checksum_valid'),m.get('is_egg')) for m in owned],
        inventory.get('field_badges',[]),geometry_key(inventory['_planning']),
        {k:version[k] for k in ('rom','catalog','encounters','navigation','policy')}])


def prepare_packet(plan,inventory,config,root):
    if not plan.get('navigation') or '_planning' not in inventory:return None
    packet=dict(schema=SCHEMA,key=selection_key(inventory,config,root),plan=deepcopy(plan))
    packet['checksum']=digest(packet)
    return packet


def checked_plan(packet,inventory,config,root):
    if not isinstance(packet,dict):return None,'no_prepared_plan'
    if not inventory.get('ready'):return None,'inventory_unavailable'
    try:
        body={k:v for k,v in packet.items() if k!='checksum'}
        if packet.get('schema')!=SCHEMA or packet.get('checksum')!=digest(body):return None,'invalid_prepared_plan'
        if packet['key']!=selection_key(inventory,config,root):return None,'conditions_changed'
        plan=deepcopy(packet['plan']);cfg=RunConfig.parse(config)
        owned={m['uid']:m for m in inventory.get('party',[])+inventory.get('boxes',[]) if m.get('checksum_valid') and not m.get('is_egg')}
        uids=plan['team_uids'];roles=[plan['trainee'],*plan['fighters'],*plan.get('utility_uids',[])]
        if plan.get('runner'):roles.append(plan['runner'])
        if not 1<=len(uids)<=6 or len(set(uids))!=len(uids) or not set(roles)<=set(uids)<=set(owned):return None,'team_changed'
        if plan['trainee']!=cfg.trainee or plan['target']!=cfg.target:return None,'target_changed'
        if cfg.training_approach!='local' and cfg.route!='Auto' and cfg.route!=plan['route']:return None,'route_changed'
        from .zones import zone_spec
        spec=zone_spec(root);farm=plan['navigation']['farm']
        if farm['map']!=spec['zones'][plan['route']]['map'] or farm['hub'] not in spec['hubs']:return None,'invalid_navigation'
        plan['team']=[deepcopy(owned[u]) for u in uids]
        plan['team_fingerprint']=team_fingerprint(plan['team'])
        return plan,'validated'
    except (KeyError,TypeError,ValueError):return None,'invalid_prepared_plan'


def resolve_plan(inventory,config,root,*,cache=None):
    from .optimizer import make_training_plan,forecast_cycle,read_evidence,PRIORS
    plan,reason=checked_plan(config.get('_prepared_plan'),inventory,config,root)
    if plan is None:return make_training_plan(inventory,config,root,cache=cache),False,reason
    # XP, speed and new evidence can change the forecast without changing team
    # selection or a single path. Reforecast only the verified selected route.
    cfg=dict(RunConfig.parse(config).as_dict(),route=plan['route'],_speed=inventory['_planning'].get('speed',1))
    if cfg.get('training_approach','legacy')!='legacy':cfg['training_policy']=plan.get('effective_policy',cfg['training_policy'])
    geometry=plan['navigation'];forecast=forecast_cycle(plan,cfg,root,geometry,read_evidence(root))
    current={m['uid'] for m in inventory.get('party',[])};desired=set(plan['team_uids'])
    prep=0 if plan.get('keep_party') else geometry['preparation_seconds']+(len(current-desired)+len(desired-current))*PRIORS['pc_member']
    forecast.update(preparation_seconds=prep,eta_game_seconds=prep+forecast['remaining_game_seconds'],preparation_steps=geometry['preparation_steps'])
    plan['forecast']=forecast
    return plan,True,reason
