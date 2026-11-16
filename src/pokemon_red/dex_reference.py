from .i18n import search_matches,render
from .entity_names import entity_aliases
from .editions import reference_path,edition
"""Offline species provenance, independent of live route/automation availability."""
from functools import lru_cache
import json
from .engine import ROOT
from .catalog import catalog,species,evolution_text
from .types_ui import TYPE_INFO

CATEGORIES={'firered':'FireRed','leafgreen':'LeafGreen · обмен','other':'Другая игра','event':'Особое получение'}

@lru_cache
def availability(root=ROOT):
    return json.loads(reference_path(root,'dex_availability.json').read_text())['species']

def origin(number,root=ROOT):return availability(root)[str(number)]

def origin_label(number,root=ROOT):
    row=origin(number,root)
    return edition_text('FireRed · обмен' if row['category']=='firered' and row.get('trade') else CATEGORIES[row['category']],root)

def origin_description(number,root=ROOT):
    row=origin(number,root);category=row['category'];parts=[]
    if category=='firered':
        method=row.get('method')
        if method=='wild':parts.append('Можно поймать в FireRed.')
        elif method=='gift':parts.append(row.get('note','Получение в FireRed')+'.')
        elif method=='breed':parts.append('Разведение '+species(row['parent'],root)['name']+' на Four Island.')
        elif method=='evolution':parts.append('Из '+species(row['parent'],root)['name']+': '+evolution_text(row['evolution'],root)+'.')
        if row.get('trade'):parts.append('Для эволюции нужен обмен с другим сохранением. Исходный вид доступен в FireRed.')
        if row.get('note') and method!='gift':parts.append(row['note'])
        parts.append('Доступ зависит от сюжета и открытых территорий; эта пометка не означает «можно поймать сейчас».')
    elif category=='leafgreen':
        parts.append('Эта линия доступна в LeafGreen. Перенеси Pokémon или его предка обменом и при необходимости развей в FireRed.')
        if row.get('note'):parts.append(row['note'])
    elif category=='other':
        parts.append(row.get('note','В обычном прохождении FireRed и LeafGreen не получается. Нужен перенос из совместимой игры поколения III: Ruby, Sapphire, Emerald, Colosseum или XD.'))
    else:parts.append(row['note']+' В обычном прохождении GBA без специальных условий не получается.')
    if row.get('choice'):parts.append(row['choice'])
    return edition_text(' '.join(parts),root)

def edition_text(text,root):
    if edition(root).family=='hoenn':
        local=edition(root).name;other='Sapphire' if local=='Ruby' else 'Ruby'
        return text.replace('FireRed','__local__').replace('LeafGreen',other).replace('__local__',local).replace('Four Island','Route 117').replace('атакующая форма','обычная форма')
    if edition(root).id!='leafgreen':return text
    return text.replace('FireRed','__edition__').replace('LeafGreen','FireRed').replace('__edition__','LeafGreen').replace('атакующая форма','защитная форма')

def dex_rows(root=ROOT):
    return sorted(catalog(root)['species'].values(),key=lambda row:row['national_id'])

def filter_dex(rows,query='',category='all',root=ROOT):
    query=query.strip().casefold();result=[]
    for sp in rows:
        entry=origin(sp['id'],root)
        if category!='all' and entry['category']!=category:continue
        types=' '.join(' '.join(TYPE_INFO.get(t,TYPE_INFO[9])[:2]) for t in sp['type_ids'])
        text=f"{sp['name']} #{sp['national_id']:03} {sp['national_id']} {types} {origin_label(sp['id'],root)}".casefold()
        english_types=' '.join(render(TYPE_INFO.get(typ,TYPE_INFO[9])[0],locale='en') for typ in sp['type_ids'])
        if search_matches(query,text,english_types,render(origin_label(sp['id'],root),locale='en'),entity_aliases('species',sp['id']),' '.join(entity_aliases('abilities',n) for n in sp.get('abilities',[]))) :result.append(sp)
    return result
