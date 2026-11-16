"""One-shot hunt planning against a detached map snapshot and live save flags."""
from .capture_target import candidates,hunt_atlas
from .hunt_spots import hunting_spot
from .navigation import Navigator
from .travel import strongest
from .locations import location_name
from .field_tools import knows
from .capture import capture_kit,SLEEP_MOVES
from .path_cache import map_key
from .water_hunting import RODS,water_spot
from .editions import edition


def choose_hunter(inventory):
    owned=inventory.get('party',[])+inventory.get('boxes',[])
    valid=[m for m in owned if m.get('checksum_valid') and not m.get('is_egg') and m.get('hp',0)>0]
    return min(valid,key=lambda m:(not capture_kit(m),not any(knows(m,n) for n in SLEEP_MOVES),m['species_id']!=3,m.get('location')!='party',-m['level'],m['uid']),default=None)

class HuntPlanner:
    def __init__(self,trainer,inventory):
        self.t=trainer;self.root=trainer.root;self.inventory=inventory;self.nav=Navigator(trainer).configure_tools(inventory);self.hunter=choose_hunter(inventory);self.maps={};self.geometry={};self.retreats={}
    def row(self,entry):
        name=entry['map'];row=dict(entry,label=location_name(name),available=False)
        method=entry['method'];water=method in (*RODS,'water_mons')
        if method!='land_mons' and not water:return dict(row,reason='Этот способ встреч пока не автоматизирован: '+method)
        if water and edition(self.root).family=='hoenn':return dict(row,reason='Рыбалка и Surf для автопоимки пока проверены только в FireRed / LeafGreen')
        if method in RODS and not any(r['id']==RODS[method] and r['pocket']=='key' for r in self.inventory.get('bag',{}).get('items',[])):return dict(row,reason='Нет нужной удочки в сумке: '+{'old_rod':'Old Rod','good_rod':'Good Rod','super_rod':'Super Rod'}[method])
        surf=None
        if method=='water_mons':
            surf=next((m for m in self.inventory['party']+self.inventory.get('boxes',[]) if knows(m,57)),None)
            if 5 not in self.inventory.get('field_badges',[]):return dict(row,reason='Для Surf нужен Soul Badge — значок Коги')
            if surf is None:return dict(row,reason='Нужен Pokémon с уже выученным Surf; приёмы автоматически не заменяются')
        if name.startswith('SafariZone'):return dict(row,reason='В Safari Zone другой тип боя и правила ловли; нужен отдельный исполнитель')
        reviewed={e[k] for e in self.nav.spec['links'] for k in ('source','destination')}
        if name not in reviewed and (not water or name!=self.t.state()['map']['name']):return dict(row,reason='Для этой карты пока нет проверенных автоматических переходов')
        if not self.hunter:return dict(row,reason='Нет боеспособного Pokémon для ловли')
        state=self.t.state();origin=state['map']['name'];point=(state['position']['x'],state['position']['y']);hunter=self.hunter
        try:
            # Healthy local hunts can go straight to the field. Boxed hunters,
            # trips to other maps or depleted resources are prepared at a PC.
            in_party=hunter['uid'] in {m['uid'] for m in self.inventory['party']}
            sleep=next((a['current_pp'] for a in hunter['moves'] if a['id']==79),None)
            local=origin==name and (surf is None or surf['uid'] in {m['uid'] for m in self.inventory['party']}) and in_party and hunter['hp']>=hunter['max_hp']*.65 and not hunter.get('status_code') and (sleep is None or sleep>=3)
            preferred=[m['uid'] for m in self.inventory['party']]
            escort=strongest(self.inventory['party'])
            if not escort:raise ValueError('В отряде нет боеспособного Pokémon для пути к Center')
            pinned=list(dict.fromkeys([hunter['uid'],escort['uid']]+([surf['uid']] if surf else [])))
            if local:
                nav=self.nav.initial_tools();grid=nav.grid(name);farm=water_spot(grid,point,method) if water else hunting_spot(self.root,grid,point);trip=None;steps=len(farm['path'])
            else:
                nav=self.nav;trip=nav.itinerary(name,pinned=pinned,preferred=preferred)
                entry_point=trip['legs'][-1]['plan']['arrival'] if trip['legs'] else point
                grid=nav.grid(name);farm=water_spot(grid,entry_point,method) if water else hunting_spot(self.root,grid,entry_point);steps=sum(l['plan']['cost'][1] for l in trip['legs'])+len(farm['path'])
            # Prove a retreat from BOTH ends before starting a long rare hunt.
            retreat_key=(name,tuple(farm['shore'])) if water else None
            clinics=self.retreats.get(retreat_key) if retreat_key is not None else None
            if clinics is None:
                clinics=[]
                for clinic,hub in self.nav.spec['hubs'].items():
                    try:
                        out=nav.plan(name,farm['shore'] if water else farm['pair'][0],hub['map'],hub['nurse'],diagnose=False);back=nav.plan(name,farm['shore'] if water else farm['pair'][1],hub['map'],hub['nurse'],diagnose=False)
                    except RuntimeError:continue
                    clinics.append((max(out['cost'],back['cost']),clinic))
                if retreat_key is not None:self.retreats[retreat_key]=clinics
            if not clinics and not (water and local):raise RuntimeError('Не найден проверенный путь из участка охоты в Pokémon Center')
            clinic=min(clinics)[1] if clinics else None
            return dict(row,available=True,reason='',manual_heal=not bool(clinics),surf_uid=surf['uid'] if surf else None,farm=farm,hunter_uid=hunter['uid'],hunter_name=hunter['nickname'],clinic=clinic,steps=steps,local=local,pinned=pinned,preferred=preferred,geometry=map_key(grid))
        except (RuntimeError,ValueError) as error:return dict(row,reason=str(error))
    def choices(self,target):
        found=[]
        for entry in candidates(target,self.root):
            key=(entry['map'],entry['method'])
            if key not in self.geometry:self.geometry[key]=self.row(entry)
            found.append(dict(self.geometry[key],levels=entry['levels'],probability=entry['probability']))
        return sorted(found,key=lambda r:(not r['available'],-r['probability']*r['encounter_rate'],sum(int(lv)*p for lv,p in r['levels'].items())/max(.01,r['probability']),r.get('steps',10**9),r['map'],r['method']))
    def choose(self,target):
        rows=self.choices(target)
        if not rows:raise ValueError('Нет обычных диких встреч этого вида с выбранным уровнем и способом')
        selected=next((r for r in rows if r['available']),None)
        if selected is None:raise ValueError(rows[0]['label']+': '+rows[0]['reason'])
        return selected
