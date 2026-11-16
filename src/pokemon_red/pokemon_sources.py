"""Species acquisition for the pinned FireRed version, not LeafGreen slot tables."""

from .paths import resource
from functools import lru_cache
from pathlib import Path
from collections import defaultdict
import json,re
from .catalog import catalog,species,evolution_text
from .evolution_reference import EvolutionIndex
from .encounters import level_label
from .locations import NAMES
from .editions import edition,reference_path

METHODS={'land_mons':'Пешком','water_mons':'Surf','rock_smash_mons':'Rock Smash',
         'old_rod':'Old Rod','good_rod':'Good Rod','super_rod':'Super Rod'}
# Pinned map scripts, FireRed branch; these are fixed purchases, not encounters.
GAME_CORNER={63:180,35:500,147:2800,123:5500,137:9999}
AREA_NAMES={**NAMES,'SafariZone':'Сафари-зона','PokemonTower':'Башня покемонов',
    'PokemonMansion':'Особняк покемонов','SeafoamIslands':'Острова Пены',
    'VictoryRoad':'Дорога Победы','CeruleanCave':'Церулинская пещера','PowerPlant':'Электростанция',
    'BerryForest':'Ягодный лес','PatternBush':'Узорчатый лес','MtEmber':'Гора Эмбер',
    'CinnabarIsland':'Остров Синнабар','FuchsiaCity':'Фуксия','OneIsland':'Остров 1','TwoIsland':'Остров 2',
    'ThreeIsland':'Остров 3','FourIsland':'Остров 4','FiveIsland':'Остров 5','SixIsland':'Остров 6','SevenIsland':'Остров 7',
    'IcefallCave':'Ледяная пещера','AlteringCave':'Изменчивая пещера','LostCave':'Затерянная пещера',
    'TanobyRuins':'Руины Таноби','Center':'центр','North':'север','South':'юг','East':'восток','West':'запад',
    'Entrance':'вход','Back':'дальняя часть','Exterior':'снаружи','Interior':'внутри','Summit':'вершина'}

def location_title(name):
    from .locations import location_name
    return location_name(name,locale='en')

def location_note(name):
    if name.startswith('PokemonTower_'):return 'Для опознания и поимки призраков нужен Silph Scope.'
    if 'TanobyRuins' in name:return 'Встречи Unown открываются после загадки Tanoby Key.'
    if name.startswith('SafariZone_'):return 'Встречи по правилам Safari Zone; шанс поимки зависит от её механики.'
    if name.startswith('CeruleanCave_'):return 'Поздняя локация: требуется завершить сюжет и восстановить сеть Селио.'
    return ''

@lru_cache
def encounter_index(root,version=None):
    root=Path(root);group=json.loads(reference_path(root,'wild_encounters.json').read_text())['wild_encounter_groups'][0]
    constants={n:int(v) for n,v in re.findall(r'^#define\s+(SPECIES_\w+)\s+(\d+)\b',(resource(root,'vendor/reference/species.h')).read_text(),re.M)}
    topology=json.loads(reference_path(root,'world_topology.json').read_text())['maps']
    maps={v['symbol']:k for k,v in topology.items()};fields={v['type']:v for v in group['fields']};result=defaultdict(list)
    for row in group['encounters']:
        if not row['base_label'].endswith('_'+(version or edition(root).name)) or re.search(r'AlteringCave_[2-9]_',row['base_label']):continue
        name=maps[row['map']]
        for field,definition in fields.items():
            if field not in row:continue
            info=row[field]
            if not info['encounter_rate']:continue
            groups=definition.get('groups') or {field:list(range(len(info['mons'])))}
            for method,slots in groups.items():
                totals={}
                for slot in slots:
                    mon=info['mons'][slot];number=constants[mon['species']];weight=definition['encounter_rates'][slot]
                    record=totals.setdefault(number,dict(probability=0,levels={}))
                    record['probability']+=weight
                    for level in range(mon['min_level'],mon['max_level']+1):
                        record['levels'][str(level)]=record['levels'].get(str(level),0)+weight/(mon['max_level']-mon['min_level']+1)
                if sum(r['probability'] for r in totals.values())!=100:raise ValueError('Invalid encounter weights: '+row['base_label'])
                for number,data in totals.items():
                    result[number].append(dict(map=name,location=location_title(name),method=method,method_label=METHODS[method],
                        probability=data['probability'],levels=data['levels'],level_label=level_label(data),note=location_note(name)))
    for rows in result.values():rows.sort(key=lambda r:(r['location'],list(METHODS).index(r['method'])))
    return dict(result)

