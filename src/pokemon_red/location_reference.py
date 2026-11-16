from .editions import reference_path
"""Static map reference, with small one-shot save overlays; no live NPC tracking."""
from functools import lru_cache
from pathlib import Path
import json,re
from .locations import location_name
from .catalog import catalog,species

METHODS={'land_mons':'Трава / пещера','water_mons':'Surf','rock_smash_mons':'Rock Smash','old_rod':'Старая удочка','good_rod':'Хорошая удочка','super_rod':'Суперудочка'}
ROLES={'NURSE':'Медсестра','MART_CLERK':'Продавец','GYM_GUY':'Сотрудник стадиона','SCIENTIST':'Учёный','OAK':'Профессор Oak','FAT_MAN':'Житель','BOY':'Мальчик','GIRL':'Девочка','YOUNGSTER':'Юный тренер','WOMAN_1':'Жительница','WOMAN_2':'Жительница','MAN':'Житель','OLD_MAN':'Пожилой житель','OLD_WOMAN':'Пожилая жительница','CUT_TREE':'Дерево Cut','ROCK_SMASH_ROCK':'Камень Rock Smash','PUSHABLE_BOULDER':'Камень Strength'}

@lru_cache(maxsize=8)
def reference(root):return json.loads(reference_path(root,'location_reference.json').read_text())

def point_label(point):return f'X {point[0]}, Y {point[1]}' if point and None not in point else 'Координаты не определены'
def moving(obj):return any(k in obj['movement'] for k in ('WALK','WANDER','PACE')) and 'IN_PLACE' not in obj['movement']
def object_name(obj):
    if obj.get('trainers'):
        t=obj['trainers'][0];return t['trainer_class'].replace('_',' ').title()+' '+t['name'].title()
    role=obj['script'].split('_EventScript_')[-1] if '_EventScript_' in obj['script'] else obj['graphics']
    return ROLES.get(obj['graphics'],re.sub(r'(?<=[a-z])(?=[A-Z])',' ',role).replace('_',' '))

def map_info(root,name,flag_set=None):
    value=reference(root)['maps'].get(name)
    if value is None:return None
    value=json.loads(json.dumps(value));value['name']=name;value['label']=location_name(name)
    for obj in value['objects']:
        obj['label']=object_name(obj);obj['moving']=moving(obj)
        flag=obj.get('hide_flag');obj['hidden_now']=bool(flag_set and flag and flag_set(flag))
        for trainer in obj['trainers']:trainer['defeated']=bool(flag_set and trainer['id'] is not None and flag_set(0x500+trainer['id']))
    for item in value['items']:
        item['name']=catalog(root)['items'].get(str(item['item_id']),str(item['item_id']))
        flag=item.get('hide_flag');item['collected']=bool(flag_set and flag and flag_set(flag))
    return value
