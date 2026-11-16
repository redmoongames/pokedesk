"""Managed bot processes. Only owner-thread poll()/frame callbacks touch mGBA.

Network and stdout threads exchange plain requests/events, never emulator objects.
Each run gets a new loopback port, token and cancellation scope.
"""
from __future__ import annotations

from .paths import session_paths, resource

from collections import deque
from concurrent.futures import Future
from dataclasses import dataclass, field
from datetime import datetime
import json
import os
from pathlib import Path
import queue
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time
import uuid

from .engine import BUTTONS
from .speeds import normalize_speed


@dataclass
class Request:
    session: object
    method: str
    args: dict
    done: threading.Event = field(default_factory=threading.Event)
    response: dict | None = None
    received_at: float = field(default_factory=time.perf_counter)

    def reply(self, result=None, *, error=None, cancelled=False):
        if self.done.is_set():
            return
        self.response = {"ok": error is None, "result": result, "error": error, "cancelled": cancelled}
        self.done.set()


@dataclass
class Session:
    listener: socket.socket
    id: str = field(default_factory=lambda:uuid.uuid4().hex)
    token: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    cancelled: threading.Event = field(default_factory=threading.Event)
    peer: socket.socket | None = None
    finishing: bool = False
    success: bool = True
    completion_reason: str | None = None
    completion_status: str = 'finished'
    error_detail: dict | None = None
    execution: dict | None = None


