"""Prepare a reusable donor from a snapshot; never apply that snapshot to main."""
import hashlib,signal,time,traceback,uuid
from .engine import Game
from .acquisition import read_json,write_json
from .acquisition_play import Player,AcquisitionAttention
from .journey import Journey
from .telemetry import read_state
from .models import read_inventory
from .editions import edition
from .item_delivery import DONOR_UID,verify_template,quantity,eligible_couriers
from .item_delivery_worker import DeliveryWorker,DeliveryCancelled,take_item,return_to_clinic
from .item_sources import library_root,clone_donor,register,can_prepare
from .item_transfer import give_item
from .player_inventory import read_player_inventory
from .trade import perform_trade

class SourceWorker(DeliveryWorker):
    def run(self):
        signal.signal(signal.SIGTERM,lambda *_:setattr(self,'cancel',True));signal.signal(signal.SIGINT,lambda *_:setattr(self,'cancel',True))
        started=time.monotonic()
        try:
            item=self.config['item_id'];courier=self.config['courier_uid']
            with Game(self.job/'main') as main:
                self.game=main;p=Journey(main,self);initial=read_inventory(main);inv=read_player_inventory(main);stock=quantity(inv,item)
                error=can_prepare(self.project,item,inv)
                if error:raise AcquisitionAttention(error)
                if len(initial['party'])<2 or courier not in {m['uid'] for m in eligible_couriers(initial['party'],self.project)}:raise AcquisitionAttention('Нет подходящего курьера в копии прохождения')
                if DONOR_UID in {m['uid'] for m in initial['party']+initial['boxes']}:raise AcquisitionAttention('Курьер подготовки уже есть в коллекции; нужен другой донор')
                self.phase('source','Копия прохождения · готовим отдельного курьера')
                return_to_clinic(p);p.save_game()
                # The seed supplies a distinct Pokémon. Trading two unchanged
                # clones would duplicate UIDs and is deliberately rejected.
                seed=library_root(self.project)/'templates/items/antidote-v1/ready'
                # Verify the legacy seed independently of a user-created provider.
                from .item_delivery import PRODUCTS
                manifest=read_json(seed/'manifest.json',{})
                if set(manifest)!={'FireRed.state','FireRed.sav','metadata.json'} or any(hashlib.sha256((seed/n).read_bytes()).hexdigest()!=h for n,h in manifest.items()):raise AcquisitionAttention('Повреждён исходный донор курьера')
                clone_donor(self.project,seed,self.job/'seed')
                with Game(self.job/'seed') as donor:
                    take_item(Player(donor,self),DONOR_UID,14)
                    perform_trade(main,donor,courier,DONOR_UID,self)
                give_item(p,DONOR_UID,item)
                state=read_state(main)
                if courier in {m['uid'] for m in state['party']} or next(m for m in state['party'] if m['uid']==DONOR_UID)['held_item']!=item:raise AcquisitionAttention('Не подтверждён отдельный донорский курьер')
                self.heartbeat()
                folder=library_root(self.project)/'Sessions/item-sources'/uuid.uuid4().hex/'ready';folder.mkdir(parents=True)
                main.save_to(folder)
                meta=dict(schema_version=1,item_id=item,state=state,game=edition(main.root).id,donor_uid=DONOR_UID,stock=stock,created_at=time.time(),origin_sha256=self.spec['base_state_sha256'],method='Snapshot clone, distinct courier through native link, ordinary Give; no RAM edits')
                write_json(folder/'metadata.json',meta)
                write_json(folder/'manifest.json',{n:hashlib.sha256((folder/n).read_bytes()).hexdigest() for n in ('FireRed.state','FireRed.sav','metadata.json')})
                self.heartbeat()
                register(self.project,item,folder,DONOR_UID,stock,edition(main.root).id)
                verify_template(self.project,item)
                write_json(self.job/'result.json',dict(verified=True,item_id=item,stock=stock,template=str(folder.relative_to(library_root(self.project))),seconds=time.monotonic()-started))
                self.update(status='ready',stage='Донор готов · основное прохождение не менялось')
        except DeliveryCancelled:self.update(status='cancelled',stage='Подготовка донора отменена · основное прохождение не менялось')
        except Exception as error:traceback.print_exc();self.update(status='attention',stage=str(error),error_type=type(error).__name__)
        return 0
