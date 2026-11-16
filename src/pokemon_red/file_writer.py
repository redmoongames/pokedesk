"""One bounded, ordered file writer. Completions are consumed on the session owner."""
from __future__ import annotations

from collections import deque
from concurrent.futures import Future
from dataclasses import dataclass
import threading
import time
from typing import Any, Callable


@dataclass
class WriteJob:
    operation: Callable[[], Any]
    future: Future
    key: str | None


class FileWriter:
    def __init__(self, notify=lambda: None, *, capacity=16):
        self.notify = notify
        self.capacity = capacity
        self.pending = deque()
        self.condition = threading.Condition()
        self.stopping = False
        self.thread = threading.Thread(target=self._run, name="pokemon-file-writer", daemon=True)
        self.thread.start()

    def submit(self, operation: Callable[[], Any], *, coalesce: str | None = None) -> Future:
        future = Future()
        with self.condition:
            if self.stopping:
                raise RuntimeError("Запись сохранений уже завершается")
            if coalesce is not None:
                # Only unpublished, replaceable jobs (autosave/telemetry).
                # Remove the old job and append the new one after all earlier
                # named/manual writes; replacing in place would reorder saves.
                for job in list(self.pending):
                    if job.key == coalesce:
                        self.pending.remove(job)
                        job.future.cancel()
            if len(self.pending) >= self.capacity:
                raise RuntimeError("Очередь записи заполнена; дождись сохранения")
            self.pending.append(WriteJob(operation, future, coalesce))
            self.condition.notify()
        return future

    def _run(self):
        while True:
            with self.condition:
                while not self.pending and not self.stopping:
                    self.condition.wait()
                if not self.pending:
                    return
                job = self.pending.popleft()
            if not job.future.set_running_or_notify_cancel():
                continue
            started = time.perf_counter()
            try:
                result = job.operation()
            except BaseException as error:
                job.future.write_ms = (time.perf_counter() - started) * 1000
                job.future.set_exception(error)
            else:
                job.future.write_ms = (time.perf_counter() - started) * 1000
                job.future.set_result(result)
            self.notify()  # Thread-safe wakeup only; never calls Tk or mGBA.

    def close(self):
        """Drain accepted jobs. The session calls this after its final checkpoint completed."""
        with self.condition:
            self.stopping = True
            self.condition.notify()
        self.thread.join()
