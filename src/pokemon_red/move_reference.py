"""Presentation-only Gen III articles; battle numbers remain the ROM's facts."""

CATEGORY_RU={'Physical':'Физический','Special':'Специальный','Status':'Статусный'}


def enrich_reference(data,reference):
    from .editions import FIRERED,EDITIONS
    compatible=reference.get('rom_sha1')==FIRERED.sha1 and data.get('rom_sha1') in {e.sha1 for e in EDITIONS.values()}
    if reference.get('generation')!=3 or reference.get('rom_sha1')!=data.get('rom_sha1') and not compatible:
        raise ValueError('Справочник приёмов не соответствует версии игры')
    if set(reference['moves'])!=set(data['moves']):raise ValueError('Неполный справочник приёмов')
    data['move_reference']={k:v for k,v in reference.items() if k!='moves'}
    for key,m in data['moves'].items():
        article=reference['moves'][key]
        if not article.get('summary') or not article.get('details'):raise ValueError('Нет описания приёма '+key)
        m['description_en']=m['description'];m['description']=article['summary'];m['reference']=article
    return data


def power_text(m):
    name=m.get('effect_name');mode=m.get('reference',{}).get('coverage')
    if m.get('category')=='Status':return '—'
    if name=='HIDDEN_POWER':return '30–70'
    if name=='WEATHER_BALL':return '50 / 100'
    ranges={'LOW_KICK':'20–120','FLAIL':'20–200','RETURN':'1–102','FRUSTRATION':'1–102','ERUPTION':'1–150','MAGNITUDE':'10–150','SPIT_UP':'100–300','PRESENT':'40–120'}
    if name in ranges:return ranges[name]
    if mode=='ohko':return 'KO'
    if mode=='fixed' or name in ('BIDE','BEAT_UP'):return 'Особая'
    return str(m['power']) if m['power']>1 else 'Особая'


def accuracy_text(m):
    name=m.get('effect_name')
    if name=='OHKO':return '30% + ур.'
    if name in ('ALWAYS_HIT','VITAL_THROW'):return 'Без проверки'
    if not m['accuracy']:return '—'
    return str(m['accuracy'])+'%'


def category_text(m):
    if m.get('effect_name') in ('HIDDEN_POWER','WEATHER_BALL','NATURE_POWER'):return 'Зависит от типа'
    mode=m.get('reference',{}).get('coverage')
    if mode=='fixed':return 'Фиксированный урон'
    if mode=='ohko':return 'Мгновенный KO'
    if m.get('effect_name')=='BEAT_UP':return 'Особый расчёт'
    if mode=='special':return 'Вызывает другой приём'
    return CATEGORY_RU.get(m.get('category'),'—')


def offensive_profile(m,effectiveness):
    """Single-type targets. Fixed and typeless damage must never imply x2/x0.5."""
    article=m.get('reference',{});mode=article.get('coverage','status' if m['category']=='Status' else 'standard')
    result=dict(mode=mode,strong=[],resisted=[],immune=[])
    if mode in ('status','variable','typeless','special'):return result
    if mode=='fixed':result['immune']=article.get('immunities',[]);return result
    for target in range(18):
        if target==9:continue
        factor=next((v for a,b,v in effectiveness if a==m['type_id'] and b==target),1)
        if factor==0:result['immune'].append(target)
        elif mode=='standard' and factor>1:result['strong'].append(target)
        elif mode=='standard' and factor<1:result['resisted'].append(target)
    return result
