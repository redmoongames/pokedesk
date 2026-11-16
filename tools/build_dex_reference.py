"""Reproducible version availability, using pinned FR/LG encounter + ROM tables.

This describes species obtainable over possible playthrough choices, not a
single save's progress. Unreleased Altering Cave encounter switches are omitted.
"""
from pathlib import Path
import json,re

ROOT=Path(__file__).resolve().parents[1]
GIFTS={1:'Стартовый у профессора Оука',4:'Стартовый у профессора Оука',7:'Стартовый у профессора Оука',
       83:'Обмен с NPC в Vermilion',106:'Выбор награды в Fighting Dojo',107:'Выбор награды в Fighting Dojo',
       108:'Обмен с NPC на Route 18',122:'Обмен с NPC на Route 2',124:'Обмен с NPC в Cerulean',
       131:'Подарок в Silph Co.',133:'Подарок в Celadon',137:'Приз Game Corner в Celadon',
       138:'Восстановление Helix Fossil',140:'Восстановление Dome Fossil',142:'Восстановление Old Amber',
       143:'Спящий Snorlax',144:'Легендарная встреча на Seafoam Islands',145:'Легендарная встреча в Power Plant',
       146:'Легендарная встреча на Mt. Ember',150:'Легендарная встреча в Cerulean Cave',175:'Яйцо на Water Labyrinth',
       243:'Скитающийся Raikou, если стартовый — Squirtle',244:'Скитающийся Entei, если стартовый — Bulbasaur',
       245:'Скитающийся Suicune, если стартовый — Charmander'}
BABIES={172:25,173:35,174:39,236:106,238:124,239:125,240:126,298:183,360:202}
EVENTS={151:'Mew: историческая раздача или перенос из Emerald с событийным Old Sea Map (японская версия).',
        249:'Lugia: Navel Rock по событийному MysticTicket; также перенос из Pokémon XD.',
        250:'Ho-Oh: Navel Rock по событийному MysticTicket; также перенос из Pokémon Colosseum.',
        251:'Celebi: историческая раздача, в том числе японский бонусный диск Colosseum.',
        385:'Jirachi: специальное получение в совместимых играх поколения III (например, бонусный диск Colosseum или Pokémon Channel).',
        386:'Deoxys: Birth Island по событийному AuroraTicket. В FireRed используется атакующая форма.'}

def build(root=ROOT,game='FireRed'):
    reference=json.loads((root/'vendor/catalog/firered.json').read_text());sp=reference['species']
    constants={name:int(value) for name,value in re.findall(r'^#define SPECIES_(\w+)\s+(\d+)\b',(root/'vendor/reference/species.h').read_text(),re.M)}
    bynational={v['national_id']:int(k) for k,v in sp.items()}
    encounters=json.loads((root/'vendor/reference/wild_encounters.json').read_text())['wild_encounter_groups'][0]['encounters']
    versions={}
    for version in ('FireRed','LeafGreen'):
        available={}
        for row in encounters:
            if not row['base_label'].endswith(version) or re.search(r'AlteringCave_[2-9]_',row['base_label']):continue
            for data in row.values():
                if not isinstance(data,dict):continue
                for mon in data.get('mons',[]):
                    n=constants[mon['species'].removeprefix('SPECIES_')]
                    if str(n) in sp:available.setdefault(n,dict(method='wild',trade=False))
        for national,note in GIFTS.items():available.setdefault(bynational[national],dict(method='gift',note=note,trade=False))
        while True:
            before=len(available)
            for n,origin in list(available.items()):
                for evo in sp[str(n)]['evolutions']:
                    # FireRed/LeafGreen have no working daytime/nighttime evolution.
                    if evo['method'] in (2,3):continue
                    available.setdefault(evo['target'],dict(method='evolution',parent=n,evolution=evo,trade=origin['trade'] or evo['method'] in (5,6)))
            for child,parent in BABIES.items():
                if bynational[parent] in available:
                    available.setdefault(bynational[child],dict(method='breed',parent=bynational[parent],trade=False))
            if len(available)==before:break
        versions[version]=available
    result={}
    for key,s in sp.items():
        n=int(key);national=s['national_id'];fr=versions[game].get(n);lg=versions['LeafGreen' if game=='FireRed' else 'FireRed'].get(n)
        category='event' if national in EVENTS else 'firered' if fr else 'leafgreen' if lg else 'other'
        entry=dict(national_id=national,category=category)
        if fr:entry.update(fr)
        elif lg:entry['leafgreen_method']=lg
        if national in EVENTS:entry['note']=EVENTS[national]
        if national in (196,197):entry['note']='Eevee доступен в FireRed, но для этой эволюции нужны день или ночь. Эволюционируй в Ruby, Sapphire или Emerald и перенеси обратно.'
        if national in (1,2,3,4,5,6,7,8,9):entry['choice']='В одном прохождении выбирается один стартовый. Остальных можно получить с другого сохранения.'
        if national in (138,139,140,141):entry['choice']='В Mt. Moon выбирается одна из двух окаменелостей. Для второй ветки потребуется другое сохранение.'
        if national in (243,244,245):entry['choice']=GIFTS[national]+'. В одном прохождении появляется один из трёх.'
        if national==298:entry['note']='Marill из LeafGreen; разведение с Sea Incense на Four Island. Можно также перенести из Ruby, Sapphire или Emerald.'
        if national==360:entry['note']='Разведение Wobbuffet с Lax Incense на Four Island. Без этого предмета из яйца вылупится Wobbuffet.'
        result[key]=entry
    return dict(format=1,game='Original GBA FireRed / LeafGreen',sources=[
        'https://github.com/pret/pokefirered/tree/ce6406d8c2eaf46d543c8a2606de0c3cb1951982',
        'https://www.serebii.net/fireredleafgreen/exclusives.shtml',
        'https://www.serebii.net/fireredleafgreen/unobtainable.shtml'],species=result)

if __name__=='__main__':
    output=build();(ROOT/'vendor/reference/dex_availability.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
    from collections import Counter
    print(Counter(s['category'] for s in output['species'].values()))
