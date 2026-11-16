"""One reversible courier round trip in private emulator cores, using buttons."""

from .paths import resource
from pathlib import Path
import hashlib
import signal
import time
import traceback
from .acquisition import read_json,write_json
from .acquisition_play import Player,AcquisitionAttention
from .engine import Game
from .journey import Journey
from .models import read_inventory
from .operations import clone_session
from .persistence import SaveSnapshot,atomic_bytes
from .player_inventory import read_player_inventory
from .item_delivery import (ITEM_ID,DONOR_UID,checked_id,queue_folder,verify_template,
                            capacity_error,quantity,eligible_couriers,product)

class DeliveryCancelled(Exception):pass

def open_party(player):
    player.tap('START',wait=80)
    for _ in range(40):
        s=player.state();c=s['controls']
        if 'Task_StartMenuHandleInput' not in player.tasks(s):player.advance(12);continue
        if 1 not in c['start_order']:raise AcquisitionAttention('В меню нет команды Pokémon')
        target=c['start_order'].index(1)
        if c['start_cursor']==target:player.tap('A',wait=100);return
        player.tap('UP' if c['start_cursor']>target else 'DOWN',wait=30)
    raise AcquisitionAttention('Не открылось меню команды')

def take_item(player,uid,item_id=ITEM_ID):
    mon=next((m for m in player.state()['party'] if m['uid']==uid),None)
    if not mon or mon['held_item']!=item_id:raise AcquisitionAttention('Курьер не держит ожидаемый предмет')
    before=quantity(read_player_inventory(player.g),item_id)
    open_party(player)
    target=mon['slot']-1
    for _ in range(30):
        s=player.state();c=s['controls']
        if 'Task_HandleChooseMonInput' not in player.tasks(s):player.advance(12);continue
        if c['party_cursor']==target:player.tap('A',wait=90);break
        current=c['party_cursor']
        player.tap('RIGHT' if current==0 else 'LEFT' if target==0 else 'DOWN' if current<target else 'UP',wait=30)
    else:raise AcquisitionAttention('Не выбран курьер для снятия предмета')
    for _ in range(30):
        c=player.state()['controls'];actions=c.get('party_actions',[])
        if 3 not in actions:raise AcquisitionAttention('Нет действия Item у выбранного Pokémon')
        target=actions.index(3)
        if c['menu_cursor']==target:player.tap('A',wait=60);break
        player.tap('UP' if c['menu_cursor']>target else 'DOWN',wait=30)
    else:raise AcquisitionAttention('Не открылось меню предмета')
    c=player.state()['controls']
    # The verified FireRed ACTIONS_ITEM list is Give / Take / Cancel.
    if c.get('party_actions')!=[4,5,9]:raise AcquisitionAttention('Неожиданное меню Give / Take')
    for _ in range(12):
        cursor=player.state()['controls']['menu_cursor']
        if cursor==1:player.tap('A',wait=90);break
        player.tap('DOWN' if cursor<1 else 'UP',wait=30)
    else:raise AcquisitionAttention('Не выбран Take')
    player.tap('A',wait=80);player.settle(button='B')
    after=next(m for m in player.state()['party'] if m['uid']==uid)
    if after['held_item'] or quantity(read_player_inventory(player.g),item_id)!=before+1:
        raise AcquisitionAttention('Не подтверждено снятие '+product(item_id)['name']+' в сумку')

def item_totals(inv):
    result={}
    for r in inv['items']:
        key=(r['pocket'],r['id']);result[key]=result.get(key,0)+r['quantity']
    return result

def verify_round_trip(before,after,bag_before,bag_after,courier_uid,item_id=ITEM_ID):
    if [m['uid'] for m in before['party']]!=[m['uid'] for m in after['party']]:raise AcquisitionAttention('Не восстановлен порядок отряда')
    for key in ('boxes','daycare'):
        a={(m.get('box'),m.get('box_slot'),m['uid']) for m in before.get(key,[])}
        b={(m.get('box'),m.get('box_slot'),m['uid']) for m in after.get(key,[])}
        if a!=b:raise AcquisitionAttention('Изменилось содержимое PC')
    for a,b in zip(before['party'],after['party']):
        if not b['checksum_valid']:raise AcquisitionAttention('Повреждены данные вернувшегося Pokémon')
        for field in ('uid','species_id','level','experience','ivs','evs','held_item','hp','max_hp','status_code'):
            if a.get(field)!=b.get(field):raise AcquisitionAttention('Изменились данные Pokémon: '+field)
        if [(m['id'],m['current_pp']) for m in a['moves']]!=[(m['id'],m['current_pp']) for m in b['moves']]:
            raise AcquisitionAttention('Изменились приёмы или PP')
    info=product(item_id);key=(info['pocket'],item_id)
    expected=item_totals(bag_before);expected[key]=expected.get(key,0)+1
    # The first TM automatically creates a TM Case through the game's AddBagItem.
    if 289<=item_id<=338 and ('key',364) not in expected:expected[('key',364)]=1
    if expected!=item_totals(bag_after):raise AcquisitionAttention('Инвентарь отличается от ожидаемого результата')

