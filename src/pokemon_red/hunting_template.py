"""Publish a verified, read-only hunting baseline from a detached game only."""
from pathlib import Path
import hashlib,os,time,uuid
from .acquisition import WILD_TEMPLATE,write_json,read_json,template_for
from .models import read_inventory
from .catalog import catalog
from .capture import capture_kit
from .telemetry import read_state
from .persistence import sync_directory

def publish_template(project,player,origin_hash):
    folder=Path(project)/template_for(project,WILD_TEMPLATE)
    if folder.exists():raise ValueError('Шаблон уже существует; новая версия должна иметь другое имя')
    s=player.state();inv=read_inventory(player.g)
    hunters=[m for m in inv['party'] if capture_kit(m)]
    if s['in_battle'] or s['controls']['field_locked'] or not s['map']['name'].endswith('_PokemonCenter_1F') or len(inv['party'])<2 or not hunters:raise ValueError('Шаблон должен быть в Center с охотником, усыплением и Leech Seed')
    hunter=inv['party'][0]
    if hunter not in hunters:raise ValueError('Охотник должен быть первым в команде')
    routes={};excluded={}
    for name,record in catalog(player.g.root)['routes'].items():
        if name not in player.nav.spec['zones']:continue
        try:
            area=player.nav.choose_farm(name)
            routes[name]=dict(population=record['population'],encounter_rate=record['encounter_rate'],terrain=record.get('terrain','grass'),area=area)
        except RuntimeError as error:excluded[name]=str(error)
    if not routes:raise ValueError('Не найден доступный маршрут охоты')
    folder.parent.mkdir(parents=True,exist_ok=True);pending=folder.with_name('.'+folder.name+'-'+uuid.uuid4().hex)
    player.g.save_to(pending)
    write_json(pending/'metadata.json',dict(schema_version=1,template_id='progressed-hunting-v1',display_name='Открытые территории · подготовленный охотник',created_at=time.time(),origin_state_sha256=origin_hash,hunter_uid=hunter['uid'],hunter=hunter,state=s,inventory=inv,routes=routes,excluded=excluded,identity='Independent branch; original trainer ID and original Pokémon identities retained'))
    (pending/'README.txt').write_text('Защищённый шаблон охоты. Создан из копии текущей основной игры.\nКаждое задание копирует FireRed.state и FireRed.sav в собственный Data.\nНе заменять основную игру этими файлами. Исходные имя и ID тренера сохранены.\n')
    write_json(pending/'manifest.json',dict(algorithm='sha256',files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in pending.iterdir()}))
    for path in pending.iterdir():path.chmod(0o444)
    pending.chmod(0o555);os.rename(pending,folder);sync_directory(folder.parent)
    return folder

def wild_options(project):
    meta=read_json(Path(project)/template_for(project,WILD_TEMPLATE)/'metadata.json',{})
    from .capture_target import catchable_species
    return sorted({m['species_id'] for r in meta.get('routes',{}).values() for m in r['population']} & catchable_species(Path(project)))

def choose_route(project,species_id):
    """Prefer frequent encounters with good catch odds, then lower levels/travel."""
    from .capture import catch_probability
    from .catalog import species
    from .capture_target import catchable_species
    if species_id not in catchable_species(Path(project)):
        from .i18n import t
        raise ValueError(t('capture.not_in_game'))
    meta=read_json(Path(project)/template_for(project,WILD_TEMPLATE)/'metadata.json',{});choices=[]
    for name,r in meta.get('routes',{}).items():
        mon=next((m for m in r['population'] if m['species_id']==species_id),None)
        if not mon:continue
        rate=species(species_id,project)['catch_rate']
        chance=catch_probability(rate,mon['hp_max'],mon['hp_max'],level=mon['min_level'])['probability']
        score=mon['probability']*r['encounter_rate']*max(chance,.01)
        choices.append(((-score,mon['max_level'],r['area']['cost'][1],name),name))
    if not choices:raise ValueError('Нет доступного маршрута для этого Pokémon')
    return min(choices)[1]
