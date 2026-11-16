"""Compile factual FireRed map/NPC/item/encounter reference from pinned pret source.
No dialogue is copied. Coordinates are ROM event anchors, zero-based map tiles.
"""
from pathlib import Path
import argparse,ast,hashlib,json,re,sys
PIN='ce6406d8c2eaf46d543c8a2606de0c3cb1951982';ROOT=Path(__file__).resolve().parents[1]

def constants(source):
    values={};pending={}
    for name in ('items','species','flags','trainers','opponents','vars'):
        if not (source/f'include/constants/{name}.h').is_file():continue
        for key,raw in re.findall(r'^#define\s+(\w+)\s+([^\n]+)',(source/f'include/constants/{name}.h').read_text(),re.M):pending[key]=raw.split('//')[0].strip()
    def expr(n):
        if isinstance(n,ast.Constant) and type(n.value) is int:return n.value
        if isinstance(n,ast.Name):return values[n.id]
        if isinstance(n,ast.BinOp):
            a,b=expr(n.left),expr(n.right)
            if isinstance(n.op,ast.Add):return a+b
            if isinstance(n.op,ast.Sub):return a-b
            if isinstance(n.op,ast.BitOr):return a|b
            if isinstance(n.op,ast.LShift):return a<<b
        raise ValueError()
    for _ in range(8):
        for key,raw in list(pending.items()):
            try:values[key]=expr(ast.parse(raw,mode='eval').body);del pending[key]
            except (ValueError,SyntaxError,KeyError):pass
    return values

