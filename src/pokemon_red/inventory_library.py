"""Detached inventory aggregation: bag, item PC and Pokémon-held items."""
from collections import defaultdict

def holdings(rows,inventory=None,state=None):
    totals=defaultdict(lambda:dict(bag=0,pc=0,party=0,boxes=0,daycare=0,total=0))
    for row in rows:
        kind='pc' if row['pocket']=='pc' else 'bag';totals[row['id']][kind]+=row['quantity'];totals[row['id']]['total']+=row['quantity']
    inventory=inventory or {};state=state or {}
    for key,mons in [('party',state.get('party',inventory.get('party',[]))),('boxes',inventory.get('boxes',[])),('daycare',inventory.get('daycare',[]))]:
        for mon in mons:
            item=mon.get('held_item',0)
            if item and mon.get('checksum_valid',True):totals[item][key]+=1;totals[item]['total']+=1
    return dict(totals)

def library_rows(data,counts):
    return [dict(id=i,name=info['name'],quantity=counts.get(i,{}).get('total',0),pocket='library',pocket_name=info['usage'],slot=i) for i,info in data.items() if info['available_firered'] or counts.get(i,{}).get('total',0)]

def sort_rows(rows,data,field='name',reverse=False):
    return sorted(rows,key=lambda r:(r['quantity'],data[r['id']]['title'].casefold()) if field=='count' else (data[r['id']]['title'].casefold(),r['id']),reverse=reverse)