def return_to_clinic(player):
    """Return via the game's validated Teleport landing, including late Kanto."""
    import json,re
    from .telemetry import maps,read_map
    from .field_teleport import TeleportRuntime,OUTDOOR_TYPES
    from .field_tools import knows
    state=player.state();root=player.g.root
    if state['map']['name'].endswith('_PokemonCenter_1F'):return
    field=state.get('field_teleport') or {};landing=field.get('landing');c=state['controls']
    provider=next((m for m in state['party'] if knows(m,100)),None)
    if provider and landing and field.get('map_type') in OUTDOOR_TYPES and not state['in_battle'] and c['callback']=='CB2_Overworld' and not c['field_locked'] and not c['moving']:
        names={'MAP_'+re.sub(r'(?<=[a-z])(?=[A-Z])','_',n).upper():n for n in maps(root).values()}
        records=json.loads((resource(root,'vendor/reference/heal_locations.json')).read_text())['heal_locations']
        record=next((r for r in records if names.get(r['map'])==landing['map'] and [r['x'],r['y']]==landing['point'] and names.get(r['respawn_map'],'').endswith('_PokemonCenter_1F')),None)
        if record:
            proposal=dict(pokemon_uid=provider['uid'],clinic=record['id'],destination=landing)
            runtime=TeleportRuntime(player.g,proposal,state)
            while not runtime.poll(player.g):player.advance(1,runtime.mask)
            if runtime.result()['teleported']:
                center=names[record['respawn_map']];position=player.state()['position'];x,y=position['x'],position['y'];grid=read_map(player.g)
                if not any(w['x']==x and w['y']==y-1 and w['destination']==center for w in grid.get('warps',[])):raise AcquisitionAttention('У точки Teleport не подтверждён вход в Center')
                player.transition('UP',center);player.settle(button='B');return
    player.center()

