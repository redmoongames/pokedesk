"""Pure derived encounter reference: exact weights, HP ranges and type matchups."""
VERSION='encounter-profiles-v1'

def enrich_routes(data,routes):
    chart={(a,b):m for a,b,m in data['effectiveness']}
    for key,route in routes.items():
        average=reward=0.;maximum=0
        for row in route['population']:
            info=data['species'][str(row['species_id'])];types=list(dict.fromkeys(info['type_ids']));hp={}
            for raw in row['levels']:
                level=int(raw);base=info['base_stats']['hp']
                hp[raw]=dict(min=1 if info['national_id']==292 else 2*base*level//100+level+10,max=1 if info['national_id']==292 else (2*base+31)*level//100+level+10)
            multipliers={}
            for typ in range(18):
                if typ==9:continue
                factor=1.
                for defense in types:factor*=chart.get((typ,defense),1)
                multipliers[str(typ)]=factor
            row.update(types=types,hp_by_level=hp,hp_min=min(v['min'] for v in hp.values()),hp_max=max(v['max'] for v in hp.values()),weaknesses={k:v for k,v in multipliers.items() if v>1},resistances={k:v for k,v in multipliers.items() if 0<v<1},immunities=[int(k) for k,v in multipliers.items() if v==0])
            for raw,weight in row['levels'].items():
                level=int(raw);average+=level*weight/100;reward+=(info['base_xp']*level//7)*weight/100;maximum=max(maximum,level)
        route['difficulty']=dict(mean_level=average,max_level=maximum,expected_wild_xp=reward)
        route['profile_version']=VERSION
    for rank,(key,route) in enumerate(sorted(routes.items(),key=lambda p:(p[1]['difficulty']['mean_level'],p[1]['difficulty']['expected_wild_xp'],p[1]['difficulty']['max_level'],p[0])),1):route['difficulty']['rank']=rank
    return routes
