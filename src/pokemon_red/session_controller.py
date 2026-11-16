"""One emulator-owner session. No Tk objects or UI callbacks cross this boundary."""
from __future__ import annotations

from .paths import session_paths, resource
from .game_layout import main_flags
from .i18n import t
import fcntl,json,time,threading,traceback
from pathlib import Path
from datetime import datetime
from concurrent.futures import CancelledError,Future
from .engine import Game,BUTTONS,ROM_SHA1,atomic_bytes
from .scheduling import FrameQuantum, next_frame_at
from .settings import Settings
from .slots import Slots
from .history import History
from .diagnostics import Diagnostics
from .file_writer import FileWriter
from .audio import Playback
from .automation import Automation
from .manual_battle import frame_guard as manual_battle_guard
from .speeds import normalize_speed
from .editions import rom_sha1
from .persistence import publish_checkpoint
from .telemetry import read_state,read_map,read_decision,read_training_alert,read_walk_state,symbols

class SessionController:
    VIDEO_INTERVAL=1/30
    MODEL_INTERVAL=.2
    EXPORT_INTERVAL=1.
    def __init__(self,root,*,paused,transport):
        self.paths=session_paths(root);self.folder=self.paths.profile.root;self.transport=transport;self.dirty=True
        self.lock=(self.folder/'Data/.session.lock').open('a')
        try:
            fcntl.flock(self.lock,fcntl.LOCK_EX|fcntl.LOCK_NB);self.game=Game(self.folder)
        except BlockingIOError as error:
            self.lock.close();raise RuntimeError('Сессия уже открыта. Используй существующее окно проекта.') from error
        except BaseException:self.lock.close();raise
        try:
            self.settings=Settings(self.folder);self.slots=Slots(self.folder)
            self.history=History(self.folder,async_writer=True,notify=transport.wake);self.diagnostics=Diagnostics(self.folder)
            self.playback=Playback(self.game.lib)
            self.automation=Automation(self.folder,snapshot=self.bot_snapshot,checkpoint=self.create_slot,
                set_speed=self.set_speed,release=lambda:self.game.advance(0,0),map_reader=lambda name=None:read_map(self.game,name),
                event_sink=self.record_automation_event,inventory_reader=self.inventory_snapshot,walk_reader=lambda:read_walk_state(self.game),
                move_installer=self.install_move_plan,field_installer=self.install_field_action,notify=transport.wake,
                frame_reader=lambda:self.game.frame,metrics=self.diagnostics.measure,speed_installer=self.configure_automatic_speed,game_reader=lambda:self.game)
            from .automatic_speed import AutomaticSpeed
            self.automatic_speed=None;self.speed_control=AutomaticSpeed(self.apply_automatic_speed)
            self.paused=paused;self.closed=False;self.closing=False;self.session_transition=False;self.pending_start=None
            self.safety_notice=None;self.last_shiny_token=None;self.shiny_checked_revision=None
            self.pending_writes=[];self.preparations=[];self.state_cache=None;self.observed_key=None;self.keys=set();self.budget=0.
            self.writer=FileWriter(transport.wake)
            self.settings.save_hook=self.save_preferences
            self.last_tick=self.last_save=time.monotonic();self.last_video=self.last_panel=self.last_export=0.
            self.measured_fps=0.;self.fps_frame=self.game.frame;self.fps_at=self.last_tick
            self.last_saved_frame=self.game.frame;self.save_failed=False;self.last_state=None
            self.last_saved_at=self.game.loaded_from.stat().st_mtime if self.game.loaded_from else None
            self.notice='Восстановлено из резервной копии' if self.game.recovered_from else 'Сессия загружена'
            self.battle_was_active=False;self.battle_token=None;self.video=None;self.video_revision=0
            from .operations import MainOperation
            from .item_delivery import DeliveryManager
            self.operation=MainOperation(self);self.operation.restore_catch_context();self.delivery=DeliveryManager(self)
            self.game.advance(1);self.sync_audio(clear=True);self.refresh_state();self.capture_video()
        except BaseException:
            for name in ('automation','writer','history','playback','game','lock'):
                resource=getattr(self,name,None)
                if resource is not None:
                    try:resource.close()
                    except Exception:pass
            raise

    def save_preferences(self):
        path=self.settings.path;payload=(json.dumps(self.settings.values,ensure_ascii=False,indent=2)+'\n').encode()
        return self.submit_write(lambda:atomic_bytes(path,payload,durable=True),coalesce='settings')

    def save_application_language(self,folder,language):
        settings=Settings(Path(folder));settings.set('language',language,persist=False)
        path=settings.path;payload=(json.dumps(settings.values,ensure_ascii=False,indent=2)+'\n').encode()
        return self.submit_write(lambda:atomic_bytes(path,payload,durable=True),coalesce=('application_language',str(path)))

    def emit(self,kind,**data):self.transport.emit(kind,**data)
    def update_panel(self):self.dirty=True
    def show_panel(self,tab='overview'):self.emit('show_panel',tab=tab)
    def input_status(self):
        return dict(self.transport.ui_metadata,engine=dict(owner_thread_id=threading.get_ident(),generation=self.transport.session_generation,queued_commands=len(self.transport.commands),scheduler=self.transport.work.metrics()),automatic_speed=self.automatic_speed_info,fps=round(self.measured_fps,1),paused=self.paused,
                    speed=0 if self.paused else self.simulation_speed,manual_buttons=sorted(self.keys),bot=self.automation.info(),
                    performance=self.diagnostics.performance(),saving=bool(self.pending_writes))
    def refresh_state(self):
        state=self.session_state()
        if not state.get('telemetry_valid',True) and self.last_state is not None:return
        self.last_state=state;self.observe_state(state)
        self.operation.observe_catch_context(state)
        party_key=tuple(m['uid'] for m in state.get('party',[]));storage=bool(state.get('controls',{}).get('storage'))
        changed=getattr(self,'inventory_epoch',None)!=(self.game,self.game.state_generation)
        dirty=(not getattr(self,'last_inventory',None) or changed
            or party_key!=getattr(self,'inventory_party_key',None) or getattr(self,'inventory_dirty',False) or storage or getattr(self,'storage_was_open',False))
        if dirty and (changed or time.monotonic()-getattr(self,'last_inventory_sync',0)>1):self.inventory_snapshot()
        elif getattr(self,'last_inventory',None):self.last_inventory=dict(self.last_inventory,party=[dict(m,location='party') for m in state.get('party',[])],frame=state['frame'])
        self.storage_was_open=storage;active=state.get('in_battle',False)
        token=tuple(m['uid'] for m in (state.get('battle') or {}).get('enemy_party',[])) if active else None
        if active and (not self.battle_was_active or token!=self.battle_token):self.emit('battle')
        self.battle_was_active=active;self.battle_token=token;self.update_panel()
    def capture_video(self):
        operation=self.operation
        key=(self.game,self.game.revision,operation.last_screen if operation.active else None)
        if key==getattr(self,'_video_key',None):return
        self._video_key=key
        self.video=operation.last_screen if operation.active and operation.last_screen else b'P6\n240 160\n255\n'+self.game.rgb()
        self.video_revision+=1
    def error(self,title,error,*,modal=True):
        self.take_control(focus=False);self.pause(save=False);self.notice=f'{title}: {error}'
        self.diagnostics.record('error',title=title,error=str(error),frame=self.game.frame)
        if modal:self.emit('error',title=title,message=str(error))
        self.update_panel()
    def new_game(self):
        self.take_control(focus=False);candidate=Game(self.folder,resume=False);candidate.advance(120)
        def loaded():self.notice='Новое прохождение начато';self.show_panel('overview')
        return self.replace_game(candidate,'Перед началом новой игры',on_loaded=loaded)
    def close_failed(self,error):
        self.closing=False;self.save_failed=True;self.pause(save=False)
        self.notice='Не удалось сохранить · игра остаётся открытой на паузе'
        self.diagnostics.record('close_save_failed',error=str(error),frame=self.game.frame,traceback=''.join(traceback.format_exception(error))[-6000:])
        self.emit('close_failed',message=str(error))

    def publish_save(self,snapshot,*,backup=False):
        """Writer-only publication; a returned path alone is not a durable ack."""
        warnings=[];data=self.folder/'Data'
        publish_checkpoint(snapshot,data,rom_sha1(self.folder),backup=backup,on_warning=warnings.append)
        snapshot.verify(data)
        for message in warnings:self.diagnostics.record('save_history_warning',message=message,frame=snapshot.frame)
        return warnings
    def finish_close(self):
        self.closed=True
        try:
            self.writer.close()
            try:self.history.close()
            except Exception as error:self.diagnostics.record('journal_close_error',error=str(error))
        finally:
            self.playback.close();self.game.close();self.lock.close()

    def pause(self, _=None, *, save=True):
        self.paused = True
        self.keys.clear()
        self.budget = 0.0
        self.sync_audio(clear=True)
        if save:
            self.save_if_changed()
        self.update_panel()
        return "break"


    @property
    def automatic_speed_info(self):
        control=getattr(self,'speed_control',None)
        return control.info() if control else dict(enabled=False,speed=None,phase='Ручная скорость')


    @property
    def simulation_speed(self):
        override=getattr(self,'automatic_speed',None)
        return override if override is not None else self.settings['speed']


    def configure_automatic_speed(self, enabled, max_speed=12):
        # A bot owns this lease only until stop, error, attention or F9.
        if enabled and (not self.automation.running or getattr(self,'safety_notice',None)):
            return
        self.speed_control.configure(enabled,max_speed=max_speed)


    def apply_automatic_speed(self, speed, phase):
        # Record both sides of the transition so mixed-speed cycles retain their
        # real speed intervals. No preferences or files are written here.
        state=self.session_state()
        self.observe_state(state)
        previous=self.simulation_speed
        if speed is None and self.history.cycle is not None:
            self.history.cycle['automatic_speed_interrupted']=True
        self.automatic_speed=speed
        self.budget=0.0
        self.sync_audio(clear=True)
        self.observe_state(state)
        self.automation.record_event('automatic_speed_changed',
            f"Автоскорость: {self.simulation_speed}× · {phase}",
            dict(previous=previous,speed=self.simulation_speed,phase=phase,automatic=speed is not None))


    def update_automatic_speed(self):
        control=getattr(self,'speed_control',None)
        if not control or not control.enabled or self.paused:return False
        if not self.automation.running:
            control.configure(False);return False
        from .automatic_speed import read_context
        return control.step(self.game.frame,read_context(self.game,self.automation))


    def set_speed(self, speed):
        operation=getattr(self,'operation',None)
        if operation and operation.active:return 'break'
        speed=normalize_speed(speed)
        if speed == 0:
            return self.pause()
        if getattr(self,'safety_notice',None):
            self.notice='Встречен shiny · сначала F9, затем выбери скорость';self.update_panel();return 'break'
        control=getattr(self,'speed_control',None)
        if control and control.enabled:
            control.configure(False)
            self.notice='Ручная скорость до следующего запуска бота'
        if not self.paused and self.settings["speed"] == speed:
            return "break"
        if self.settings["speed"] != speed:
            self.settings.set("speed", speed)
        self.paused = False
        self.keys.clear()
        self.budget = 0.0
        self.last_tick = time.monotonic()
        self.sync_audio(clear=True)
        self.update_panel()
        return "break"


    def sync_audio(self, *, clear=False):
        playback = getattr(self, "playback", None)
        if playback is None:
            return
        if clear:
            self.game.clear_audio()
        playback.configure(active=not self.paused, rate=self.game.audio_rate,
                           speed=self.simulation_speed, enabled=self.settings["sound_enabled"],
                           volume=self.settings["volume"],prevent_app_nap=self.settings['prevent_app_nap'])
        if playback.error:
            self.notice = playback.error


    def submit_write(self, operation, *, coalesce=None, success=None, critical=False, failure=None):
        future = self.writer.submit(operation, coalesce=coalesce)
        self.pending_writes.append(dict(future=future, success=success, failure=failure,
                                       scope=self.automation.session if critical else None))
        return future


    def poll_writes(self):
        pending, self.pending_writes = self.pending_writes, []
        for job in pending:
            if self.closed:
                break
            future = job['future']
            if not future.done():
                self.pending_writes.append(job)
                continue
            try:
                result = future.result()
            except CancelledError:
                if job['scope'] is not None and job['scope'] is self.automation.session:
                    self.automation.stop("Резервное сохранение отменено", status='error')
                    self.error("Ошибка записи", RuntimeError("Резервное сохранение отменено"), modal=False)
                continue
            except Exception as error:
                self.save_failed = True
                if self.automation.running:
                    self.automation.stop("Ошибка сохранения: " + str(error), status='error')
                if job['failure']:
                    job['failure'](error)
                else:
                    self.error("Ошибка записи", error, modal=False)
            else:
                self.diagnostics.measure('file_write', getattr(future, 'write_ms', 0))
                if job['success']:
                    try:
                        job['success'](result)
                    except Exception as error:
                        self.error("Ошибка завершения записи", error, modal=False)


    def critical_save_pending(self):
        session = self.automation.session
        return session is not None and any(job['scope'] is session for job in self.pending_writes)


    def pump_background(self, *, limits=None):
        if self.closed:
            return
        self.poll_writes()
        preparations,self.preparations=self.preparations,[]
        for future,completed in preparations:
            if future.done():completed(future)
            else:self.preparations.append((future,completed))
        if self.closed:
            return
        was_running = self.automation.running
        if limits is None:self.automation.poll()
        else:self.automation.poll(max_requests=limits.request_count,request_budget=limits.request_seconds,
                                  max_events=limits.event_count,event_budget=limits.event_seconds)
        if was_running and not self.automation.running:
            self.notice = self.automation.reason
        # Observe a newly decoded state once, independently of client reads.
        if self.state_cache and self.state_cache[0] == (self.game, self.game.revision):
            self.observe_state(self.state_cache[1])


    def ready_work(self):
        return (any(job['future'].done() for job in self.pending_writes)
                or any(future.done() for future,_ in self.preparations)
                or self.automation.ready_work()
                or self.history.ready_work())

    def frame_blocked(self):
        return (self.closing or self.session_transition or self.critical_save_pending()
                or bool(getattr(self,'operation',None) and self.operation.active))

    def next_deadline(self):
        """Owner-only readiness projection; no pending-operation busy polling."""
        now=time.monotonic()
        due=[self.last_video+self.VIDEO_INTERVAL]
        if not self.closing:
            due.extend((self.last_panel+self.MODEL_INTERVAL,self.last_export+self.EXPORT_INTERVAL))
        blocked=self.frame_blocked()
        if not self.paused and not blocked:
            due.append(next_frame_at(self.last_tick,self.budget,self.simulation_speed))
        if (not self.save_failed and self.settings['autosave_enabled'] and not self.closing
                and not self.session_transition and self.game.frame!=self.last_saved_frame
                and self.game.frame!=getattr(self,'pending_save_frame',None)):
            due.append(max(self.last_save,getattr(self,'last_save_request',self.last_save))+self.settings['autosave_seconds'])
        for service in (self.operation,self.delivery):
            deadline=service.next_poll_at()
            if deadline is not None:due.append(deadline)
        return max(now,min(due))

    def session_state(self):
        key = (self.game, self.game.revision)
        if self.state_cache is None or self.state_cache[0] != key:
            started = time.perf_counter()
            state = read_state(self.game)
            self.state_cache = (key, state)
            self.diagnostics.measure('state_decode', (time.perf_counter() - started) * 1000)
        return self.state_cache[1]


    def observe_state(self, state):
        if (state.get('battle') or {}).get('outcome')==7:self.inventory_dirty=True
        controller = self.automation.info()['script'] if self.automation.running else 'manual'
        key = (self.game, state['frame'], controller, self.paused, self.simulation_speed)
        if key != self.observed_key:
            self.history.observe(state, controller, self.paused, speed=self.simulation_speed)
            self.observed_key = key


    def save(self, *, manual=False):
        if self.closing or self.session_transition:
            return "break"
        try:
            started = time.perf_counter()
            snapshot = self.game.capture_save()
            self.diagnostics.measure('save_capture', (time.perf_counter() - started) * 1000)
            self.last_save_request = time.monotonic()
            self.pending_save_frame = snapshot.frame
            data = self.folder / 'Data'
            def saved(warnings):
                self.last_saved_frame = snapshot.frame
                self.last_save = time.monotonic()
                self.last_saved_at = snapshot.captured_at
                self.save_failed = False
                self.notice = "Сессия сохранена · " + time.strftime("%H:%M:%S", time.localtime(snapshot.captured_at))
                if warnings:self.notice+=' · история сохранений требует внимания'
                self.update_panel()
            self.submit_write(lambda:self.publish_save(snapshot, backup=manual),
                              coalesce=None if manual else 'autosave', success=saved)
        except Exception as error:
            self.save_failed = True
            self.error("Ошибка сохранения", error, modal=False)
        return "break"


    def save_if_changed(self):
        if (not self.save_failed and self.settings["autosave_enabled"]
                and self.game.frame != self.last_saved_frame
                and self.game.frame != getattr(self, 'pending_save_frame', None)):
            self.save()


    def save_if_due(self, now):
        if now - max(self.last_save, getattr(self, 'last_save_request', self.last_save)) >= self.settings["autosave_seconds"]:
            self.save_if_changed()


    def create_slot(self, name, slot_id=None, *, on_saved=None):
        snapshot = self.slots.capture(self.game, name, slot_id)
        def saved(identifier):
            self.notice = f"Слот «{name}» сохранён"
            self.emit('slots_changed',identifier=identifier)
            if on_saved:
                on_saved(identifier)
        return self.submit_write(snapshot.publish, success=saved, critical=True)


    def bot_snapshot(self):
        state = dict(self.session_state())
        from .travel_policy import guard
        state['travel_guard']=guard(self.game,getattr(self.automation,'trainer_policy',None))
        runtime = getattr(self.automation, 'move_runtime', None)
        if runtime:
            state['move_plan'] = runtime.info()
        state["session"] = {"automatic_speed":self.automatic_speed_info,"paused": self.paused, "speed": 0 if self.paused else self.simulation_speed,
                            "automation": self.automation.info(),
                            "recovery": self.automation.recovery_runtime.info() if self.automation.recovery_runtime else None}
        return state


    def install_cut(self,args):
        from .field_actions import CutRuntime
        return CutRuntime(self.game,args,read_state(self.game)['party'])


    def install_field_action(self,args):
        if args.get('action')=='training_item':
            from .training_item import TrainingItemRuntime
            self.create_slot('Lucky Egg')
            return TrainingItemRuntime(self.game,args)
        if args.get('action')!='teleport':return self.install_cut(args)
        from .field_teleport import offer,TeleportRuntime
        state=read_state(self.game);proposal=offer(state,args.get('clinic'),self.folder)
        if not proposal['teleported']:return proposal
        self.create_slot('Перед Teleport к Pokémon Center')
        return TeleportRuntime(self.game,proposal,state)


    def install_move_plan(self,args):
        from .move_plan import compile_plan,require_approval
        from .learning import LearningRuntime
        from .telemetry import read_decision
        inventory=self.inventory_snapshot();uid=args.get('uid');mon=next((m for m in inventory.get('party',[])+inventory.get('boxes',[]) if m['uid']==uid),None)
        if not mon:raise ValueError('Покемон для плана приёмов не найден')
        choice=read_decision(self.game);pending=None
        if choice:
            if mon.get('location')!='party' or choice['party_slot']!=mon['slot']:raise ValueError('Сначала реши запрос другого Pokémon')
            pending=dict(choice,uid=uid)
        goal=args.get('goal')
        if type(goal) is not int:raise ValueError('Некорректный целевой уровень')
        plan=compile_plan(mon,goal,args.get('final_moves'),self.folder,args.get('evolution_mode','natural'),pending)
        require_approval(plan,args.get('approved_plan_id'))
        runtime=LearningRuntime(plan,event=self.automation.record_event,checkpoint=self.create_slot,suspend=self.automation.suspend_input,pending=pending)
        self.automation.move_runtime=runtime;self.automation.record_event('move_plan_registered','План приёмов подтверждён',dict(plan=plan))
        return plan


    def inventory_snapshot(self):
        from .models import read_inventory
        inventory=read_inventory(self.game)
        if inventory.get('ready'):
            from .telemetry import read_field_badges
            inventory['field_badges']=read_field_badges(self.game)
            from .player_inventory import read_player_inventory
            inventory['training_items']=[r for r in read_player_inventory(self.game)['items'] if r['id']==197]
            if self.automation.running:
                # Use the same generation-qualified revision as the preview.
                # A raw flags hash here invalidated every prepared packet at
                # startup even though neither the party nor map had changed.
                inventory['navigation_revision']=self.transport.navigation_version(self)
            self.history.inventory(inventory);self.last_inventory=inventory
            self.inventory_epoch=(self.game,self.game.state_generation)
            self.inventory_party_key=tuple(m['uid'] for m in inventory['party'])
            self.inventory_dirty=False;self.last_inventory_sync=time.monotonic()
        return inventory


    def record_automation_event(self,code,message,details):
        if code=='bot_input':
            # Input traces need exact frames/coordinates, not rich party decode.
            from .telemetry import read_walk_state
            sample=read_walk_state(self.game);run=self.history.run;cycle=self.history.cycle
            context=dict(details,frame=self.game.frame,map=sample.get('map'),position=sample.get('position'),run_id=run.get('id') if run else None,cycle_id=cycle.get('id') if cycle else None)
            self.history.event(code,message,context,durable=False);return
        state=self.session_state()
        self.observe_state(state)
        context=dict(details,frame=state['frame'],map=state.get('map'),position=state.get('position'))
        run=self.history.run;cycle=self.history.cycle
        context.update(run_id=run.get('id') if run else None,cycle_id=cycle.get('id') if cycle else None)
        if code in ('script_error','script_attention','training_timeout','training_blocked','battle_recovery','switch_blocked_menu','escape_failed','move_plan_mismatch','field_action_mismatch','unexpected_dialog','unexpected_scene','field_recovery_failed'):
            context['battle']=state.get('battle');context['controls']=state.get('controls')
            context['resources']=[dict(uid=m['uid'],hp=m['hp'],status_code=m.get('status_code'),moves=[dict(id=a['id'],pp=a['current_pp']) for a in m['moves']]) for m in state.get('party',[])]
        if code!='bot_input':context['party']=[{key:m[key] for key in ('uid','nickname','species','level','hp','max_hp','experience')} for m in state.get('party',[])]
        self.history.event(code,message,context,durable=code!='bot_input')
        self.history.training_event(code,details,state)
        if code=='cycle_complete':return getattr(self.history,'completed_write',None)


    def start_training(self,config):
        """Persist the selected contract off-thread before the existing launch.

        F9/load/close revoke pending_start while the writer owns the file. A
        late disk completion must not launch an obsolete training request.
        """
        from .run_context import RunConfig
        from .grind import validate_start
        from .persistence import atomic_bytes
        validate_start(self.session_state(),self.folder);RunConfig.parse(config)
        if self.automation.running or self.pending_start is not None or self.closing or self.session_transition:
            raise ValueError(t('training.finish_current_action'))
        token=self.pending_start=object();game=self.game;generation=game.state_generation
        payload=json.dumps(config,ensure_ascii=False,indent=2).encode()
        def saved(_):
            if self.pending_start is not token:return
            self.pending_start=None
            if self.closed or self.closing or self.game is not game or game.state_generation!=generation:return
            self.start_bot(resource(self.folder,'Bots/train_xp.py'))
        def failed(error):
            if self.pending_start is token:self.pending_start=None
            self.error(t('training.start_failed'),error,modal=False)
        self.submit_write(lambda:atomic_bytes(self.folder/'Data/training.json',payload,durable=True),success=saved,failure=failed,critical=True)
        self.notice=t('training.saving_plan');self.update_panel()

    def start_party_change(self,config):
        from .party_management import validate_roster,validate_field
        from .persistence import atomic_bytes
        validate_field(self.session_state());validate_roster(self.inventory_snapshot(),config.get('desired'))
        if self.automation.running or self.pending_start is not None or self.operation.active or getattr(self.delivery,'enabled',False) or self.closing or self.session_transition:
            raise ValueError(t('party_edit.busy'))
        from .zones import zone_spec
        hub=zone_spec(self.folder)['hubs'].get(config.get('clinic'))
        if not hub or hub['map']!=config.get('destination') or list(hub['nurse'])!=list(config.get('goal',[])):
            raise ValueError(t('party_edit.review_again'))
        token=self.pending_start=object();game=self.game;generation=game.state_generation
        payload=json.dumps(config,ensure_ascii=False,indent=2).encode()
        def saved(_):
            if self.pending_start is not token:return
            self.pending_start=None
            if self.closed or self.closing or self.game is not game or game.state_generation!=generation:return
            self.start_bot(resource(self.folder,'Bots/change_party.py'))
        def failed(error):
            if self.pending_start is token:self.pending_start=None
            self.error(t('party_edit.start_failed'),error,modal=False)
        self.submit_write(lambda:atomic_bytes(self.folder/'Data/party-change.json',payload,durable=True),success=saved,failure=failed,critical=True)
        self.notice=t('party_edit.starting');self.update_panel()

    def start_bot(self, path):
        try:
            if getattr(self.history.db,'error',None):raise RuntimeError('Журнал недоступен: сохрани игру и перезапусти приложение')
            if getattr(self,'operation',None) and self.operation.active:raise RuntimeError('Сначала останови ловлю / обмен')
            if getattr(self,'safety_notice',None):
                self.notice='Встречен shiny · сначала возьми управление через F9';self.update_panel();return
            if self.automation.running or self.pending_start is not None:
                raise RuntimeError("Сначала останови текущий скрипт")
            if self.closing or self.session_transition:
                raise RuntimeError("Дождись завершения смены сессии")
            path = Path(path)
            if not path.is_file() or path.suffix.lower() != ".py":
                raise ValueError("Выбери Python-скрипт .py")
            token = self.pending_start = object()
            game=self.game;generation=game.state_generation
            name = "Перед ботом · " + path.stem[:30] + " · " + datetime.now().strftime("%H:%M:%S")
            def begin(prepared):
                if self.pending_start is not token or self.closed or self.closing:
                    return
                self.pending_start = None
                if self.game is not game or game.state_generation != generation:return
                self.keys.clear()
                self.game.advance(0, 0)
                self.automation.start(path,prepared=prepared)
                self.automation.log("Резервный слот: " + name)
                if self.paused:
                    self.set_speed(self.settings["speed"])
                self.notice = "Бот: " + path.name
                self.update_panel()
            def saved(_):
                if self.pending_start is not token:return
                from .installation_versions import prepare_bot,submit_preparation
                try:future=submit_preparation(lambda:prepare_bot(self.folder,path),notify=self.transport.wake)
                except Exception as error:
                    self.pending_start=None;self.error('Не удалось запустить скрипт',error);return
                def completed(value):
                    if self.pending_start is not token or self.closed or self.closing:return
                    try:begin(value.result())
                    except Exception as error:
                        self.pending_start=None;self.error('Не удалось запустить скрипт',error)
                self.preparations.append((future,completed))
            self.create_slot(name, on_saved=saved)
            self.notice = "Сохраняем резервный слот перед запуском бота"
            self.update_panel()
        except Exception as error:
            self.pending_start = None
            self.error("Не удалось запустить скрипт", error)


    def take_control(self, _=None, *, focus=True):
        if getattr(self,'delivery',None):self.delivery.interrupt()
        operation=getattr(self,'operation',None)
        if operation and operation.active:
            operation.command('cancel');self.notice='Останавливаем действие и сохраняем прогресс…';return 'break'
        self.pending_start = None  # Also revoke a bot waiting for its checkpoint.
        self.safety_notice = None
        automation = getattr(self, "automation", None)
        if automation and automation.running:
            automation.stop()
            self.notice = "Ручное управление"
            self.update_panel()
        game=getattr(self,'game',None)
        if game:
            self.keys.clear();game.advance(0,0)
        if getattr(self,'paused',False):self.notice='Управление у тебя · игра на паузе · Space — продолжить'
        if focus:self.emit('focus_game')
        self.update_panel()
        return "break"


    def replace_game(self, candidate: Game, reason: str, *, on_loaded=None):
        operation=getattr(self,'operation',None)
        if operation and operation.active:candidate.close();raise RuntimeError('Дождись остановки ловли / обмена')
        self.take_control(focus=False)
        if self.closing or self.session_transition:
            candidate.close()
            raise RuntimeError("Смена сессии уже выполняется")
        self.session_transition = True
        self.keys.clear()
        try:
            completion=Future()
            previous = self.game
            backup = self.slots.capture_backup(previous, reason)
            snapshot = candidate.capture_save()
            data = self.folder / 'Data'
            def publish():
                directory = backup.publish()
                publish_checkpoint(snapshot, data, rom_sha1(self.folder))
                return directory
            def loaded(directory):
                self.history.observe(read_state(previous), paused=self.paused, speed=self.simulation_speed)
                self.history.change_timeline(reason, source=str(candidate.loaded_from or 'new_game'))
                self.game = candidate
                self.playback.close()
                previous.close()
                self.state_cache = None
                self.observed_key = None
                self.save_failed = False
                self.keys.clear()
                self.budget = 0.0
                self.last_saved_frame = snapshot.frame
                self.pending_save_frame = None
                self.last_save = self.last_save_request = self.last_tick = time.monotonic()
                self.fps_frame, self.fps_at = self.game.frame, time.monotonic()
                self.last_saved_at = snapshot.captured_at
                self.session_transition = False
                self.notice = "Предыдущее состояние сохранено в резервных копиях"
                self.sync_audio(clear=True)
                self.capture_video()
                self.refresh_state()
                if on_loaded:
                    on_loaded()
                completion.set_result(directory)
                if getattr(self, 'close_after_transition', False):
                    self.close_after_transition = False
                    self.close()
            def failed(error):
                candidate.close()
                self.session_transition = False
                completion.set_exception(error)
                self.error("Не удалось сменить сессию", error, modal=False)
                if getattr(self, 'close_after_transition', False):
                    self.close_after_transition = False
                    self.close()
            self.submit_write(publish,success=loaded,failure=failed)
            return completion
        except BaseException:
            self.session_transition = False
            candidate.close()
            raise


    def load_slot(self, slot_id):
        self.take_control()
        candidate = self.slots.prepare_load(slot_id)
        name = self.slots.get(slot_id)['name']
        def loaded():
            self.notice = f"Загружен слот «{name}»"
            self.update_panel()
        future=self.replace_game(candidate, "Перед загрузкой другого слота", on_loaded=loaded)
        self.notice = "Загружаем слот · сохраняем предыдущую сессию"
        return future


    def load_backup(self, directory):
        self.take_control()
        candidate = self.slots.prepare_backup(directory)
        def loaded():
            self.notice = "Резервная копия восстановлена"
            self.update_panel()
        future=self.replace_game(candidate, "Перед восстановлением резервной копии", on_loaded=loaded)
        self.notice = "Восстанавливаем резервную копию"
        return future


    def check_training_decision(self):
        if not self.automation.running or self.automation.safety_profile!='training':return False
        from .field_recovery import poison_notification,PoisonRecovery,RecoveryMismatch
        recovery=getattr(self.automation,'recovery_runtime',None)
        if recovery is not None or poison_notification(self.game):
            if recovery is None:
                self.automation.suspend_input('field_recovery')
                recovery=PoisonRecovery(self.game)
                self.automation.recovery_runtime=recovery
                self.automation.record_event('field_recovery_started','Обморок от яда вне боя: закрываем игровое уведомление',dict(kind='poison_faint'))
            try:
                if recovery.poll(self.game):
                    self.automation.recovery_runtime=None;self.automation.release()
                    self.automation.record_event('field_recovery_complete','Уведомление закрыто: проверяем команду и необходимость лечения',dict(kind='poison_faint',pokemon=recovery.fainted))
                return False
            except RecoveryMismatch as error:
                reason='Восстановление после обморока остановлено: '+str(error)
                self.automation.record_event('field_recovery_failed',reason);self.automation.stop(reason,status='attention');self.notice=reason;return True
        field=self.automation.field_runtime
        if field:
            from .field_actions import FieldMismatch
            try:
                if field.poll(self.game):
                    self.automation.field_runtime=None;request=self.automation.field_request;self.automation.field_request=None;self.automation.release()
                    if getattr(field,'action','cut')=='training_item':
                        request.reply(field.result);self.automation.record_event('training_item_equipped','Lucky Egg',field.result)
                    elif getattr(field,'action','cut')=='teleport':
                        from .field_teleport import REASONS
                        result=field.result();message='Teleport: прибытие к нужному Center подтверждено' if result['teleported'] else REASONS.get(result['reason'],result['reason'])+' · возвращаемся пешком'
                        self.automation.record_event('field_action_complete' if result['teleported'] else 'field_teleport_skipped',message,dict(result,action='teleport'));request.reply(result)
                    else:
                        self.automation.record_event('field_action_complete','Дерево срублено: путь открыт',dict(map=field.map,local_id=field.local_id,point=field.point,pokemon_uid=field.provider));request.reply(dict(removed=True))
                return False
            except FieldMismatch as error:
                name='Lucky Egg' if getattr(field,'action','cut')=='training_item' else 'Teleport' if getattr(field,'action','cut')=='teleport' else 'Cut';reason=name+' остановлен: '+str(error)+'. Управление у тебя.'
                self.automation.record_event('field_action_mismatch',reason,dict(action=name,phase=getattr(field,'phase',None)));self.automation.stop(reason,status='attention');self.create_slot(name+' · требуется внимание');self.notice=reason;self.show_panel('automation');return True
        alert=read_training_alert(self.game,self.automation.interaction,getattr(self.automation,'trainer_policy',None))
        if alert:
            code=alert.pop('code');reason=alert.pop('message');self.automation.record_event(code,reason,alert);self.automation.stop(reason,status='attention');self.create_slot('Прокачка · событие требует внимания');self.notice=reason;self.show_panel('automation');return True
        choice=read_decision(self.game)
        runtime=getattr(self.automation,'move_runtime',None)
        if runtime:
            from .move_plan import PlanMismatch
            try:runtime.poll(self.game,choice)
            except PlanMismatch as error:
                reason='План приёмов не совпал: '+str(error)+'. Управление у тебя.'
                self.automation.record_event('move_plan_mismatch',reason,dict(plan_id=runtime.plan['id'],index=runtime.tracker.index));self.automation.stop(reason,status='attention');self.create_slot('Прокачка · план приёмов не совпал');self.notice=reason;self.show_panel('automation');return True
            if choice and runtime.owns_input:return False
        if not runtime:
            from .telemetry import read_learning_control
            if read_learning_control(self.game)['evo']:
                reason='Нужно решение по эволюции. Управление у тебя.'
                self.automation.record_event('evolution_choice_required',reason);self.automation.stop(reason,status='attention');self.create_slot('Прокачка · выбор эволюции');self.notice=reason;self.show_panel('automation');return True
        if not choice:return False
        from .catalog import move
        state=self.bot_snapshot()
        mon=next((m for m in state['party'] if m['slot']==choice['party_slot']),{})
        reason=f"Нужен твой выбор: {mon.get('nickname','Pokémon')} хочет выучить {move(choice['move_id'],self.folder).get('name','приём')}. Выбери замену в окне игры."
        self.automation.record_event('move_choice_required',reason,dict(choice,pokemon_uid=mon.get('uid'),pokemon=mon.get('nickname'),current_moves=[m['name'] for m in mon.get('moves',[])]))
        self.automation.stop(reason,status='attention')
        self.create_slot('Прокачка · выбор нового приёма')
        self.notice=reason
        self.show_panel('automation')
        return True


    def check_shiny_encounter(self):
        # Rarity is a search filter, not an interruption or capture override.
        # Keep this hook for callers; no per-frame shiny RAM polling is needed.
        return False


    def tick(self, *, quantum=None):
        if self.closed:
            return
        started = time.perf_counter()
        try:
            if getattr(self,'history',None) is not None:
                try:self.history.check_health()
                except Exception:
                    self.paused=True;self.keys.clear();self.game.advance(0,0);self.automation.stop('Ошибка записи журнала',status='error');raise
            if getattr(self,'operation',None):self.operation.poll()
            if getattr(self,'delivery',None):self.delivery.poll()
            now = time.monotonic()
            elapsed = min(0.1, now - self.last_tick)
            self.last_tick = now
            blocked = self.frame_blocked()
            if not self.paused and not blocked:
                self.budget = min(self.budget + elapsed * 59.7275 * self.simulation_speed, 60)
                frames = int(self.budget)
                executed = 0
                manual = sum(BUTTONS[key] for key in self.keys)
                # One complete guarded frame precedes cooperative ordinary-work yield.
                quantum = quantum or FrameQuantum.bounded()
                for _ in range(frames):
                    if self.transport.consume_interrupt(self):break
                    if self.check_shiny_encounter():break
                    if manual_battle_guard(self):break
                    if self.automation.running:
                        if self.check_training_decision() or self.critical_save_pending():
                            break
                        if self.update_automatic_speed():break
                        mask = self.automation.next_mask(manual)
                        if self.transport.consume_interrupt(self):break
                        self.game.advance(1, mask)
                        executed += 1
                        self.automation.after_frame(self.game.frame)
                        if self.check_training_decision():
                            break
                    else:
                        if self.transport.consume_interrupt(self):break
                        self.game.advance(1, sum(BUTTONS[key] for key in self.keys))
                        executed += 1
                    self.transport.after_frame(self)
                    if manual_battle_guard(self):break
                    if self.check_shiny_encounter():break
                    if self.critical_save_pending() or quantum.should_yield():
                        break
                self.budget = max(0.0, self.budget-executed)
                if executed:
                    self.sync_audio()
                    if self.playback.handle:self.playback.write(self.game.read_audio())
                    else:self.game.clear_audio()
            elif blocked:
                self.budget = 0.0  # No catch-up burst after a checkpoint barrier.
            if now - self.last_video >= self.VIDEO_INTERVAL:
                self.capture_video()
                self.last_video = now
            if now - self.last_panel >= self.MODEL_INTERVAL and not self.closing:
                self.refresh_state()
                self.last_panel = now
            if now - self.last_export >= self.EXPORT_INTERVAL and not self.closing:
                self.measured_fps=(self.game.frame-self.fps_frame)/max(.001,now-self.fps_at)
                self.fps_frame,self.fps_at=self.game.frame,now
                exported = dict(self.last_state, automation=self.automation.info(),session=self.input_status())
                data = (json.dumps(exported, ensure_ascii=False, indent=2) + "\n").encode()
                path = self.folder / "Data/telemetry.json"
                self.submit_write(lambda:atomic_bytes(path, data), coalesce='telemetry')
                self.last_export = now
            self.save_if_due(now)
        except Exception as error:
            self.error("Ошибка сессии", error, modal=False)
        finally:
            self.diagnostics.measure('tick', (time.perf_counter() - started) * 1000, frame=self.game.frame)


    def close(self):
        if getattr(self,'delivery',None):self.delivery.interrupt()
        operation=getattr(self,'operation',None)
        if operation and operation.active:
            operation.command('cancel');self.close_after_operation=True;return
        if self.closed or self.closing:
            return
        if self.session_transition:
            self.close_after_transition = True
            return
        self.pending_start = None
        self.automation.close()
        self.closing = True
        self.keys.clear()
        self.game.advance(0, 0)
        self.budget = 0
        self.notice = "Сохраняем игру перед закрытием"
        self.update_panel()
        try:
            snapshot = self.game.capture_save()
            data = self.folder / 'Data'
            settings_path = self.settings.path
            settings_bytes = (json.dumps(self.settings.values, ensure_ascii=False, indent=2) + "\n").encode()
            def publish():
                self.publish_save(snapshot,backup=True)
                atomic_bytes(settings_path, settings_bytes, durable=True)
            self.submit_write(publish, success=lambda _:self.finish_close(), failure=self.close_failed)
        except Exception as error:
            self.close_failed(error)


    def toggle_pause(self, _=None):
        operation=getattr(self,'operation',None)
        if operation and operation.active:operation.command('pause');return 'break'
        if self.paused:
            control=getattr(self,'speed_control',None)
            if control and control.enabled and not getattr(self,'safety_notice',None):
                self.paused=False;self.keys.clear();self.budget=0.0;self.last_tick=time.monotonic()
                self.sync_audio(clear=True);self.update_panel()
            else:self.set_speed(self.settings['speed'])
        else:
            self.pause()
        return "break"

