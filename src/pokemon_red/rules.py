"""Versioned Gen III move rules shared by planning, battle policy and reference UI."""

from .paths import resource
import re

STAT_NAMES={'attack':'Атака','defense':'Защита','speed':'Скорость','special_attack':'Спец. атака','special_defense':'Спец. защита','accuracy':'Точность','evasion':'Уклонение'}
ABILITY_RULES={
    50:dict(escape_guaranteed=True,text='Гарантированный побег из обычного дикого боя. Не позволяет убежать из боя с тренером.'),
    62:dict(status_attack_multiplier=1.5,text='При статусном состоянии физическая атака ×1.5; штраф атаки от ожога не применяется.'),
    14:dict(accuracy_multiplier=1.3,text='Точность атак ×1.3, максимум 100%.'),
    51:dict(prevents_accuracy_drop=True,text='Противник не может понизить точность.'),
    9:dict(contact_paralysis_chance=.3,text='Контактная атака противника может вызвать паралич (30%).'),
    26:dict(immune_type=4,text='Невосприимчивость к Ground-атакам.'),
    10:dict(immune_type=13,text='Electric-атака противника восстанавливает до ¼ максимального HP вместо урона.'),
    11:dict(immune_type=11,text='Water-атака противника восстанавливает до ¼ максимального HP вместо урона.'),
    18:dict(immune_type=10,text='Невосприимчивость к Fire-атакам; после срабатывания сила собственных Fire-атак ×1.5.'),
    25:dict(only_super_effective=True,text='Пропускает прямой урон только от суперэффективных атак. Есть исключения и косвенный урон.'),
    47:dict(reduced_types=[10,15],attack_multiplier=.5,text='Атакующая характеристика противника для Fire/Ice-урона уменьшается вдвое.'),
    37:dict(attack_multiplier=2,text='Физическая атака ×2.'),74:dict(attack_multiplier=2,text='Физическая атака ×2.'),
    55:dict(attack_multiplier=1.5,physical_accuracy_multiplier=.8,text='Физическая атака ×1.5; точность физических атак ×0.8.'),
    65:dict(low_hp_type=12,text='При HP ≤⅓ сила Grass-атак ×1.5.'),66:dict(low_hp_type=10,text='При HP ≤⅓ сила Fire-атак ×1.5.'),67:dict(low_hp_type=11,text='При HP ≤⅓ сила Water-атак ×1.5.'),68:dict(low_hp_type=6,text='При HP ≤⅓ сила Bug-атак ×1.5.')}

def stage_multiplier(stage,*,accuracy=False):
    stage=max(-6,min(6,int(stage)));base=3 if accuracy else 2
    return (base+stage)/base if stage>=0 else base/(base-stage)

def enrich_moves(data,root,*,game=None):
    from .editions import edition
    game=game or edition(root)
    sprite_root='assets/pokemon-rs' if game.family=='hoenn' else 'assets/pokemon'
    for info in data['species'].values():
        info['sprite_path']=f"{sprite_root}/{info['national_id']}.png";info['shiny_sprite_path']=f"{sprite_root}/shiny/{info['national_id']}.png"
    for key,entry in data['abilities'].items():entry['mechanics']=ABILITY_RULES.get(int(key),{})
    constants={int(m[2]):m[1].removeprefix('EFFECT_') for m in re.finditer(r'^#define\s+(EFFECT_\w+)\s+(\d+)',(resource(root,'vendor/reference/battle_move_effects.h')).read_text(),re.M)}
    for move in data['moves'].values():
        name=constants.get(move['effect_id'],'UNKNOWN');move['effect_name']=name;changes=[]
        match=re.fullmatch(r'(ATTACK|DEFENSE|SPEED|SPECIAL_ATTACK|SPECIAL_DEFENSE|ACCURACY|EVASION)_(UP|DOWN)(?:_(2|3))?(?:_HIT)?',name)
        if match:
            stat,direction,count=match.groups();delta=int(count or 1)*(1 if direction=='UP' else -1)
            changes=[dict(stat=stat.lower(),stages=delta,target='user' if direction=='UP' else 'opponent',chance=move['effect_chance'] or 100)]
        combined={'BULK_UP':[('attack',1),('defense',1)],'CALM_MIND':[('special_attack',1),('special_defense',1)],'DRAGON_DANCE':[('attack',1),('speed',1)],'COSMIC_POWER':[('defense',1),('special_defense',1)],'TICKLE':[('attack',-1),('defense',-1)],'OVERHEAT':[('special_attack',-2)],'SUPERPOWER':[('attack',-1),('defense',-1)],'MEMENTO':[('attack',-2),('special_attack',-2)],'DEFENSE_CURL':[('defense',1)],'MINIMIZE':[('evasion',1)],'SWAGGER':[('attack',2)],'FLATTER':[('special_attack',1)],'BELLY_DRUM':[('attack',6)]}
        if name in combined:changes=[dict(stat=s,stages=d,target='opponent' if name in ('TICKLE','MEMENTO','SWAGGER','FLATTER') else 'user',chance=100) for s,d in combined[name]]
        if name=='BELLY_DRUM':changes=[];move['sets_stages']={'attack':6}
        move['stat_changes']=changes
        move['conditional_damage']=name in ('COUNTER','MIRROR_COAT','BIDE','SPIT_UP','PRESENT','BEAT_UP')
    data['mechanics']=dict(generation=3,stage_min=-6,stage_max=6,
        stat_stages={str(n):stage_multiplier(n) for n in range(-6,7)},
        accuracy_stages={str(n):stage_multiplier(n,accuracy=True) for n in range(-6,7)},
        critical_multiplier=2,normal_critical_chance=1/16,
        physical_types=list(range(9)),special_types=list(range(10,18)))
    from .statuses import STATUS_RULES
    data['mechanics']['statuses']=STATUS_RULES
    return data

def effect_description(move):
    if move.get('sets_stages'):return 'Атака пользователя устанавливается на +6 ступеней (×4 от нейтральной), если хватает HP. Расходуется ½ максимального HP.'
    result=[]
    for change in move.get('stat_changes',[]):
        delta=change['stages'];stat=change['stat'];who='пользователя' if change['target']=='user' else 'противника'
        result.append(f"{STAT_NAMES[stat]} {who}: {delta:+d} ступ. ({change['chance']}%).")
        multiplier=stage_multiplier(delta,accuracy=stat in ('accuracy','evasion'))
        result.append(f"От нейтрального состояния: ×{multiplier:g}. Предел: −6…+6 ступеней.")
        if stat=='defense' and delta>0:result.append(f"Обычный физический урон примерно ×{1/multiplier:.2f}; критические удары и особые эффекты могут изменить расчёт.")
    return ' '.join(result)
