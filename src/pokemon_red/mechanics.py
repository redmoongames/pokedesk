"""Gen III damage estimates; observed XP and outcomes always come from RAM.

Planning assumes neutral nature/15 IV wilds and no weather/items. Live estimates
use current stats and stages. Unsupported conditional attacks are not auto-picked.
"""
import math
from .catalog import species,effectiveness,move
from .models import calculate_stats
from .rules import stage_multiplier,ABILITY_RULES
from .battle_conditions import move_blockers

def wild_mon(species_id,level,root):
    info=species(species_id,root);stats=calculate_stats(info,level)
    known=[]
    for entry in info['learnset']:
        if entry['level']<=level and entry['move'] not in known:known.append(entry['move'])
    moves=[dict(move(n,root),current_pp=move(n,root)['pp']) for n in known[-4:]]
    return dict(species_id=species_id,species=info['name'],level=level,hp=stats['hp'],max_hp=stats['hp'],stats=stats,types=info['type_ids'],ability_id=info['abilities'][0],status_code=0,moves=moves)

def incoming_risk(mon,enemy,root):
    attacks=ranked_attacks(enemy,mon,root)
    maximum=max((row['max'] for _,row in attacks),default=0)
    slower=enemy.get('stats',{}).get('speed',0)>=mon.get('stats',{}).get('speed',0)
    return maximum*(2 if slower else 1)/max(1,mon.get('hp',mon.get('max_hp',1)))

def attacks(mon,root):
    return [(i,dict(move(a['id'],root),**a)) for i,a in enumerate(mon.get('moves',[])) if a.get('power',0)>0 and not move_blockers(mon,a)]

