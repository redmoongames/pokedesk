"""Bounded analytics requests: durable barrier, separate process, detached result.

Only this dispatcher waits for persistence or subprocesses. The owner never
waits here. Shutdown cancels queued work and terminates the read-only worker.
"""

from .paths import session_paths
from concurrent.futures import Future, CancelledError, TimeoutError
from dataclasses import dataclass
from pathlib import Path
import json
import queue
import subprocess
import sys
import tempfile
import threading
import time
from .history_queries import validate
from .runtime_data import DetachedResult, PreparedHistoryExport


@dataclass
class Query:
    name: str
    params: tuple
    barrier: Future | None
    future: Future
    export_path: Path | None


class AnalyticsService:
    def __init__(self, root, *, capacity=8, timeout=60):
        self.root = Path(root);self.timeout = timeout
        self.requests = queue.Queue(maxsize=capacity);self.stopped = threading.Event()
        self.lock = threading.Lock();self.process = None
        self.thread = threading.Thread(target=self._run, name='pokemon-analytics-dispatch', daemon=True)
        self.thread.start()

    @property
    def closed(self):return self.stopped.is_set()

    def request(self, name, params=(), *, barrier=None, export_path=None):
        params = validate(name, params)
        if name=='export' and export_path is None:raise ValueError('History export requires a destination')
        future = Future();future.work_started = threading.Event();future.worker_pid = None
        job = Query(name, params, barrier, future, Path(export_path) if export_path is not None else None)
        with self.lock:
            if self.stopped.is_set():future.set_exception(CancelledError('Analytics service closed'))
            else:
                try:self.requests.put_nowait(job)
                except queue.Full:future.set_exception(RuntimeError('Analytics request queue is full'))
        return future

    def _check(self, job):
        if self.stopped.is_set() or job.future.cancelled():raise CancelledError('Analytics request cancelled')

    def _compute(self, job):
        if job.barrier is not None:
            while True:
                self._check(job)
                try:job.barrier.result(timeout=.05);break
                except TimeoutError:
                    if job.barrier.done():job.barrier.result()
        self._check(job)
        python = session_paths(self.root).installation.python
        if not python.exists():python = Path(sys.executable)
        with tempfile.TemporaryDirectory(prefix='pokedesk-analytics-') as temporary:
            folder = Path(temporary);request = folder/'request.json';output = folder/'result.json'
            from .installation_versions import loaded_id,require_response
            request.write_text(json.dumps(dict(database=str(session_paths(self.root).profile.journal),name=job.name,params=job.params,_installation=loaded_id())))
            with (folder/'worker.log').open('w+') as log:
                self._check(job)
                # Popen may wait for exec; never hold the producer/close lock
                # while starting a process. A racing close is checked below.
                process = subprocess.Popen([str(python),'-I','-B',str(Path(__file__).with_name('analytics_worker.py')),str(request),str(output)],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=log)
                with self.lock:
                    self.process = process;job.future.worker_pid = process.pid
                deadline = time.monotonic() + self.timeout
                try:
                    while process.poll() is None:
                        self._check(job)
                        if output.with_suffix('.started').exists():job.future.work_started.set()
                        if time.monotonic() >= deadline:raise TimeoutError('Analytics worker deadline exceeded')
                        self.stopped.wait(.005)
                    self._check(job)
                    if process.returncode:
                        log.seek(0);raise RuntimeError('Analytics worker failed: ' + log.read()[-4000:])
                    job.future.work_started.set()
                    require_response(json.loads(output.with_suffix('.version.json').read_text()))
                    if job.name == 'export':
                        return PreparedHistoryExport(job.export_path, output.read_bytes())
                    rows=[]
                    with output.open(encoding='utf-8') as stream:
                        for number,line in enumerate(stream):
                            self._check(job);rows.append(json.loads(line))
                            if number%16==0:time.sleep(0)
                    return DetachedResult(rows)
                finally:
                    if process.poll() is None:process.kill()
                    process.wait()
                    with self.lock:
                        if self.process is process:self.process = None

    def _run(self):
        while True:
            job = self.requests.get()
            if job is None:return
            if not job.future.set_running_or_notify_cancel():continue
            try:
                self._check(job);result = self._compute(job)
            except BaseException as error:job.future.set_exception(error)
            else:job.future.set_result(result)

    def close(self):
        with self.lock:
            if self.stopped.is_set():return
            self.stopped.set()
            if self.process is not None and self.process.poll() is None:self.process.terminate()
            while True:
                try:job = self.requests.get_nowait()
                except queue.Empty:break
                if job is not None:job.future.cancel()
            self.requests.put_nowait(None)