def build(source,game='FireRed'):
    rs=game in ('Ruby','Sapphire');pin='5784633ce4ef7ade1a7f2d2d0c288e3d5e6cdd7f' if rs else PIN;repo='pokeruby' if rs else 'pokefirered'
    def edition_text(text):
        stack=[True];known=[]
        output=[]
        for line in text.splitlines():
            directive=re.match(r'\s*\.(ifdef|ifndef|if|else|endif)\b\s*(.*)',line)
            if directive:
                command,value=directive.groups()
                if command in ('ifdef','ifndef','if'):
                    test=(value.strip()==game.upper()) if value.strip() in ('FIRERED','LEAFGREEN','RUBY','SAPPHIRE') else None
                    if test is not None and command=='ifndef':test=not test
                    known.append(test);stack.append(stack[-1] and (test if test is not None else True))
                elif command=='else' and known:stack[-1]=stack[-2] and (not known[-1] if known[-1] is not None else True)
                elif command=='endif' and known:known.pop();stack.pop()
                continue
            if stack[-1]:output.append(line)
        return '\n'.join(output)

    c=constants(source);blocks={};sources={}
    for path in sorted([*source.glob('data/maps/*/scripts.inc'),*source.glob('data/scripts/*.inc')]):
        raw=edition_text(path.read_text());sources[str(path.relative_to(source))]=hashlib.sha256(path.read_bytes()).hexdigest()
        labels=list(re.finditer(r'^(\w+)::?[ \t]*(?:@[^\n]*)?$',raw,re.M))
        for i,m in enumerate(labels):blocks[m[1]]=raw[m.end():labels[i+1].start() if i+1<len(labels) else len(raw)]
    def script_facts(label):
        seen=set();pending=[(label,0)];bodies=[]
        while pending and len(seen)<64:
            name,depth=pending.pop()
            if name in seen or name not in blocks:continue
            seen.add(name);body=blocks[name];bodies.append(body)
            if depth<5:
                for line in body.splitlines():
                    if re.match(r'\s*(?:call|goto|goto_if_\w+|call_if_\w+)\s',line):
                        pending.extend((ref,depth+1) for ref in re.findall(r'\b\w+\b',line) if ref in blocks and '_Text_' not in ref)
        body='\n'.join(bodies)
        items=[]
        for m in re.finditer(r'^\s*(finditem|giveitem|additem)\s+(ITEM_\w+)(?:,\s*(\d+))?',body,re.M):
            if m[2] in c:items.append(dict(item_id=c[m[2]],quantity=int(m[3] or 1),conditional=m[1]!='finditem'))
        pokemon=[]
        for m in re.finditer(r'^\s*(setwildbattle|givemon|givepokemon)\s+(SPECIES_\w+),\s*(\d+)',body,re.M):
            if m[2] in c:pokemon.append(dict(species_id=c[m[2]],level=int(m[3]),kind='static' if m[1]=='setwildbattle' else 'gift'))
        for token,number in (('BulbasaurBall',1),('CharmanderBall',4),('SquirtleBall',7)):
            if label.endswith(token):pokemon=[dict(species_id=number,level=5,kind='gift')]
        trainers=list(dict.fromkeys(m for m in re.findall(r'trainerbattle\w*\s+(TRAINER_\w+)',body) if m in c))
        shop=[]
        for label in re.findall(r'\bpokemart\s+(\w+)',body):shop.extend(c[n] for n in re.findall(r'\bITEM_\w+\b',blocks.get(label,'')) if n in c and c[n])
        return dict(items=list({(r['item_id'],r['quantity']):r for r in items}.values()),pokemon=list({(r['species_id'],r['level'],r['kind']):r for r in pokemon}.values()),trainers=trainers,shop=list(dict.fromkeys(shop)),conditions=sorted({x for x in re.findall(r'\b(?:FLAG|VAR)_\w+\b',body) if x in c}))
    parties={}
    raw=(source/'src/data/trainer_parties.h').read_text()
    for name,body in re.findall(r'((?:sParty_|gTrainerParty_)\w+)\[\]\s*=\s*\{(.*?)\n\};',raw,re.S):
        parties[name]=[dict(species_id=c[sp],level=int(lv)) for lv,sp in re.findall(r'\.(?:lvl|level)\s*=\s*(\d+).*?\.species\s*=\s*(SPECIES_\w+)',body,re.S) if sp in c]
    trainers={}
    raw=(source/('src/data/trainers_en.h' if rs else 'src/data/trainers.h')).read_text()
    for name,body in re.findall(r'^    \[(TRAINER_\w+)\]\s*=\s*\{(.*?)^    \},',raw,re.M|re.S):
        text=re.search(r'\.trainerName\s*=\s*_\("([^"]*)"\)',body);party=re.search(r'\.party\s*=\s*\w+\((\w+)\)',body) or re.search(r'\.party\s*=\s*\{\s*\.\w+\s*=\s*(gTrainerParty_\w+)',body);cl=re.search(r'\.trainerClass\s*=\s*TRAINER_CLASS_(\w+)',body)
        trainers[name]=dict(id=c.get(name),name=text[1] if text else name,trainer_class=cl[1] if cl else '',double='TRUE' in re.search(r'\.doubleBattle\s*=\s*(\w+)',body)[1] if re.search(r'\.doubleBattle\s*=\s*(\w+)',body) else False,party=parties.get(party[1],[]) if party else [])
    maps={};by_symbol={}
    for path in sorted(source.glob('data/maps/*/map.json')):
        m=json.loads(path.read_text());name=m['name'];by_symbol[m['id']]=name;sources[str(path.relative_to(source))]=hashlib.sha256(path.read_bytes()).hexdigest();objects=[];items=[]
        for i,o in enumerate(m.get('object_events',[]),1):
            point=[o.get('x'),o.get('y')];script=o.get('script','');facts=script_facts(script);gfx=o.get('graphics_id','');kind='item' if gfx=='OBJ_EVENT_GFX_ITEM_BALL' else 'obstacle' if any(s in gfx for s in ('CUT_TREE','ROCK_SMASH','PUSHABLE_BOULDER')) else 'npc'
            entry=dict(local_id=i,point=point,kind=kind,graphics=gfx.removeprefix('OBJ_EVENT_GFX_'),script=script,hide_flag=c.get(o.get('flag')),hide_flag_name=o.get('flag'),movement=o.get('movement_type','').removeprefix('MOVEMENT_TYPE_'),movement_range=[o.get('movement_range_x',0),o.get('movement_range_y',0)],clone=o.get('type')=='clone',facts=facts)
            if kind=='item' and facts['pokemon']:entry['kind']='npc'
            entry['trainers']=[trainers[t] for t in facts['trainers'] if t in trainers]
            objects.append(entry)
            for item in facts['items']:items.append(dict(item,point=point,kind='ground' if kind=='item' else 'gift',local_id=i,hide_flag=entry['hide_flag'],conditions=facts['conditions'],source_script=script))
        for o in m.get('bg_events',[]):
            if o.get('type')=='hidden_item' and o.get('item') in c:items.append(dict(item_id=c[o['item']],quantity=o.get('quantity',1),point=[o['x'],o['y']],kind='hidden',hide_flag=c.get(o.get('flag')),underfoot=o.get('underfoot',False),conditions=[],source_script=None))
        maps[name]=dict(id=m['id'],map_type=m['map_type'],region=m['region_map_section'],requires_flash=m['requires_flash'],allow_running=m.get('allow_running',m['map_type'] in ('MAP_TYPE_TOWN','MAP_TYPE_CITY','MAP_TYPE_ROUTE','MAP_TYPE_UNDERGROUND')),objects=objects,items=items,encounters=[],warps=m.get('warp_events',[]),connections=m.get('connections') or [],sources=[f'https://github.com/pret/{repo}/blob/{pin}/data/maps/{name}/map.json',f'https://github.com/pret/{repo}/blob/{pin}/data/maps/{name}/scripts.inc'])
    wild=json.loads((source/'src/data/wild_encounters.json').read_text())
    for group in wild['wild_encounter_groups']:
        if not group.get('for_maps'):continue
        for row in group.get('encounters',[]):
            other={'FireRed':'LeafGreen','LeafGreen':'FireRed','Ruby':'Sapphire','Sapphire':'Ruby'}[game]
            if other in row['base_label']:continue
            name=by_symbol.get(row['map'])
            if name not in maps:continue
            for field in group['fields']:
                key=field['type'];value=row.get(key)
                if not value:continue
                indexes=field.get('groups') or {key:list(range(len(field['encounter_rates'])))}
                for method,slots in indexes.items():
                    population={}
                    for index in slots:
                        m=value['mons'][index];sp=c.get(m['species']);weight=field['encounter_rates'][index]
                        if not sp:continue
                        p=population.setdefault(sp,dict(species_id=sp,probability=0,min_level=m['min_level'],max_level=m['max_level']))
                        p['probability']+=weight;p['min_level']=min(p['min_level'],m['min_level']);p['max_level']=max(p['max_level'],m['max_level'])
                    maps[name]['encounters'].append(dict(method=method,encounter_rate=value['encounter_rate'],population=list(population.values())))
    return dict(version=1,source_commit=pin,coordinate_system='0-based map tile x,y; moving NPC position is template anchor, not live tracking',source=f'https://github.com/pret/{repo}/tree/'+pin,maps=maps,source_sha256=sources)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('source',type=Path);ap.add_argument('--output',type=Path,default=ROOT/'vendor/reference/location_reference.json');a=ap.parse_args();data=build(a.source);a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(data,ensure_ascii=False,separators=(',',':'))+'\n');print('maps',len(data['maps']),'objects',sum(len(m['objects']) for m in data['maps'].values()),'items',sum(len(m['items']) for m in data['maps'].values()))