def estimate(attacker,defender,attack,root):
    """Return conservative noncritical rolls + accuracy and expected actions.

    Explicitly approximate multi-hit, recoil, two-turn and variable attacks. Not a
    full battle simulator; never use conditional/recharge/self-KO attacks for grind.
    """
    aid=attacker.get('ability_id',0);did=defender.get('ability_id',0);typ=attack['type_id']
    types=defender.get('types',species(defender['species_id'],root).get('type_ids',[]))
    own=attacker.get('types',species(attacker['species_id'],root).get('type_ids',[]))
    matchup=effectiveness(typ,types,root);effect=attack.get('effect_name','');power=attack['power'];name=attack['name']
    defender_rule=ABILITY_RULES.get(did,{})
    if typ==defender_rule.get('immune_type') or (defender_rule.get('only_super_effective') and matchup<=1):matchup=0
    unsafe=attack.get('conditional_damage') or effect in ('EXPLOSION','SELFDESTRUCT','RECHARGE','OHKO','ROLLOUT','FURY_CUTTER','SOLAR_BEAM','SKULL_BASH','RAZOR_WIND','SKY_ATTACK','FLY','SEMI_INVULNERABLE')
    if not power or not matchup or unsafe:return dict(min=0,max=0,mean=0,accuracy=0,turns=math.inf,ohko=0,move_id=attack['id'],move=name,effectiveness=matchup)
    physical=typ<=8;atk='attack' if physical else 'special_attack';defense='defense' if physical else 'special_defense'
    av=attacker.get('stats',{}).get(atk,10);dv=defender.get('stats',{}).get(defense,10)
    av=max(1,int(av*stage_multiplier(attacker.get('stages',{}).get(atk,0))))
    dv=max(1,int(dv*stage_multiplier(defender.get('stages',{}).get(defense,0))))
    if physical:av=int(av*ABILITY_RULES.get(aid,{}).get('attack_multiplier',1))
    if physical and aid==62 and attacker.get('status_code',0):av=av*3//2
    if physical and did==63 and defender.get('status_code',0):dv=dv*3//2
    if did==47 and typ in (10,15):av//=2
    if attacker.get('hp',1)<=attacker.get('max_hp',1)//3 and (aid,typ) in ((65,12),(66,10),(67,11),(68,6)):power=power*3//2
    if effect=='RETURN':power=max(1,attacker.get('friendship',70)*10//25)
    elif effect=='FRUSTRATION':power=max(1,(255-attacker.get('friendship',70))*10//25)
    elif effect in ('LOW_KICK','FLAIL','REVERSAL','HIDDEN_POWER','ERUPTION','MAGNITUDE','WEATHER_BALL','FACADE','SMELLINGSALT','REVENGE'):
        # Avoid optimistic estimates for context-dependent power not modelled here.
        return dict(min=0,max=0,mean=0,accuracy=0,turns=math.inf,ohko=0,move_id=attack['id'],move=name,effectiveness=matchup)
    base=(((2*attacker['level']//5+2)*power*av//max(1,dv))//50)+2
    if physical and attacker.get('status_code',0)&0x10 and aid!=62:base=max(1,base//2)
    if typ in own:base=base*3//2
    base=max(1,int(base*matchup))
    fixed={"SEISMIC TOSS":attacker['level'],"NIGHT SHADE":attacker['level'],"DRAGON RAGE":40,"SONICBOOM":20}
    if name in fixed:rolls=[fixed[name]]*16
    elif effect=='SUPER_FANG':rolls=[max(1,defender['hp']//2)]*16
    elif effect=='ENDEAVOR':rolls=[max(0,defender['hp']-attacker['hp'])]*16
    else:rolls=[max(1,base*r//100) for r in range(85,101)]
    multihit=effect in ('MULTI_HIT','DOUBLE_HIT','TWINEEDLE','TRIPLE_KICK')
    if multihit:
        # Two-hit moves are exact; 2–5 hit estimates are intentionally marked.
        counts=[2] if effect in ('DOUBLE_HIT','TWINEEDLE') else [2,2,2,3,3,3,4,5]
        rolls=[r*n for n in counts for r in rolls]
    accuracy=(attack.get('accuracy') or 100)/100
    if attack.get('accuracy'):
        stages=attacker.get('stages',{}).get('accuracy',0)-defender.get('stages',{}).get('evasion',0)
        accuracy*=stage_multiplier(stages,accuracy=True)
        accuracy*=ABILITY_RULES.get(aid,{}).get('accuracy_multiplier',1)
        if physical:accuracy*=ABILITY_RULES.get(aid,{}).get('physical_accuracy_multiplier',1)
    accuracy=min(1,max(0,accuracy));hp=defender['hp'];mean=sum(rolls)/len(rolls)
    # Average over all damage rolls, including misses. Better than raw power.
    turns=sum(math.ceil(hp/max(1,r)) for r in rolls)/len(rolls)/max(.001,accuracy)
    return dict(min=min(rolls),max=max(rolls),mean=mean,accuracy=accuracy,turns=turns,ohko=sum(r>=hp for r in rolls)/len(rolls)*accuracy,ohko_on_hit=sum(r>=hp for r in rolls)/len(rolls),move_id=attack['id'],move=name,effectiveness=matchup,approximate=multihit)

def ranked_attacks(mon,enemy,root):
    rows=[(i,estimate(mon,enemy,m,root)) for i,m in attacks(mon,root)]
    return sorted((p for p in rows if p[1]['mean']>0),key=lambda p:(p[1]['turns'],-p[1]['ohko'],-p[1]['mean']))

def escape_info(mon,enemy_speed=None):
    if mon is None:return dict(guaranteed=False,reason='Нет отдельного Pokémon для побега',chance=None)
    from .field_tools import teleport_slot
    if teleport_slot(mon) is not None:return dict(guaranteed=False,reason='Teleport: требует PP, не действует при некоторых ловушках',chance=None)
    if mon.get('held_item')==194:return dict(guaranteed=True,reason='Smoke Ball',chance=1)
    if ABILITY_RULES.get(mon.get('ability_id'),{}).get('escape_guaranteed'):return dict(guaranteed=True,reason='Run Away',chance=1)
    speed=mon.get('stats',{}).get('speed',0)
    if mon.get('status_code',0)&0x40:speed//=4
    if enemy_speed is None:return dict(guaranteed=False,reason='По скорости; Run Away отсутствует',chance=None)
    chance=1 if speed>=enemy_speed else min(1,(speed*128//max(1,enemy_speed)+30)/256)
    return dict(guaranteed=chance==1,reason='Скорость' if chance==1 else 'Побег не гарантирован',chance=chance)
