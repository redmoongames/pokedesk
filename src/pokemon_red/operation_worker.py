"""Owns detached main/donor cores; publishes results, never writes Main Data."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import hashlib,json,time,traceback,signal,fcntl,os
from pokemon_red.engine import Game
from pokemon_red.telemetry import read_state
from pokemon_red.acquisition import write_json,read_json
from pokemon_red.acquisition_play import JobPaused,AcquisitionAttention
from pokemon_red.persistence import atomic_bytes,SaveSnapshot
from pokemon_red.operations import clone_session
from pokemon_red.journey import Journey
from pokemon_red.trade import perform_trade
from pokemon_red.models import read_inventory
from collections import Counter

class Cancelled(Exception):pass
class Worker:
    def __init__(self,job):
        self.job=Path(job).resolve();self.spec=read_json(self.job/'operation.json');project=Path(self.spec['project']);self.project=(project if project.is_absolute() else self.job/project).resolve()
        if self.job.parent!=self.project/'Sessions/operations':raise ValueError('Некорректная папка операции')
        self.parent_pid=os.getppid();self.prologue=None;self.accept_best=False;self.best_seen=False;self.selected_candidate=None
        self.status=read_json(self.job/'status.json',{});self.game=None;self.pause=False;self.cancel=False;self.next_beat=0;self.config=self.spec['config'];self.pacer=None;self.caught_at=None
        if self.spec['kind']=='encounter' or self.spec['kind']=='local' and self.config.get('schema_version')==2:
            from pokemon_red.worker_pacing import FramePacer
            self.pacer=FramePacer(self.config.get('max_auto_speed',12))
    def reset_pacing(self):
        if self.pacer:
            from pokemon_red.worker_pacing import FramePacer
            self.pacer=FramePacer(self.config.get('max_auto_speed',12))
    def update(self,**kw):self.status.update(kw,updated_at=time.time());write_json(self.job/'status.json',self.status)
    def event(self,code,details):
        with (self.job/'events.jsonl').open('a') as f:f.write(json.dumps(dict(time=time.time(),code=code,details=details),ensure_ascii=False)+'\n')
    def heartbeat(self):
        if os.getppid()!=getattr(self,'parent_pid',os.getppid()):self.cancel=True
        if self.pacer and self.game:self.pacer.step(self.game.frame,generation=self.game.state_generation)
        if self.spec['kind']=='encounter' and self.game and self.caught_at is None:
            from pokemon_red.telemetry import symbols
            if self.game.read8(symbols(self.game.root)['gBattleOutcome'])==7:self.caught_at=time.time()
        if time.monotonic()<self.next_beat:return
        self.next_beat=time.monotonic()+.12
        command=read_json(self.job/'command.json',{}).get('command');self.pause|=command=='pause';self.cancel|=command=='cancel'
        if command=='use_best' and self.spec['kind'] in ('prologue','local') and not self.best_seen:self.accept_best=True;self.best_seen=True;self.selected_candidate=read_json(self.job/'command.json',{}).get('candidate_sha')
        if (self.cancel or self.pause) and self.spec['kind']=='encounter':
            request=read_json(self.job/'command.json',{}).get('requested_at',time.time())
            if self.caught_at is None or request<=self.caught_at:raise Cancelled()
        if (self.cancel or self.pause) and self.spec['kind']=='trade':raise Cancelled()
        if self.cancel and self.spec['kind'] in ('local','prologue'):raise JobPaused()
        if self.game:
            atomic_bytes(self.job/'screen.ppm',getattr(self,'search_preview',None) or b'P6\n240 160\n255\n'+self.game.rgb())
            self.status.update(speed_limit=self.pacer.maximum if self.pacer else None,frame=self.game.frame,pause_pending=self.pause or self.cancel,updated_at=time.time());write_json(self.job/'status.json',self.status)
    def safe_point(self):
        self.heartbeat()
        if getattr(self,'accept_best',False) and (self.spec['kind']=='local' or self.prologue and self.prologue.progress['phase']=='search'):raise JobPaused()
        if self.pause or self.cancel:
            if self.spec['kind']=='encounter':
                request=read_json(self.job/'command.json',{}).get('requested_at',time.time())
                if self.caught_at is not None and request>self.caught_at:return
                raise Cancelled()
            raise JobPaused()
    def publish(self,mon=None):
        self.game.advance(0,0)
        self.game.save_to(self.job/'main/Data')
        write_json(self.job/'result.json',dict(pokemon=mon,prologue=self.prologue.progress if self.prologue else None,main_hashes={n:hashlib.sha256((self.job/'main/Data'/n).read_bytes()).hexdigest() for n in ['FireRed.state','FireRed.sav']}))
    def recovered_catch(self):
        expected=getattr(self,'verified_catch',None)
        if not expected:return None
        inventory=read_inventory(self.game)
        actual=next((m for m in inventory['party']+inventory['boxes'] if m['uid']==expected['uid']),None)
        keys=('uid','species_id','personality','ivs','level','shiny')
        return actual if actual and actual.get('checksum_valid') and all(actual.get(k)==expected.get(k) for k in keys) else None
    def run(self):
        donor_lock=None
        signal.signal(signal.SIGTERM,lambda *_:setattr(self,'cancel',True))
        try:
            with Game(self.job/'main') as game:
                self.game=game;p=Journey(game,self)
                try:
                    if self.spec['kind']=='prologue':
                        from pokemon_red.prologue import Prologue
                        from pokemon_red.i18n import set_locale,t
                        set_locale(self.config.get('_locale','en'))
                        self.prologue=Prologue(p,self.config,self.config.get('_progress'))
                        self.accept_best=bool(self.config.get('_use_best'));self.best_seen=self.accept_best;self.selected_candidate=self.config.get('_candidate_sha')
                        mon=self.prologue.run();self.publish(mon);self.update(status='ready',stage=t('prologue.ready'),pokemon=mon,prologue=self.prologue.progress)
                    elif self.spec['kind']=='encounter':
                        from pokemon_red.encounter_capture import run
                        mon=run(p);self.next_beat=0;self.safe_point();self.publish(mon)
                        result=read_json(self.job/'result.json');result.update(verified=True,caught_at=self.caught_at);write_json(self.job/'result.json',result)
                        self.update(status='ready',stage='Пойман '+mon['species']+' · управление у тебя',pokemon=mon)
                    elif self.spec['kind']=='local':
                        if self.config.get('_saved_candidate'):
                            from pokemon_red.wild_search_history import catch_saved
                            from pokemon_red.i18n import set_locale
                            set_locale(self.config.get('_locale','en'))
                            mon=catch_saved(p,self.config['_saved_candidate'],self.project)
                        elif self.config.get('schema_version')==2:
                            from pokemon_red.wild_search import search
                            from pokemon_red.i18n import set_locale
                            set_locale(self.config.get('_locale','en'))
                            mon=search(p,self.config)
                        else:mon=p.hunt(self.config.get('species_id',0),self.config.get('shiny',False),self.config.get('route'))
                        p.save_game();self.publish(mon);self.update(status='ready',stage='Пойман '+mon['species']+' · управление у тебя',pokemon=mon)
                    else:
                        donor_id=self.config['donor_job']
                        if not isinstance(donor_id,str) or len(donor_id)!=32 or any(c not in '0123456789abcdef' for c in donor_id):raise ValueError('Некорректный донор')
                        donor=self.project/'Sessions/acquisition'/donor_id;state=read_json(donor/'status.json',{})
                        if state.get('status')!='ready' or not state.get('transfer_ready'):raise ValueError('Донор ещё не готов или уже перенесён')
                        donor_lock=(donor/'Data/.session.lock').open('a');fcntl.flock(donor_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                        donor_before=hashlib.sha256((donor/'Data/FireRed.state').read_bytes()).hexdigest()
                        snap=SaveSnapshot((donor/'Data/FireRed.state').read_bytes(),(donor/'Data/FireRed.sav').read_bytes(),0,time.time());clone_session(self.project,self.job/'donor',snap)
                        base_inventory=read_inventory(game);original=Counter(m['uid'] for m in base_inventory['party']+base_inventory['boxes'])
                        self.update(stage='Идём в ближайший Pokémon Center');hub=p.center()
                        give=self.config.get('give_uid')
                        if not give:
                            route=self.config.get('catch_route') or ('Route1' if hub['map'].startswith('Viridian') else self.config.get('origin_map'))
                            if route not in __import__('pokemon_red.catalog',fromlist=['catalog']).catalog(game.root)['routes']:route='Route1'
                            for _ in range(5):
                                mon=p.hunt(0,False,route)
                                if not mon['shiny']:break
                                self.event('extra_shiny_preserved',dict(pokemon=mon));p.persist()
                            else:raise AcquisitionAttention('Найдены Shiny: сохранены; для обмена нужен обычный Pokémon')
                            give=mon['uid'];self.update(stage='Pokémon для обмена пойман · готовим команду',give_uid=give)
                            p.center()
                        p.ensure_party(give);p.heal();p.save_game()
                        with Game(self.job/'donor') as other:
                            donor_target=read_json(donor/'result.json')['uid']
                            mon=perform_trade(game,other,give,donor_target,self)
                            other.save_to(self.job/'donor/Data');self.publish(mon)
                        final_inventory=read_inventory(game);final=Counter(m['uid'] for m in final_inventory['party']+final_inventory['boxes']);expected=original.copy()
                        if expected[give]:expected[give]-=1
                        if any(final[uid]<count for uid,count in expected.items()):raise AcquisitionAttention('Не подтверждена сохранность прежних Pokémon; основная игра не заменена')
                        self.event('original_roster_preserved',dict(original=dict(original),final=dict(final)))
                        result=read_json(self.job/'result.json');result.update(donor=str(donor),donor_before_sha256=donor_before,donor_hashes={n:hashlib.sha256((self.job/'donor/Data'/n).read_bytes()).hexdigest() for n in ['FireRed.state','FireRed.sav']},give_uid=give);write_json(self.job/'result.json',result)
                        self.update(status='ready',stage='Реальный обмен завершён · '+mon['species']+' получен',pokemon=mon)
                except JobPaused:
                    if self.spec['kind']=='local':
                        if self.config.get('_saved_candidate'):
                            from pokemon_red.wild_search_history import expected_candidate
                            mon=expected_candidate(game,self.config['_saved_candidate'],self.project)
                        else:mon=self.recovered_catch()
                        if mon:
                            from pokemon_red.i18n import t
                            self.publish(mon);self.update(status='ready',stage=t('capture.saved_caught_paused'),pokemon=mon);return 0
                    self.publish()
                    if self.spec['kind']=='prologue':
                        from pokemon_red.i18n import t
                        self.update(status='paused',stage=t('prologue.paused'),prologue=self.prologue.progress if self.prologue else {})
                    else:
                        from pokemon_red.i18n import t
                        self.update(status='cancelled' if self.cancel else 'paused',stage=t('capture.search_paused'))
                except Cancelled:self.update(status='cancelled',stage='Автопоимка выключена · исходная встреча восстановлена' if self.spec['kind']=='encounter' else 'Обмен отменён · обе исходные стороны сохранены')
                except Exception as error:
                    traceback.print_exc()
                    if self.spec['kind'] in ('local','prologue'):self.publish()
                    else:game.save_to(self.job/'attention-main')
                    self.update(status='attention',stage=str(error),error_type=type(error).__name__)
        finally:
            if donor_lock:donor_lock.close()
        return 0
if __name__=='__main__':
    from pokemon_red.installation_versions import validate_worker
    validate_worker(Path(sys.argv[1]))
    job=Path(sys.argv[1])
    if read_json(job/'operation.json',{}).get('kind')=='delivery_source':
        from pokemon_red.item_source_worker import SourceWorker
        raise SystemExit(SourceWorker(job).run())
    if read_json(job/'operation.json',{}).get('kind')=='delivery':
        from pokemon_red.item_delivery_worker import DeliveryWorker
        raise SystemExit(DeliveryWorker(job).run())
    raise SystemExit(Worker(job).run())