class Automation:
    def __init__(self, root: Path, *, snapshot, checkpoint, set_speed, release, map_reader=None, event_sink=None, inventory_reader=None,walk_reader=None,move_installer=None,field_installer=None,notify=None,frame_reader=None,metrics=None,speed_installer=None,game_reader=None):
        self.root = Path(root)
        self.snapshot = snapshot
        self.map_reader = map_reader
        self.inventory_reader = inventory_reader
        self.walk_reader=walk_reader
        self.move_installer=move_installer;self.move_runtime=None;self.field_installer=field_installer;self.field_runtime=None;self.field_request=None
        self.recovery_runtime = None
        self.event_sink = event_sink
        self.checkpoint = checkpoint
        self.set_speed = set_speed
        self.speed_installer = speed_installer
        self.game_reader = game_reader
        self.trainer_policy = None
        self.release = release
        self.notify = notify or (lambda: None)
        self.frame_reader = frame_reader or (lambda: self.snapshot()['frame'])
        self.metrics = metrics
        self.pending_writes = []
        self.thread = threading.get_ident()
        self.requests = queue.Queue(maxsize=64)
        self.events = queue.Queue(maxsize=256)
        self.session = self.process = self.action = None
        self.retiring = []
        self.logs = deque(maxlen=200)
        self.log_revision = 0
        self.log_file = None
        self.script = None
        self.status = "idle"
        self.reason = "Скрипт не запущен"
        self.started_at = None
        self.interaction = 'travel'
        self.stage = None
        self.safety_profile='none'

    def _main(self):
        if threading.get_ident() != self.thread:
            raise RuntimeError("Automation controller must run on the emulator thread")

    def suspend_input(self, reason='move_plan'):
        self._main()
        if self.action:self.action['request'].reply(dict(interrupted=reason));self.action=None
        self.release()

    @property
    def running(self):
        return self.session is not None

    def scripts(self):
        folder = resource(self.root,"Bots")
        folder.mkdir(exist_ok=True)
        return sorted(folder.glob("*.py"), key=lambda path: path.name.lower())

    def log(self, message):
        self._main()
        line = datetime.now().strftime("%H:%M:%S") + "  " + str(message)[:2000]
        self.logs.append(line)
        self.log_revision += 1
        if self.log_file:
            self.log_file.write(line + "\n")
            self.log_file.flush()

    def record_event(self,code,message,details=None):
        if code in ('training_stage','cycle_start','preparation_complete','team_assembled'):self.stage=message
        if code not in ('bot_input','training_stage'):details=dict(details or {},stage=self.stage,interaction=self.interaction)
        if code!='bot_input':self.log(message)
        if self.session:details=dict(details or {},automation_session_id=self.session.id)
        if self.event_sink:return self.event_sink(code,message,details or {})

    def info(self):
        action = None
        if self.action:
            action = {"buttons": self.action["buttons"],
                      "frames_left": sum(phase[1] for phase in self.action.get('phases',[])),
                      "goal":list(self.action['walk'].goal) if 'walk' in self.action else None}
        return {"running": self.running, "controller": "bot" if self.running else "manual",
                "status": self.status, "reason": self.reason,
                "script": self.script.name if self.script else None, "action": action, "stage":self.stage}

    def acknowledge(self):
        self._main()
        if not self.running and self.status in ('attention','error'):
            previous=self.reason;self.status='idle';self.reason='Ручное управление';self.stage=None
            self.record_event('attention_acknowledged','Игрок перешёл к ручному управлению',dict(previous_reason=previous))

    def start(self, script: Path, *, prepared=None):
        from .editions import edition,HOENN_NOTICE
        if not edition(self.root).automation:raise RuntimeError(HOENN_NOTICE)
        self._main()
        if self.running:
            raise RuntimeError("Сначала останови текущий скрипт")
        self.interaction='travel'
        self.trainer_policy=None
        self.safety_profile='training' if Path(script).name in ('route1_xp.py','train_xp.py') else 'none'
        self.stage=None
        script = Path(script).resolve()
        if not script.is_file() or script.suffix.lower() != ".py":
            raise ValueError("Выбери существующий Python-файл .py")
        from .installation_versions import prepare_bot,loaded_id
        prepared = prepared or prepare_bot(self.root,script)
        if loaded_id() is not None and prepared.version.id != loaded_id():
            raise ValueError('Bot installation differs from the live session')
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(0.2)
        session = Session(listener,execution=prepared.execution)
        self.session = session
        self.script = script
        self.status, self.reason = "running", "Скрипт управляет игрой"
        self.started_at = time.monotonic()
        self.logs.clear()
        self.log_revision += 1
        folder = self.root / "Data/logs/automation"
        folder.mkdir(parents=True, exist_ok=True)
        try:
            self.log_file = (folder / (datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8] + ".log")).open("w", encoding="utf-8")
            python = prepared.version.python
            if not python.exists():
                python = Path(sys.executable)  # For isolated integration harnesses.
            environment = prepared.version.environment()
            environment.update(POKEMON_BOT_PORT=str(listener.getsockname()[1]),
                               POKEMON_BOT_TOKEN=session.token, POKEMON_PROJECT_DIR=str(self.root),
                               POKEMON_BOT_PARENT_PID=str(os.getpid()),POKEMON_RUN_MANIFEST=str(prepared.job/'execution.json'))
            self.process = subprocess.Popen(
                [str(python), "-I", "-B", "-u", str(prepared.version.worker('bot_runner.py')), str(prepared.script)],
                cwd=self.root, env=environment, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", start_new_session=True)
        except BaseException:
            self.stop("Не удалось запустить скрипт", status="error")
            raise
        threading.Thread(target=self._serve, args=(session,), daemon=True).start()
        threading.Thread(target=self._console, args=(session, self.process), daemon=True).start()
        self.record_event('script_started',"Запущен: " + script.name,{'script':script.name})

    def _event(self, session, kind, message):
        try:
            self.events.put_nowait((session, kind, message))
        except queue.Full:
            pass
        self.notify()

    def _console(self, session, process):
        try:
            with process.stdout:
                while line := process.stdout.readline(4096):
                    self._event(session, "log", line.rstrip())
        except (OSError, ValueError):
            pass

    def _serve(self, session):
        try:
            while not session.cancelled.is_set():
                try:
                    peer, _ = session.listener.accept()
                except socket.timeout:
                    continue
                except OSError:
                    return
                peer.settimeout(0.2)
                peer.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                session.peer = peer
                authenticated = False
                accepted_at = time.monotonic()
                buffer = b""
                try:
                    while not session.cancelled.is_set():
                        try:
                            data = peer.recv(4096)
                        except socket.timeout:
                            if not authenticated and time.monotonic() - accepted_at > 5:
                                break
                            continue
                        if not data:
                            break
                        buffer += data
                        if len(buffer) > 65536:
                            break
                        while b"\n" in buffer and not session.cancelled.is_set():
                            line, buffer = buffer.split(b"\n", 1)
                            packet = json.loads(line)
                            if (not isinstance(packet, dict) or not isinstance(packet.get("token"), str)
                                    or not secrets.compare_digest(packet["token"], session.token)):
                                raise ValueError("Invalid session token")
                            authenticated = True
                            if session.execution is not None and packet.get('execution') != session.execution:
                                raise ValueError('Bot installation or run does not match the session')
                            request = Request(session, packet.get("method"), packet.get("args", {}))
                            self.requests.put(request, timeout=1)
                            self.notify()
                            while not request.done.wait(0.1):
                                if session.cancelled.is_set():
                                    return
                            peer.sendall((json.dumps(request.response, ensure_ascii=False) + "\n").encode())
                except (OSError, ValueError, queue.Full, TypeError):
                    pass
                finally:
                    peer.close()
                    session.peer = None
                if authenticated:
                    self._event(session, "disconnect", "Связь со скриптом потеряна")
                    return
        finally:
            session.listener.close()

    @staticmethod
    def _frames(value, *, zero=False):
        if type(value) is not int or not (0 if zero else 1) <= value <= 3600:
            raise ValueError("Число кадров должно быть целым от 1 до 3600")
        return value

    def _dispatch(self, request):
        if not isinstance(request.args, dict):
            raise ValueError("Invalid request arguments")
        args = request.args
        method = request.method
        if method == "state":
            request.reply(self.snapshot())
        elif method == 'map' and self.map_reader:
            name=args.get('name')
            request.reply(self.map_reader(str(name)) if name else self.map_reader())
        elif method == 'inventory' and self.inventory_reader:
            request.reply(self.inventory_reader())
        elif method=='travel_policy':
            if self.safety_profile!='training':raise ValueError('Нужен профиль training')
            if not self.map_reader or not self.game_reader:raise ValueError('Перезапусти приложение для путешествий')
            grid=self.map_reader()
            if args.get('map')!=grid['name']:raise ValueError('Карта разрешения изменилась')
            from .travel_policy import make_policy
            self.trainer_policy=make_policy(self.game_reader(),grid,args.get('trainer_ids',[]))
            request.reply()
        elif method=='safety_profile':
            profile=args.get('profile')
            if profile!='training':raise ValueError('Неизвестный профиль защиты')
            self.safety_profile=profile
            self.record_event('safety_profile','Включена покадровая защита прокачки',dict(profile=profile))
            request.reply()
        elif method in ('cut_tree','field_teleport','training_item'):
            if self.safety_profile!='training' or not self.field_installer or self.action or self.field_runtime:raise ValueError('Полевое действие требует свободную сессию с защитой training')
            if self.move_runtime and self.move_runtime.owns_input:raise ValueError('Сначала дождись окончания обучения')
            runtime=self.field_installer(dict(args,action='teleport') if method=='field_teleport' else dict(args,action='training_item') if method=='training_item' else args)
            if isinstance(runtime,dict):
                from .field_teleport import REASONS
                self.record_event('field_teleport_skipped',REASONS.get(runtime['reason'],runtime['reason'])+' · возвращаемся пешком',runtime);request.reply(runtime);return
            self.field_runtime=runtime;self.field_request=request;self.release()
            self.record_event('field_action_started','Lucky Egg' if method=='training_item' else 'Teleport к Pokémon Center' if method=='field_teleport' else 'Срубаем дерево Cut',dict(args,action='training_item' if method=='training_item' else 'teleport' if method=='field_teleport' else 'cut',pokemon_uid=self.field_runtime.provider))
        elif method=='move_plan':
            if self.safety_profile!='training' or not self.move_installer:raise ValueError('Нужен профиль training и обновлённое приложение')
            if self.move_runtime is not None:raise ValueError('План приёмов уже установлен для этого запуска')
            request.reply(self.move_installer(args))
        elif method == 'expect_interaction':
            context=args.get('context')
            if context not in ('travel','healing','storage'):raise ValueError('Неизвестный контекст взаимодействия')
            self.interaction=context
            request.reply()
        elif method == 'event':
            result=self.record_event(str(args.get('code','script_event'))[:80],str(args.get('message',''))[:2000],args.get('details',{}))
            if isinstance(result,Future):
                self.pending_writes.append((request,result));result.add_done_callback(lambda _:self.notify())
            else:request.reply()
        elif method == 'handoff':
            reason=str(args.get('message','Нужен выбор игрока'))[:2000]
            code=str(args.get('code','needs_input'))[:80]
            self.record_event(code,reason,args.get('details',{}))
            self.release()
            self.session.finishing=True
            self.session.completion_reason=reason
            self.session.completion_status='finished' if code in ('target_reached','party_change_complete') else 'attention'
            request.reply()
        elif method == "log":
            self.log(str(args.get("message", ""))[:2000])
            request.reply()
        elif method == "finish":
            if self.action:
                raise ValueError("A button action is still running")
            self.session.finishing = True
            self.session.success = args.get("success", True) is True
            error=args.get('error')
            if not self.session.success and isinstance(error,dict):
                self.session.error_detail={k:str(error.get(k,''))[:12000 if k=='traceback' else 2000] for k in ('error_type','message','traceback')}
                self.session.completion_reason='Ошибка скрипта: '+self.session.error_detail['message']
            request.reply()
        elif self.session.finishing:
            request.reply(error="Скрипт уже завершён", cancelled=True)
        elif method in ('walk_segment','walk_step'):
            if self.action:raise ValueError('Другая команда ещё выполняется')
            if self.recovery_runtime:request.reply(dict(interrupted='field_recovery'));return
            if self.move_runtime and self.move_runtime.owns_input:request.reply(dict(reason='learning'));return
            if self.safety_profile!='training':raise ValueError("Для ходьбы включи bot.safety_profile('training')")
            if not self.walk_reader or not self.map_reader:raise ValueError('Перезапусти приложение для ускоренной ходьбы')
            from .movement import WalkSegment,straight_path,safe_segment,safe_step,movement_mode,MAX_SEGMENT
            start=args.get('start');goal=args.get('goal');name=args.get('map');search=args.get('search',False);allow_encounters=args.get('allow_encounters',False)
            if type(search) is not bool or type(allow_encounters) is not bool or not isinstance(name,str) or any(not isinstance(p,(list,tuple)) or len(p)!=2 or any(type(v) is not int for v in p) for p in (start,goal)):raise ValueError('Некорректные координаты участка')
            state=self.walk_reader();path=straight_path(start,goal)
            if not path or len(path)>MAX_SEGMENT:raise ValueError('Ожидался короткий прямой участок')
            if state.get('map')!=name or state.get('position')!=list(start) or not state.get('ready') or not state.get('open') or state.get('in_battle') or state.get('moving'):
                request.reply(dict(reason='changed',position=state.get('position')));return
            grid=self.map_reader();precision=method=='walk_step'
            from .travel_policy import trainer_grid
            policy=getattr(self,'trainer_policy',None)
            if policy and policy['map']==name:grid=trainer_grid(grid,policy['ids'])
            safe=grid and (len(path)<=2 and safe_step(grid,start,goal) if precision else safe_segment(grid,start,path,search=search,allow_encounters=allow_encounters)==path)
            if not safe:
                request.reply(dict(reason='unsafe',position=state.get('position')));return
            mode='walk' if precision else movement_mode(state,len(path))
            walk=WalkSegment(name,start,goal,state['frame'],mode=mode,precision=precision)
            self.action=dict(request=request,walk=walk,buttons=walk.button,start_frame=state['frame'])
            self.record_event('walk_segment_started',('Бег' if mode=='run' else 'Ходьба')+' · '+str(len(path))+' клеток',dict(map=name,start=start,goal=goal,search=search,allow_encounters=allow_encounters,tiles=len(path),mode=mode,precision=precision))
        elif method in ("press", "wait_frames"):
            if method=='press' and self.recovery_runtime:request.reply(dict(interrupted='field_recovery'));return
            if method=='press' and self.move_runtime and self.move_runtime.owns_input:request.reply(dict(interrupted='move_plan'));return
            if self.action:
                raise ValueError("Другая команда ещё выполняется")
            frames = self._frames(args.get("frames"))
            mask = 0
            buttons = "Ожидание"
            if method == "press":
                buttons = str(args.get("button", "")).upper()
                try:
                    mask = sum(BUTTONS[name] for name in set(buttons.split("+")))
                except KeyError as error:
                    raise ValueError("Неизвестная кнопка GBA") from error
                release = self._frames(args.get("release_frames", 1), zero=True)
                self.record_event('bot_input',buttons,dict(buttons=buttons,frames=frames,release_frames=release))
            else:
                release = 0
            phases = deque([[mask, frames]])
            if release:
                phases.append([0, release])
            self.action = {"request": request, "phases": phases, "buttons": buttons,
                           "start_frame": self.frame_reader()}
        elif method == "checkpoint":
            result = self.checkpoint(str(args.get("name", "Слот бота")))
            if isinstance(result, Future):
                self.pending_writes.append((request, result))
                result.add_done_callback(lambda _: self.notify())
            else:
                request.reply(result)
        elif method == 'manage_speed':
            enabled=args.get('enabled')
            if type(enabled) is not bool:raise ValueError('Управлять скоростью: требуется bool')
            if self.safety_profile!='training':raise ValueError('Для автоскорости включи защиту training')
            if self.speed_installer is None:raise ValueError('Перезапусти приложение для управления скоростью')
            from .automatic_speed import speed_cap
            maximum=speed_cap(args.get('max_speed',12))
            if 'max_speed' in args:self.speed_installer(enabled,max_speed=maximum)
            else:self.speed_installer(enabled)
            request.reply()
        elif method == "set_speed":
            speed = normalize_speed(args.get('speed'))
            self.set_speed(speed)
            request.reply()
        else:
            raise ValueError("Неизвестная команда API")

    def ready_work(self):
        return (not self.requests.empty() or not self.events.empty()
                or any(future.done() or request.session.cancelled.is_set() for request,future in self.pending_writes)
                or bool(self.session and self.process and self.process.poll() is not None))

    def poll(self, *, max_requests=8, request_budget=.002, max_events=32, event_budget=.001):
        self._main()
        self._reap()
        waiting = []
        for request, future in self.pending_writes:
            if request.session is not self.session or request.session.cancelled.is_set():
                request.reply(error="Управление возвращено игроку", cancelled=True)
            elif future.done():
                try:
                    request.reply(future.result())
                except Exception as error:
                    request.reply(error=str(error))
            else:
                waiting.append((request, future))
        self.pending_writes = waiting
        event_deadline=time.perf_counter()+event_budget
        for _ in range(max_events):
            try:
                session, kind, message = self.events.get_nowait()
            except queue.Empty:
                break
            if session is self.session:
                if kind == "log":
                    self.log(message)
                elif not session.finishing and self.process and self.process.poll() is None:
                    self.stop(message, status="error")
            if time.perf_counter()>=event_deadline:break
        deadline = time.perf_counter() + request_budget
        for _ in range(max_requests):
            try:
                request = self.requests.get_nowait()
            except queue.Empty:
                break
            if request.session is not self.session or request.session.cancelled.is_set():
                request.reply(error="Управление возвращено игроку", cancelled=True)
                continue
            try:
                started = time.perf_counter()
                if self.metrics:
                    self.metrics('rpc_queue_' + str(request.method), (started - request.received_at) * 1000)
                self._dispatch(request)
            except Exception as error:
                request.reply(error=str(error))
            finally:
                if self.metrics:
                    self.metrics('rpc_dispatch_' + str(request.method), (time.perf_counter() - started) * 1000)
            if time.perf_counter() >= deadline:
                break
        if not self.requests.empty():
            self.notify()
        if self.process and self.process.poll() is not None:
            success = self.process.returncode == 0 and self.session.success
            self.stop(self.session.completion_reason or ("Скрипт завершён" if success else "Ошибка скрипта — смотри журнал"),
                      status=self.session.completion_status if success else "error")

    def next_mask(self, manual_mask):
        self._main()
        if self.running and self.recovery_runtime:return self.recovery_runtime.mask
        if self.running and self.field_runtime:return self.field_runtime.mask
        if self.running and self.move_runtime and self.move_runtime.owns_input:return self.move_runtime.mask
        if self.running and self.action and 'walk' in self.action:
            action=self.action
            try:mask,result=action['walk'].next(self.walk_reader())
            except Exception as error:
                self.action=None;self.release();action['request'].reply(error=str(error));return 0
            if result is not None:
                self.action=None;self.release();action['request'].reply(result)
                message={'reached':'Дошли до точки','battle':'Движение прервано встречей','obstacle':'Впереди NPC: переходим на отдельные шаги','stalled':'Проверяем препятствие','interrupted':'Движение прервано событием','map_changed':'Карта изменилась','off_corridor':'Персонаж покинул участок','invalid_position':'Координаты временно недоступны','unsupported_transport':'Для этого маршрута спешься: поддержаны ходьба и бег'}.get(result['reason'],result['reason'])
                self.record_event('walk_segment_finished',message,result)
                return 0
            return mask
        return self.action["phases"][0][0] if self.running and self.action else 0 if self.running else manual_mask

    def after_frame(self, frame):
        self._main()
        if not self.action or 'walk' in self.action:
            return
        phases = self.action["phases"]
        phases[0][1] -= 1
        if phases[0][1] == 0:
            phases.popleft()
        if not phases:
            self.action["request"].reply({"start_frame": self.action["start_frame"], "end_frame": frame})
            self.action = None

    def stop(self, reason="Управление возвращено игроку", *, status="stopped"):
        self._main()
        session = self.session
        if session is None:
            return
        self.session = None  # Revoke input ownership before any cleanup.
        if self.recovery_runtime:self.recovery_runtime.cancel();self.recovery_runtime=None
        if self.move_runtime:self.move_runtime.cancel();self.move_runtime=None
        if self.field_runtime:self.field_runtime.cancel();self.field_runtime=None
        if self.field_request:self.field_request.reply(error=reason,cancelled=True);self.field_request=None
        session.cancelled.set()
        for request, _ in self.pending_writes:
            request.reply(error=reason, cancelled=True)
        self.pending_writes.clear()
        if self.action:
            self.action["request"].reply(error=reason, cancelled=True)
            self.action = None
        self.release()
        if self.speed_installer:self.speed_installer(False)
        session.listener.close()
        peer = session.peer
        if peer:
            try:
                peer.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            peer.close()
        process, self.process = self.process, None
        if process:
            if process.poll() is None:
                self._signal(process, force=False)
            self.retiring.append((process, time.monotonic() + 0.5))
        self.status, self.reason = status, reason
        detail=dict(script=self.script.name if self.script else None,automation_session_id=session.id,outcome='success' if status=='finished' else 'cancelled' if status=='stopped' else 'needs_input' if status=='attention' else 'failed',log_file=str(self.log_file.name) if self.log_file else None)
        if session.error_detail:detail.update(session.error_detail)
        self.record_event('script_'+status,reason,detail)
        if self.log_file:
            self.log_file.close()
            self.log_file = None

    def _reap(self):
        remaining = []
        for process, deadline in self.retiring:
            if process.poll() is not None:
                continue
            if time.monotonic() >= deadline:
                self._signal(process, force=True)
            remaining.append((process, deadline))
        self.retiring = remaining

    @staticmethod
    def _signal(process, *, force):
        if process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
        except ProcessLookupError:
            pass
        except PermissionError:
            # Some host process supervisors restrict group signals. Input was
            # already revoked; still terminate the managed Python process.
            try:
                process.kill() if force else process.terminate()
            except ProcessLookupError:
                pass

    def close(self):
        self.stop("Игра закрывается")
        for process, _ in self.retiring:
            if process.poll() is None:
                self._signal(process, force=True)
            process.wait(timeout=2)
        self.retiring.clear()
