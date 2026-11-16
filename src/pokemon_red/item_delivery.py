"""Durable item queue. Credits follow publication of a complete round trip."""
from pathlib import Path
from contextlib import contextmanager
import fcntl
import hashlib
import time
import uuid
from .acquisition import read_json, write_json
from .editions import rom_sha1
from .persistence import publish_checkpoint

ITEM_ID = 14  # Default keeps existing Antidote jobs and receipts readable.
DONOR_UID = '964ff2df:74f77be2'
TEMPLATE = 'templates/items/antidote-v1/ready'
PRODUCTS = {
    14: dict(title='Антидот · Antidote', name='Antidote', pocket='items', capacity=42,
             hint='Снимает отравление', source='Viridian Forest · проверенный донор', template=TEMPLATE, donor_uid=DONOR_UID),
    4: dict(title='Покебол · Poké Ball', name='Poké Ball', pocket='balls', capacity=13,
            hint='Обычный покебол для ловли Pokémon', source='Подарок профессора Oak · проверенный донор',
            template='templates/items/pokeball-v1/ready', donor_uid=DONOR_UID),
    332: dict(title='TM44 · Rest', name='TM44 (Rest)', pocket='tmhm', capacity=58,
              hint='Обучает Rest · TM расходуется при обучении', source='TM44 после S.S. Anne · проверенный донор',
              template='templates/items/tm44-v1/ready', donor_uid=DONOR_UID),
}
FINISHED = {'done', 'cancelled'}

def product(item_id=ITEM_ID,project=None):
    if type(item_id) is not int:raise ValueError('Некорректный предмет')
    if project:
        from .item_sources import provider,generic_product
        source=provider(project,item_id)
        if source:return dict(generic_product(item_id,project),**{k:v for k,v in source.items() if k!='directory'})
    if item_id in PRODUCTS:return PRODUCTS[item_id]
    from .item_sources import generic_product
    return generic_product(item_id,project)

def checked_id(value):
    if not isinstance(value,str) or len(value)!=32 or any(c not in '0123456789abcdef' for c in value):
        raise ValueError('Некорректный идентификатор доставки')
    return value

def queue_folder(project, job_id):
    return Path(project)/'Sessions/item-delivery'/checked_id(job_id)

def file_hashes(folder):
    return {n:hashlib.sha256((Path(folder)/n).read_bytes()).hexdigest() if (Path(folder)/n).is_file() else None
            for n in ('FireRed.state','FireRed.sav')}

def verify_template(project,item_id=ITEM_ID):
    info=product(item_id,project)
    from .item_sources import provider,library_root
    source=provider(project,item_id)
    folder=source['directory'] if source else library_root(project)/info.get('template','missing-source')
    manifest=read_json(folder/'manifest.json',{})
    if set(manifest)!={'FireRed.state','FireRed.sav','metadata.json'}:
        raise ValueError('Не установлен проверенный шаблон '+info['name'])
    for name,digest in manifest.items():
        if not (folder/name).is_file() or hashlib.sha256((folder/name).read_bytes()).hexdigest()!=digest:
            raise ValueError('Повреждён шаблон '+info['name']+': '+name)
    meta=read_json(folder/'metadata.json',{})
    state=meta.get('state',{})
    carrier=next((m for m in state.get('party',[]) if m.get('uid')==info['donor_uid']),None)
    if not carrier or carrier.get('held_item')!=item_id or len(state.get('party',[]))<2 or not state.get('map',{}).get('name','').endswith('_PokemonCenter_1F'):
        raise ValueError('Шаблон донора не готов к передаче '+info['name'])
    return folder

def quantity(inventory, item=ITEM_ID):
    pocket=product(item)['pocket']
    return sum(r['quantity'] for r in inventory.get('items',[]) if r['id']==item and r['pocket']==pocket)

def capacity_error(inventory,item=ITEM_ID):
    info=product(item)
    if not inventory.get('ready'):return 'Инвентарь ещё не загружен'
    if quantity(inventory,item)>=999:return 'В сумке уже 999 '+info['name']
    rows=[r for r in inventory['items'] if r['pocket']==info['pocket']]
    exists=any(r['id']==item for r in rows)
    if not exists and len(rows)>=info['capacity']:return 'Карман заполнен: освободи одно место'
    if 289<=item<=338 and not exists and not any(r['id']==364 and r['pocket']=='key' for r in inventory['items']):
        if sum(r['pocket']=='key' for r in inventory['items'])>=30:return 'Освободи место для TM Case в ключевых предметах'
    return None