def encounters(number,root):return encounter_index(Path(root)).get(number,[])

def evolution_condition(edge,root):
    method=edge['method'];level=edge['parameter']
    if method in (2,3) and edition(root).family=='hoenn':return 'Дружба ≥220 и повышение уровня '+('днём.' if method==2 else 'ночью.')
    if method in (2,3):return 'В FireRed эта эволюция недоступна. Нужны дружба ≥220 и повышение уровня '+('днём' if method==2 else 'ночью')+' в Ruby, Sapphire или Emerald, затем обмен обратно.'
    if method==5:return 'Обменять Pokémon с другим сохранением. Уровень не важен.'
    if method==6:return 'Обменять Pokémon, держащего '+catalog(root)['items'][str(level)]+'. Предмет расходуется при эволюции.'
    if method==7:return 'Использовать '+catalog(root)['items'][str(level)]+'. Повышать уровень не требуется.'
    if method in (4,13):return f'Повысить уровень до {level} или выше.'
    if method in (8,9,10):return f'Повышение уровня начиная с Lv {level}; показатель Атаки '+{8:'больше',9:'равен показателю',10:'меньше'}[method]+' Защиты.'
    if method in (11,12):return f'Повысить уровень до {level}. Эта ветка определяется скрытым значением данного Pokémon; повторная попытка его не изменит.'
    if method==14:return f'При эволюции Nincada на уровне {level}: свободное место в отряде и обычный Poké Ball в сумке.'
    if method==15:return f'Красота ≥{level}, затем повышение уровня.'+(' Красоту можно повысить Pokéblock.' if edition(root).family=='hoenn' else ' Красоту нужно подготовить в Ruby, Sapphire или Emerald.')
    return evolution_text(edge,root)+'.'

def source_data(number,root):
    root=Path(root);data=catalog(root);index=EvolutionIndex(data['species']);sp=species(number,root)
    parents=[dict(species_id=parent,name=species(parent,root)['name'],condition=evolution_condition(edge,root),method=edge['method']) for parent,edge in index.parents[number]]
    # Final identity, never a temporary form browsed on the learnset tab.
    related=[]
    for other in index.family(number):
        if other==number:continue
        relation='Предыдущая форма' if any(p==other for p,_ in index.parents[number]) else 'Следующая форма' if other in index.children(number) else 'Более ранняя форма' if number in index.descendants(other) else 'Более поздняя форма' if other in index.descendants(number) else 'Другая ветка эволюции'
        related.append(dict(species_id=other,name=species(other,root)['name'],relation=relation))
    alternatives=[]
    if edition(root).family=='kanto' and sp['national_id'] in GAME_CORNER:alternatives.append('Селадон · призовой зал Game Corner: '+str(GAME_CORNER[sp['national_id']])+' монет. Нужен Coin Case.')
    if edition(root).family=='kanto' and sp['national_id']==129:alternatives.append('Pokémon Center на Маршруте 4: покупка Magikarp уровня 5 за ₽500, один раз за прохождение.')
    if edition(root).family=='hoenn':
        from .location_reference import reference
        for name,place in reference(root)['maps'].items():
            for obj in place['objects']:
                for mon in obj['facts']['pokemon']:
                    if mon['species_id']==number:alternatives.append(location_title(name)+' · '+mon.get('kind','подарок / особая встреча')+' · Lv '+str(mon['level']))
    return dict(number=number,name=sp['name'],parents=parents,related=related,encounters=encounters(number,root),alternatives=alternatives,
                needs_national_dex=edition(root).family=='kanto' and sp['national_id']>151 and any(p['method'] not in (2,3) for p in parents))
