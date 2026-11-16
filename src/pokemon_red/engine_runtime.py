"""Single-owner emulator actor, bounded commands and a latest-value UI mailbox.

Game, Automation, RAM readers and history live on this thread. No Tcl objects
are accepted by its protocol. Takeover is an out-of-band revocation epoch,
checked before every frame and between commands, including at speed saturation.
"""
from collections import deque
from concurrent.futures import Future, CancelledError
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
import queue
import threading
import time
from .scheduling import WorkSignal, RuntimeScheduler
from .runtime_data import DetachedResult, PreparedHistoryExport, InventoryPublisher


@dataclass(frozen=True)
class RuntimeSnapshot:
    sequence: int
    epoch: int
    frame: int
    revision: int
    generation: int
    video_revision: int
    video: bytes | None
    state: dict
    inventory: dict
    status: dict
    history: dict
    operation: dict
    delivery: dict


@dataclass
class Command:
    method: str
    args: tuple
    epoch: int
    future: Future
    generation: int | None = None


SENSITIVE = {'start_training','start_party_change','start_bot','new_game','load_slot','load_backup','operation_begin','delivery_start','manual','battle_auto','battle_capture'}


class EngineRuntime:
    def __init__(self, root, *, paused=True, notify=lambda:None, capacity=128, controller_factory=None):
        self.root=Path(root);self.notify=notify;self.capacity=capacity
        self.work=WorkSignal();self.scheduler=RuntimeScheduler(self.work);self.condition=self.work.condition;self.commands=deque();self.events=queue.Queue(maxsize=64)
        self.epoch=0;self.applied_epoch=0;self.interrupt=None;self.interrupted=threading.Event()
        self.ready=Future();self.finished=Future();self.latest=None;self.sequence=0
        self.ui_metadata={};self.preferences=None;self.preference_version=0;self.applied_preferences_version=0;self.stopping=False;self.accepting=True
        self.controller=None;self.pending=[];self.manual_releases={};self.manual_pressed={}
        self.last_publish=0;self.last_status_key=None;self.session_generation=0;self.game_marker=None
        self.inventory_lease=0.;self.bag={'ready':False,'items':[]};self.daycare=[];self.delivery_rows=[];self.last_inventory_read=0.
        self.navigation_revision=None;self.navigation_lease=0.;self.last_navigation_read=0.
        self.analytics=None;self.inventory_publisher=InventoryPublisher()
        self.thread=threading.Thread(target=self._run,args=(paused,controller_factory),name='pokemon-engine-owner',daemon=True)
        self.thread.start()

    def wake(self):
        self.work.notify()

    def submit(self, method, *args):
        future=Future()
        with self.condition:
            if not self.accepting:
                future.set_exception(RuntimeError('Игровая сессия уже закрывается'));return future
            if len(self.commands)>=self.capacity:
                future.set_exception(RuntimeError('Очередь ядра заполнена'));return future
            self.commands.append(Command(method,args,self.epoch,future));self.work.notify()
        return future

    def take_control(self, *, pause=False, close=False):
        """Nonblocking, never queued behind telemetry, saves or normal RPCs."""
        with self.condition:
            self.epoch+=1;previous=self.interrupt
            self.interrupt=(self.epoch,pause or bool(previous and previous[1]),close or bool(previous and previous[2]));self.interrupted.set()
            if close:self.stopping=True
            self.work.notify();return self.epoch

    def set_preferences(self, patch, *, persist=True):
        with self.condition:
            if not patch and not persist:return self.preference_version
            self.preference_version+=1
            changes=dict(self.preferences[1]) if self.preferences else {}
            changes.update(deepcopy(patch));persist=persist or bool(self.preferences and self.preferences[2]);self.preferences=(self.preference_version,changes,persist)
            self.work.notify();return self.preference_version
    def apply_preferences(self,c,preferences):
        if preferences is None:return
        self.applied_preferences_version,patch,persist=preferences;c.settings.values.update(patch)
        try:
            if persist:c.settings.save()
        except Exception as error:
            c.save_failed=True;c.error('Не удалось сохранить настройки',error)
        c.sync_audio();c.dirty=True

    def emit(self, kind, **data):
        try:self.events.put_nowait((kind,data))
        except queue.Full:
            # The latest snapshot also contains errors, notices and pause state.
            pass
        self.notify()

    def consume_interrupt(self, c):
        if not self.interrupted.is_set():return False
        with self.condition:
            item=self.interrupt;self.interrupt=None;self.interrupted.clear()
            preferences=self.preferences;self.preferences=None
        if item is None:return False
        epoch,pause,close=item
        self.apply_preferences(c,preferences)
        self.manual_releases.clear();self.manual_pressed.clear()
        c.pending_start=None;c.keys.clear();c.game.advance(0,0)
        c.take_control(focus=False)
        if pause:c.pause(save=False)
        c.budget=0.;c.game.advance(0,0)
        self.applied_epoch=epoch
        if close:
            if self.analytics is not None:self.analytics.close()
            c.close()
        c.dirty=True;self.publish(c,force=True)
        return True

    def after_frame(self,c):
        for key,frame in list(self.manual_releases.items()):
            if c.game.frame>=frame:c.keys.discard(key);self.manual_releases.pop(key,None)

    def update_generation(self,c):
        marker=(c.game,c.game.state_generation)
        if marker==self.game_marker:return False
        previous=self.game_marker;self.game_marker=marker;self.session_generation+=1
        self.navigation_revision=None;self.bag={'ready':False,'items':[]};self.daycare=[];self.last_inventory_read=0.
        self.manual_pressed.clear();self.manual_releases.clear();c.keys.clear();c.game.advance(0,0)
        if previous is not None:
            c.last_shiny_token=None;c.shiny_checked_revision=None;c.refresh_state()
        return True
    def navigation_version(self,c):
        from .planning_state import read_world_revision
        self.update_generation(c)
        revision=read_world_revision(c.game)
        return f'{self.session_generation}:{revision}' if revision is not None else None

    def _manual(self,c,button,pressed):
        from .engine import BUTTONS
        if button not in BUTTONS or type(pressed) is not bool:raise ValueError('Некорректный ввод GBA')
        if c.operation.active or c.closing or c.session_transition:return
        if pressed and (c.automation.running or c.pending_start is not None):c.take_control(focus=False)
        if pressed:
            if c.paused:return
            c.keys.add(button);self.manual_pressed[button]=c.game.frame
            self.manual_releases.pop(button,None)
        else:
            frame=self.manual_pressed.pop(button,c.game.frame-1)+1
            if c.game.frame>=frame:c.keys.discard(button)
            else:self.manual_releases[button]=frame
        c.history.event('player_input',button,dict(button=button,pressed=pressed,frame=c.game.frame),durable=False)

    def _dispatch(self,c,method,args):
        from .game_adapters import adapter
        required={'battle_auto':'battle','battle_capture':'capture','operation_begin':'capture','bag':'inventory','inventory':'collection','navigation_revision':'travel','map_snapshot':'travel','location_info':'travel','travel_snapshot':'travel','start_bot':'training','start_training':'training','start_party_change':'training'}
        if method in required:adapter(self.root).require(required[method])
        if method=='manual':return self._manual(c,*args)
        if method=='battle_capture':
            from .encounter_capture import set_enabled
            return set_enabled(c,*args)
        if method=='battle_auto':
            from .manual_battle import set_enabled
            return set_enabled(c,*args)
        if method=='clear_keys':
            c.keys.clear();self.manual_releases.clear();self.manual_pressed.clear();c.game.advance(0,0);return
        if method=='pause':return c.pause(save=args[0] if args else True)
        if method=='toggle_pause':
            if c.operation.active:return c.operation.command('pause')
            if c.paused:
                if c.speed_control.enabled and not c.safety_notice:
                    c.paused=False;c.keys.clear();c.budget=0.;c.last_tick=time.monotonic();c.sync_audio(clear=True)
                else:c.set_speed(c.settings['speed'])
            else:c.pause()
            c.update_panel();return
        if method=='application_language':return c.save_application_language(*args)
        if method=='settings':return None  # Coalesced via the preferences mailbox.
        if method=='inventory':
            self.inventory_lease=time.monotonic()+2
            return DetachedResult(self.inventory_publisher.publish(c.inventory_snapshot(),self.session_generation,self.daycare))
        if method=='bag':
            from .player_inventory import read_player_inventory
            self.inventory_lease=time.monotonic()+2;self.bag=read_player_inventory(c.game);return self.bag
        if method=='planning_end':self.navigation_lease=0.;return
        if method=='navigation_revision':
            from .planning_state import read_world_revision
            self.navigation_lease=time.monotonic()+2;self.navigation_revision=self.navigation_version(c);return self.navigation_revision
        if method=='map_snapshot':
            from .planning_state import read_world_revision,planning_grid,PlanningSnapshotExpired
            from .telemetry import read_map
            name,expected=args
            revision=self.navigation_version(c)
            if expected is not None and revision!=expected:raise PlanningSnapshotExpired('Изменились препятствия; пересчитываем маршрут')
            grid=read_map(c.game,name)
            if grid is None:raise PlanningSnapshotExpired('Карта временно недоступна')
            return planning_grid(grid)
        if method=='location_info':
            from .location_reference import map_info
            from .telemetry import symbols
            from .game_layout import save_block,flags_offset
            sb=save_block(c.game,1)
            flags=c.game.read_bytes(sb+flags_offset(c.game),0x120) if 0x02000000<=sb<0x02040000-0x3d68 else b''
            return map_info(self.root,args[0],lambda n:0<=n//8<len(flags) and bool(flags[n//8]&(1<<(n%8))))
        if method=='travel_snapshot':
            if c.closing or c.session_transition or c.operation.active:raise RuntimeError('Основная игра занята другой операцией')
            return dict(state=c.game.capture_save().state,generation=self.session_generation)
        if method=='history_read':
            name,params=args
            from .history_queries import validate
            validate(name,params)
            return self.history_service().request(name,params,barrier=c.history.query_barrier())
        if method=='history_export':
            return self.history_service().request('export',barrier=c.history.query_barrier(),export_path=Path(args[0]))
        if method=='operation_begin':return c.operation.begin(*args)
        if method=='operation_command':return c.operation.command(*args)
        if method=='prologue_config':return c.operation.prologue_config(*args)
        if method.startswith('delivery_'):return getattr(c.delivery,method[len('delivery_'):])(*args)
        if method=='recover_input':
            attention=c.automation.info()['status'] in ('attention','error')
            if c.paused or attention:c.set_speed(1)
            if attention:c.automation.acknowledge()
            c.notice='Управление у тебя · X = A · Enter = Start';c.update_panel();return
        if method=='error':return c.error(args[0],RuntimeError(args[1]),modal=False)
        if method in ('set_speed','save','create_slot','load_slot','load_backup','new_game','start_bot','start_training','start_party_change'):
            if method=='save':return c.save(manual=args[0] if args else False)
            return getattr(c,method)(*args)
        raise ValueError('Неизвестная команда ядра: '+method)

    def history_service(self):
        # A failed final save can leave the paused session open. Its previously
        # stopped analytics service must be restartable without reopening Game.
        if self.analytics is None or getattr(self.analytics,'closed',False) is True:
            from .analytics import AnalyticsService
            self.analytics=AnalyticsService(self.root)
        return self.analytics

    def _resolve(self,command,result):
        if command.future.done():return
        if command.generation is not None:
            self.update_generation(self.controller)
            if command.generation!=self.session_generation:
                from .i18n import t
                command.future.set_exception(CancelledError(t('history.stale_result')));return
        if isinstance(result,Future):
            self.pending.append((command,result));result.add_done_callback(lambda _:self.wake())
        elif isinstance(result,PreparedHistoryExport):
            from .persistence import atomic_bytes
            self._resolve(command,self.controller.submit_write(lambda:atomic_bytes(result.path,result.payload,durable=True)))
        elif isinstance(result,DetachedResult):command.future.set_result(result.value)
        elif not command.future.done():command.future.set_result(deepcopy(result))

    def _commands(self,c):
        deadline=time.perf_counter()+self.scheduler.limits.command_seconds
        for _ in range(self.scheduler.limits.command_count):
            self.consume_interrupt(c)
            with self.condition:
                if not self.commands:break
                command=self.commands.popleft()
            if command.future.cancelled():continue
            if command.method in SENSITIVE and command.epoch!=self.epoch:
                command.future.set_exception(CancelledError('Управление возвращено игроку'));continue
            try:
                if command.method in ('history_read','history_export','inventory'):
                    self.update_generation(c);command.generation=self.session_generation
                self._resolve(command,self._dispatch(c,command.method,command.args))
            except Exception as error:
                if not command.future.done():command.future.set_exception(error)
            if command.method not in ('history_read','map_snapshot','navigation_revision'):c.dirty=True
            if time.perf_counter()>=deadline:break
        pending,self.pending=self.pending,[]
        for command,future in pending:
            if future.done():
                try:self._resolve(command,future.result())
                except Exception as error:
                    if not command.future.done():command.future.set_exception(error)
            else:self.pending.append((command,future))

    def ready_work(self,c):
        # Owner queries only; producers publish then notify through WorkSignal.
        return (bool(self.commands) or self.interrupted.is_set() or self.preferences is not None
                or any(future.done() for _,future in self.pending) or c.ready_work())

    def publish(self,c,*,force=False):
        changed=self.update_generation(c)
        now=time.monotonic()
        # Video and scalar status are cheap; rich detached models at 5 Hz.
        rich=changed or force or self.latest is None or now-self.last_publish>=.2
        old=self.latest
        status_key=(c.paused,c.closing,c.session_transition,c.notice,c.pending_start is not None,c.automation.log_revision,bool(c.pending_writes),c.operation.active)
        if not rich and old and c.video_revision==old.video_revision and not c.dirty and status_key==self.last_status_key:return
        self.last_status_key=status_key
        if rich:
            self.last_publish=now
            if self.inventory_lease>now and now-self.last_inventory_read>.7:
                from .player_inventory import read_player_inventory
                from .collection import read_daycare
                self.bag=read_player_inventory(c.game);self.daycare=read_daycare(c.game)
                self.delivery_rows=c.delivery.jobs();self.last_inventory_read=now
            if self.navigation_lease>now and now-self.last_navigation_read>.2:
                from .planning_state import read_world_revision
                self.navigation_revision=self.navigation_version(c);self.last_navigation_read=now
            state=deepcopy(c.last_state or c.session_state())
            inventory=self.inventory_publisher.publish(getattr(c,'last_inventory',{}),self.session_generation,self.daycare)
            history=deepcopy(dict(run=c.history.run,cycle=c.history.cycle,revision=c.history.revision,stats_revision=c.history.stats_revision,completed_revision=c.history.completed_revision,
                completed_pending=bool(c.history.completed_write and not c.history.completed_write.done())))
        else:state,inventory,history=old.state,old.inventory,old.history
        operation=dict(progress=deepcopy(getattr(c.operation,'status',{})),active=c.operation.active,speed_limit=getattr(c.operation,'speed_limit',None),job=c.operation.job,kind=getattr(c.operation,'kind',None),result=deepcopy(c.operation.result),catch_context=deepcopy(getattr(c.operation,'catch_context',{})),context_revision=getattr(c.operation,'context_revision',0))
        status=dict(preferences_version=self.applied_preferences_version,owner_thread_id=threading.get_ident(),paused=c.paused,closing=c.closing,closed=c.closed,transition=c.session_transition,notice=c.notice,
            automation=c.automation.info(),logs=list(c.automation.logs),log_revision=c.automation.log_revision,
            safety_notice=deepcopy(c.safety_notice),pending_start=c.pending_start is not None,saving=bool(c.pending_writes),save_failed=c.save_failed,
            last_saved_frame=c.last_saved_frame,last_saved_at=c.last_saved_at,speed=c.simulation_speed,automatic_speed=c.automatic_speed_info,
            fps=c.measured_fps,settings=deepcopy(c.settings.values),performance=c.diagnostics.performance() if rich else old.status.get('performance',{}),bag=deepcopy(self.bag),navigation_revision=self.navigation_revision)
        from .manual_battle import status as battle_auto_status
        status['battle_auto']=battle_auto_status(c,state)
        from .encounter_capture import status as capture_status
        status['battle_capture']=capture_status(c,state)
        delivery=dict(rows=deepcopy(self.delivery_rows),current=deepcopy(c.delivery.current),enabled=c.delivery.enabled)
        self.sequence+=1
        snapshot=RuntimeSnapshot(self.sequence,self.applied_epoch,c.game.frame,c.game.revision,self.session_generation,c.video_revision,c.video,state,inventory,status,history,operation,delivery)
        self.latest=snapshot;c.dirty=False;self.notify()

    def _run(self,paused,factory):
        c=None
        try:
            if factory is None:
                from .session_controller import SessionController
                factory=SessionController
            c=self.controller=factory(self.root,paused=paused,transport=self)
            self.publish(c,force=True);self.ready.set_result(True)
            while not c.closed:
                observed=self.scheduler.begin_turn()
                self.consume_interrupt(c)
                with self.condition:
                    preferences=self.preferences;self.preferences=None
                self.apply_preferences(c,preferences)
                self._commands(c)
                if c.closed:break
                c.pump_background(limits=self.scheduler.limits)
                if c.closed:break
                c.tick(quantum=self.scheduler.frame_quantum(observed,lambda:self.ready_work(c)))
                if c.closed:break
                self.publish(c)
                self.scheduler.wait(observed,c.next_deadline(),lambda:self.ready_work(c))
            if not self.finished.done():self.finished.set_result(True)
        except BaseException as error:
            if not self.ready.done():self.ready.set_exception(error)
            self.emit('fatal',message=str(error))
            if c and not c.closed:
                try:
                    c.automation.close();c.keys.clear();c.game.advance(0,0)
                    snapshot=c.game.capture_save()
                    from .persistence import publish_checkpoint
                    from .editions import rom_sha1
                    c.writer.submit(lambda:publish_checkpoint(snapshot,c.folder/'Data',rom_sha1(c.folder),backup=True)).result()
                    c.finish_close()
                except BaseException:pass
            if not self.finished.done():self.finished.set_exception(error)
        finally:
            if self.analytics is not None:self.analytics.close()
            self.accepting=False
            with self.condition:
                for command in self.commands:
                    if not command.future.done():command.future.set_exception(CancelledError('Сессия закрыта'))
                self.commands.clear()
                for command,_ in self.pending:
                    if not command.future.done():command.future.set_exception(CancelledError('Сессия закрыта'))
                self.pending.clear()
            self.notify()