def eligible_couriers(party, project,item_id=None):
    from .catalog import catalog
    data=catalog(Path(project))['species']
    from .item_sources import courier_conflicts
    excluded=courier_conflicts(project,item_id) if item_id is not None else set()
    result=[]
    for m in party:
        sp=data.get(str(m.get('species_id')), {})
        if (not m.get('checksum_valid') or m.get('is_egg') or m.get('shiny') or m.get('held_item')
                or m.get('uid') in excluded or m.get('uid')==DONOR_UID or any(e['method'] in (5,6) for e in sp.get('evolutions',[]))):continue
        result.append(m)
    return sorted(result,key=lambda m:(m.get('species_id') not in (16,19,21),m.get('level',100),m['slot']))

@contextmanager
def job_lock(folder):
    with (folder/'.queue.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        yield

def change_job(project,job_id,**changes):
    folder=queue_folder(project,job_id)
    with job_lock(folder):
        row=read_json(folder/'job.json',{})
        if not row:raise ValueError('Задание не найдено')
        row.update(changes,updated_at=time.time());write_json(folder/'job.json',row);return row

def apply_receipt(project, receipt):
    """Idempotent after crash between receipt fsync and queue-state fsync."""
    with job_lock(queue_folder(project,receipt['delivery_job'])):
        return _apply_receipt(project,receipt)

def _apply_receipt(project, receipt):
    folder=queue_folder(project,receipt['delivery_job']);state=read_json(folder/'job.json')
    if not state:raise ValueError('Задание доставки не найдено')
    if receipt.get('item_id',ITEM_ID)!=state.get('item_id',ITEM_ID):raise ValueError('Предмет квитанции не совпадает с заданием')
    seq=receipt['sequence'];delivered=state.get('delivered',0)
    if delivered>=seq:
        old=read_json(folder/'receipts'/f'{seq:06d}.json',{})
        if old.get('operation_id')!=receipt['operation_id']:raise ValueError('Конфликт квитанций доставки')
        return state
    if delivered!=seq-1:raise ValueError('Нарушен порядок квитанций доставки')
    (folder/'receipts').mkdir(exist_ok=True)
    old=read_json(folder/'receipts'/f'{seq:06d}.json',{})
    if old and old.get('operation_id')!=receipt['operation_id']:raise ValueError('Конфликт квитанций доставки')
    write_json(folder/'receipts'/f'{seq:06d}.json',receipt)
    state.update(retry_attempt=0,delivered=seq,last_operation=receipt['operation_id'],updated_at=time.time(),last_cycle_seconds=receipt.get('seconds'),recovery_pending=False)
    done=seq>=state['amount'] or state['mode']=='target' and receipt['quantity_after']>=state['requested']
    state['status']='done' if done else 'cancelled' if state.get('cancel_requested') else 'paused' if state.get('pause_requested') else 'running'
    state['stage']='Доставлено' if done else 'Доставка отменена' if state['status']=='cancelled' else 'На паузе' if state['status']=='paused' else 'Предмет доставлен · курьеры возвращены'
    write_json(folder/'job.json',state)
    return state

def commit_delivery(project, operation, result, snapshot):
    """Write-ahead journal makes the game + queue publication recoverable."""
    operation=Path(operation);job_id=checked_id(result['delivery_job'])
    state=read_json(queue_folder(project,job_id)/'job.json',{})
    if state.get('delivered',0)+1!=result['sequence']:raise ValueError('Изменился прогресс очереди')
    receipt={k:result[k] for k in ('delivery_job','sequence','quantity_before','quantity_after','courier_uid','donor_uid','seconds')}
    item=result.get('item_id',ITEM_ID);product(item)
    if item!=state.get('item_id',ITEM_ID):raise ValueError('Изменился предмет доставки')
    receipt.update(operation_id=operation.name,item_id=item)
    expected={'FireRed.state':hashlib.sha256(snapshot.state).hexdigest(),'FireRed.sav':hashlib.sha256(snapshot.sram).hexdigest()}
    journal=dict(status='committing',receipt=receipt,before=file_hashes(Path(project)/'Data'),after=expected)
    write_json(operation/'commit.json',journal)
    publish_checkpoint(snapshot,Path(project)/'Data',rom_sha1(project),backup=True)
    apply_receipt(project,receipt)
    write_json(operation/'commit.json',dict(journal,status='committed'))

def recover_commits(project):
    """Never guess or replay an uncertain transaction into a different save."""
    project=Path(project)
    for operation in (project/'Sessions/operations').glob('*'):
        spec=read_json(operation/'operation.json',{})
        if spec.get('kind')!='delivery':continue
        journal=read_json(operation/'commit.json',{})
        receipt=journal.get('receipt')
        if not receipt or journal.get('status') not in ('committing','committed'):continue
        folder=queue_folder(project,receipt['delivery_job']);state=read_json(folder/'job.json',{})
        if not state:continue
        if journal['status']=='committed' or file_hashes(project/'Data')==journal['after']:
            apply_receipt(project,receipt)
            write_json(operation/'commit.json',dict(journal,status='committed'))
        elif file_hashes(project/'Data')==journal['before']:
            write_json(operation/'commit.json',dict(journal,status='rolled_back'))
        else:
            state.update(status='attention',stage='Сохранение отличается от журнала доставки. Нужна проверка резервной копии.',recovery_pending=True)
            write_json(folder/'job.json',state)

class DeliveryManager:
    POLL_INTERVAL=.25
    def next_poll_at(self):
        return self.last_poll+self.POLL_INTERVAL if self.enabled or self.current is not None else None

    def __init__(self,monitor):
        self.m=monitor;self.project=Path(monitor.folder);self.current=None;self.last_poll=0;self.enabled=False
        recover_commits(self.project)
        for row in self.jobs():
            if row['status'] in ('running','pausing'):
                row.update(status='paused',pause_requested=True,stage='Очередь сохранена · нажми «Продолжить»');self.save(row)
    def save(self,row):
        row['updated_at']=time.time();write_json(queue_folder(self.project,row['id'])/'job.json',row)
    def jobs(self):
        rows=[read_json(p) for p in (self.project/'Sessions/item-delivery').glob('*/job.json')]
        return sorted((r for r in rows if r),key=lambda r:r['created_at'])
    def get(self,job_id):
        row=read_json(queue_folder(self.project,job_id)/'job.json')
        if not row:raise ValueError('Задание не найдено')
        return row
    def enqueue(self,requested,mode,courier_uid,item_id=ITEM_ID):
        from .player_inventory import read_player_inventory
        if type(requested) is not int or not 1<=requested<=999:raise ValueError('Количество должно быть от 1 до 999')
        if mode not in ('add','target'):raise ValueError('Некорректный режим доставки')
        info=product(item_id,self.project)
        try:verify_template(self.project,item_id)
        except ValueError:
            from .item_sources import can_prepare
            from .player_inventory import read_player_inventory
            reason=can_prepare(self.project,item_id,read_player_inventory(self.m.game))
            if reason:raise ValueError(reason)
        s=self.m.last_state or {};couriers=eligible_couriers(s.get('party',[]),self.project,item_id)
        if len(s.get('party',[]))<2:raise ValueError('Для обмена нужны минимум два Pokémon в отряде')
        if courier_uid not in {c['uid'] for c in couriers}:raise ValueError('Выбери обычного курьера из отряда без предмета и эволюции при обмене')
        inv=read_player_inventory(self.m.game);error=capacity_error(inv,item_id)
        if error:raise ValueError(error)
        current=quantity(inv,item_id);amount=requested if mode=='add' else max(0,requested-current)
        if not amount:raise ValueError('Нужное количество '+info['name']+' уже есть в сумке')
        if current+amount>999:raise ValueError('После доставки получится больше 999 '+info['name'])
        job_id=uuid.uuid4().hex;folder=queue_folder(self.project,job_id);folder.mkdir(parents=True)
        row=dict(schema_version=1,id=job_id,item_id=item_id,mode=mode,requested=requested,amount=amount,delivered=0,
                 courier_uid=courier_uid,status='queued',stage='В очереди',pause_requested=False,cancel_requested=False,created_at=time.time())
        self.save(row);return job_id
    def start(self,job_id):
        if self.current and self.current['job_id']==job_id and self.m.operation.active:raise ValueError('Это задание уже выполняется')
        if not self.m.operation.active:recover_commits(self.project)
        row=self.get(job_id)
        if row.get('recovery_pending'):raise ValueError(row['stage'])
        if row['status'] in FINISHED:raise ValueError('Это задание уже завершено')
        change_job(self.project,job_id,status='queued',pause_requested=False,cancel_requested=False,stage='Ожидает освобождения основной игры');self.enabled=True
    def pause(self,job_id,cancel=False):
        row=self.get(job_id)
        if row['status'] in FINISHED:return
        active=self.current and self.current['job_id']==job_id and self.m.operation.active
        change_job(self.project,job_id,pause_requested=True,cancel_requested=cancel,status='pausing' if active else 'cancelled' if cancel else 'paused',stage='Завершаем возврат курьеров' if active and not cancel else 'Отменяем незавершённую пару' if active else 'Отменено' if cancel else 'На паузе')
        if active:self.m.operation.command('cancel' if cancel else 'pause')
    def interrupt(self):
        self.enabled=False
        if self.current:
            row=self.get(self.current['job_id'])
            if row['status'] not in FINISHED:change_job(self.project,row['id'],pause_requested=True,status='paused',stage='Управление возвращается · незавершённая пара не засчитывается')
    def poll(self):
        if time.monotonic()-self.last_poll<self.POLL_INTERVAL:return
        self.last_poll=time.monotonic();operation=self.m.operation
        if self.current:
            if operation.active:return
            result=operation.result or {};row=self.get(self.current['job_id'])
            if self.current.get('source') and result.get('operation_id')==self.current['operation_id'] and result.get('status')=='ready':
                verify_template(self.project,row.get('item_id',ITEM_ID));row.update(status='cancelled' if row.get('cancel_requested') else 'paused' if row.get('pause_requested') else 'queued',stage='Подготовка завершена · автосбор отменён' if row.get('cancel_requested') else 'Донор готов · на паузе' if row.get('pause_requested') else 'Донор готов · начинаем автосбор');self.save(row)
            elif result.get('operation_id')==self.current['operation_id'] and not result.get('applied'):
                retry=row.get('retry_attempt',0)
                if result.get('retryable') and retry<3 and not row.get('pause_requested') and not row.get('cancel_requested'):
                    row.update(status='queued',retry_attempt=retry+1,stage=f'Повторяем незавершённый обмен · попытка {retry+2}/4');self.save(row);self.current=None;return
                status='cancelled' if row.get('cancel_requested') else 'paused' if result.get('status')=='cancelled' else 'attention'
                row.update(status=status,pause_requested=True,stage=result.get('stage','Доставка прервана'));self.save(row)
                self.enabled=False
            elif row['status']=='pausing':
                row.update(status='cancelled' if row.get('cancel_requested') else 'paused',stage='Отменено' if row.get('cancel_requested') else 'На паузе');self.save(row)
            self.current=None
        if not self.enabled or operation.active or self.m.closing or self.m.session_transition or self.m.pending_start or self.m.critical_save_pending():return
        if self.m.automation.running:return
        row=next((r for r in self.jobs() if r['status'] in ('queued','running') and not r.get('pause_requested')),None)
        if not row:self.enabled=False;return
        try:
            from .player_inventory import read_player_inventory
            item=row.get('item_id',ITEM_ID);product(item,self.project)
            inv=read_player_inventory(self.m.game)
            if row['mode']=='target' and quantity(inv,item)>=row['requested']:
                row.update(status='done',stage='Нужное количество уже в сумке');self.save(row);return
            error=capacity_error(inv,item)
            if error:raise ValueError(error)
            try:verify_template(self.project,item)
            except ValueError:
                from .item_sources import can_prepare
                reason=can_prepare(self.project,item,inv)
                if reason:raise ValueError(reason)
                row.update(status='running',stage='Готовим копию прохождения для автосбора');self.save(row)
                operation_id=operation.begin('delivery_source',dict(delivery_job=row['id'],courier_uid=row['courier_uid'],item_id=item))
                self.current=dict(job_id=row['id'],operation_id=operation_id,source=True);return
            row.update(status='running',stage=f"Доставка {row['delivered']+1} из {row['amount']}");self.save(row)
            operation_id=operation.begin('delivery',dict(delivery_job=row['id'],sequence=row['delivered']+1,courier_uid=row['courier_uid'],item_id=item,retry_attempt=row.get('retry_attempt',0)))
            self.current=dict(job_id=row['id'],operation_id=operation_id)
        except Exception as error:
            row.update(status='attention',stage=str(error),pause_requested=True);self.save(row)
