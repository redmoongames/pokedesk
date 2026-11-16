"""Build versioned Russian move articles from ROM facts and reviewed effect copy.

No network access during a build or at runtime. move_research.json records the
pinned PokéAPI CSV import; modern effect prose is not treated as Gen III rules.
"""
from pathlib import Path
import json,re,hashlib
ROOT=Path(__file__).resolve().parents[1]

def build(root=ROOT):
    base=json.loads((root/'vendor/catalog/firered.json').read_text());copy=json.loads((root/'vendor/reference/move_explanations_ru.json').read_text());research=json.loads((root/'vendor/reference/move_research.json').read_text())
    names={int(m[2]):m[1] for m in re.finditer(r'^#define\s+EFFECT_(\w+)\s+(\d+)',(root/'vendor/reference/battle_move_effects.h').read_text(),re.M)}
    stats={'ATTACK':'Атаку','DEFENSE':'Защиту','SPEED':'Скорость','SPECIAL_ATTACK':'Спец. атаку','SPECIAL_DEFENSE':'Спец. защиту','ACCURACY':'Точность','EVASION':'Уклонение'}
    articles={}
    for key,m in base['moves'].items():
        name=names[m['effect_id']];entry=copy['effects'].get(name)
        match=re.fullmatch(r'(ATTACK|DEFENSE|SPEED|SPECIAL_ATTACK|SPECIAL_DEFENSE|ACCURACY|EVASION)_(UP|DOWN)(?:_(2|3))?(_HIT)?',name)
        if entry is None and match:
            stat,change,count,hit=match.groups();count=int(count or 1);who='пользователя' if change=='UP' else 'цели';verb='Повышает' if change=='UP' else 'Снижает'
            text=f'{verb} {stats[stat]} {who} на {count} '+('ступень.' if count==1 else 'ступени.')
            if hit:text=f'Наносит урон; с вероятностью {{chance}}% '+text[0].lower()+text[1:]
            base_stage=3 if stat in ('ACCURACY','EVASION') else 2
            multiplier=(base_stage+count)/base_stage if change=='UP' else base_stage/(base_stage+count)
            entry=dict(summary=text,details=[f'Из нейтрального состояния это множитель ×{multiplier:.3g}. Ступени ограничены диапазоном −6…+6. Обычная замена снимает усиления и ослабления; способности и специальные эффекты могут заблокировать изменение.'])
        assert entry is not None,('Missing reviewed effect',key,name)
        override=copy['moves'].get(key,{})
        summary=override.get('summary',entry['summary']).replace('{chance}',str(m['effect_chance']))
        details=[t.replace('{chance}',str(m['effect_chance'])) for t in entry['details']]+override.get('notes',[])
        mode=override.get('coverage','status' if m['category']=='Status' else 'standard')
        if name=='OHKO':mode='ohko'
        slug=research['moves'][key]['slug']
        articles[key]=dict(id=m['id'],slug=slug,summary=summary,details=details,coverage=mode,immunities=override.get('immunities',[]),sources=['rom','pret','pokeapi'],dex_url='https://pokemondb.net/move/'+slug,serebii_url='https://www.serebii.net/attackdex/'+slug.replace('-','')+'.shtml')
    assert set(articles)==set(base['moves'])
    return dict(schema=1,generation=3,game=base['game'],rom_sha1=base['rom_sha1'],pokeapi_commit=research['pokeapi_commit'],sources=dict(rom=dict(label='FireRed Rev 1 · таблицы игры',url=base['sources'][0]),pret=dict(label='Механика FireRed',url=base['sources'][1]),pokeapi=dict(label='PokéAPI · структурированные данные',url='https://github.com/PokeAPI/pokeapi/tree/'+research['pokeapi_commit']+'/data/v2/csv')),editorial_sha256=hashlib.sha256((root/'vendor/reference/move_explanations_ru.json').read_bytes()).hexdigest(),moves=articles)

if __name__=='__main__':
    result=build();(ROOT/'vendor/catalog/moves_ru.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print('Built',len(result['moves']),'Russian FireRed move articles')