class DeliveryWorker:
    def __init__(self,job):
        self.job=Path(job).resolve();self.spec=read_json(self.job/'operation.json',{});project=Path(self.spec['project']);self.project=(project if project.is_absolute() else self.job/project).resolve()
        if self.job.parent!=self.project/'Sessions/operations' or self.spec.get('kind') not in ('delivery','delivery_source'):raise ValueError('Некорректная операция доставки')
        self.config=self.spec['config'];checked_id(self.config['delivery_job']);self.game=None;self.status={};self.next_beat=0;self.cancel=False;self.pause=False
    def update(self,**kw):
        self.status.update(kw,updated_at=time.time());write_json(self.job/'status.json',self.status)
    def phase(self,phase,stage):
        self.update(status='running',phase=phase,stage=stage)
        write_json(self.job/'progress.json',dict(phase=phase,stage=stage,updated_at=time.time()))
    def event(self,code,details):
        with (self.job/'events.jsonl').open('a') as f:
            import json
            f.write(json.dumps(dict(code=code,time=time.time(),details=details),ensure_ascii=False)+'\n')
    def heartbeat(self):
        now=time.monotonic()
        if now<self.next_beat:return
        self.next_beat=now+.2
        command=read_json(self.job/'command.json',{}).get('command')
        self.cancel|=command=='cancel';self.pause|=command=='pause'
        if self.cancel:raise DeliveryCancelled()
        if self.game:
            atomic_bytes(self.job/'screen.ppm',b'P6\n240 160\n255\n'+self.game.rgb())
            self.status.update(frame=self.game.frame,updated_at=now,pause_pending=self.pause)
            write_json(self.job/'status.json',self.status)
    def safe_point(self):self.heartbeat()
    def run(self):
        signal.signal(signal.SIGTERM,lambda *_:setattr(self,'cancel',True))
        signal.signal(signal.SIGINT,lambda *_:setattr(self,'cancel',True))
        started=time.monotonic()
        try:
            row=read_json(queue_folder(self.project,self.config['delivery_job'])/'job.json',{})
            if row.get('delivered',0)+1!=self.config['sequence'] or row.get('courier_uid')!=self.config['courier_uid']:
                raise AcquisitionAttention('Изменилось задание очереди')
            item_id=self.config.get('item_id',ITEM_ID);info=product(item_id,self.project);donor_uid=info['donor_uid']
            if item_id!=row.get('item_id',ITEM_ID):raise AcquisitionAttention('Изменился предмет задания')
            template=verify_template(self.project,item_id)
            with Game(self.job/'main') as main:
                self.game=main;p=Journey(main,self);initial=read_inventory(main)
                courier=self.config['courier_uid']
                if courier not in {m['uid'] for m in eligible_couriers(initial['party'],self.project,item_id)}:
                    raise AcquisitionAttention('Курьер должен оставаться в отряде, без предмета, Shiny и эволюции при обмене')
                if len(initial['party'])<2:raise AcquisitionAttention('Нужны минимум два Pokémon в отряде')
                if any(m['uid']==donor_uid for m in initial['party']+initial['boxes']):raise AcquisitionAttention('Донорский курьер уже находится в основной игре')
                error=capacity_error(read_player_inventory(main),item_id)
                if error:raise AcquisitionAttention(error)
                self.phase('preparing','Идём в Pokémon Center · готовим курьера')
                s=p.state()
                if not s['map']['name'].endswith('_PokemonCenter_1F'):return_to_clinic(p)
                elif s['in_battle'] or s['controls']['field_locked']:raise AcquisitionAttention('Сначала закончи диалог или бой')
                if [m['uid'] for m in p.state()['party']]!=[m['uid'] for m in initial['party']]:raise AcquisitionAttention('По дороге изменился порядок отряда')
                p.advance(self.config.get('retry_attempt',0)*17)
                p.save_game();before=read_inventory(main);bag_before=read_player_inventory(main)
                snap=SaveSnapshot((template/'FireRed.state').read_bytes(),(template/'FireRed.sav').read_bytes(),0,time.time())
                from .item_sources import clone_donor
                clone_donor(self.project,template,self.job/'donor')
                with Game(self.job/'donor') as donor:
                    donor_before=[m['uid'] for m in Player(donor,self).state()['party']]
                    self.phase('forward','Передаём '+info['name']+' · первый обмен')
                    received=__import__('pokemon_red.trade',fromlist=['perform_trade']).perform_trade(main,donor,courier,donor_uid,self)
                    if received['held_item']!=item_id:raise AcquisitionAttention('Курьер прибыл без '+info['name'])
                    self.phase('take','Перекладываем '+info['name']+' в сумку')
                    take_item(p,donor_uid,item_id)
                    self.phase('return','Возвращаем обоих курьеров · второй обмен')
                    __import__('pokemon_red.trade',fromlist=['perform_trade']).perform_trade(main,donor,donor_uid,courier,self)
                    donor_after=Player(donor,self).state()['party']
                    if [m['uid'] for m in donor_after]!=donor_before or any(m['held_item'] for m in donor_after):raise AcquisitionAttention('Не подтверждён возврат пустого донорского курьера')
                    donor.save_to(self.job/'donor/Data')
                self.phase('verify','Проверяем предмет и возвращённый отряд')
                after=read_inventory(main);bag_after=read_player_inventory(main)
                verify_round_trip(before,after,bag_before,bag_after,courier,item_id)
                p.save_game();main.save_to(self.job/'main/Data')
                result=dict(delivery_job=row['id'],sequence=self.config['sequence'],item_id=item_id,
                            quantity_before=quantity(bag_before,item_id),quantity_after=quantity(bag_after,item_id),courier_uid=courier,donor_uid=donor_uid,
                            seconds=time.monotonic()-started,main_hashes={n:hashlib.sha256((self.job/'main/Data'/n).read_bytes()).hexdigest() for n in ('FireRed.state','FireRed.sav')},
                            verified=True,party_uids=[m['uid'] for m in after['party']])
                write_json(self.job/'result.json',result)
                self.update(status='ready',phase='verified',stage=f"{info['name']} доставлен · курьеры возвращены · {row['delivered']+1}/{row['amount']}")
        except DeliveryCancelled:
            self.update(status='cancelled',stage='Незавершённая пара отменена · основное сохранение не заменено')
        except Exception as error:
            traceback.print_exc();self.update(status='attention',stage=str(error),error_type=type(error).__name__,retryable=any(t in str(error) for t in ('синхронизация GBA link cable','Не удалось пройти по комнате обмена')))
        return 0
