"""Cooperative owner scheduling; no emulator, transport, UI or filesystem access.

Notifications are retained as a monotonic version. A turn may wait only if its
version is still current AND its bounded service passes left no ready work.
Pending frame actions and incomplete futures are not ready work.
"""
from dataclasses import dataclass
from typing import Callable
import threading
import time


class WorkSignal:
    def __init__(self):
        self.condition = threading.Condition()
        self._version = 0
        self.notifications = 0
        self.waits = 0
        self.wait_seconds = 0.0

    @property
    def version(self):
        with self.condition:
            return self._version

    def notify(self):
        with self.condition:
            self._version += 1
            self.notifications += 1
            self.condition.notify()

    def changed(self, observed):
        with self.condition:
            return self._version != observed

    def wait(self, observed, timeout, ready):
        """Atomically check readiness/version and release the lock to wait.

        Producers publish their work before notify(). If a producer arrives
        between ready() and wait(), notify() takes this same lock, so it wakes
        the waiter after wait() atomically releases it. Wakeups are advisory;
        the owner always rechecks all sources on the next turn.
        """
        with self.condition:
            if self._version != observed or ready() or timeout <= 0:
                return False
            self.waits += 1
            started = time.monotonic()
            self.condition.wait(timeout)
            self.wait_seconds += time.monotonic() - started
            return True

    def metrics(self):
        with self.condition:
            return dict(version=self._version, notifications=self.notifications,
                        waits=self.waits, wait_seconds=round(self.wait_seconds, 6))


@dataclass(frozen=True)
class ServiceLimits:
    command_count: int = 8
    command_seconds: float = .002
    request_count: int = 8
    request_seconds: float = .002
    event_count: int = 32
    event_seconds: float = .001
    frame_seconds: float = .004
    watchdog_seconds: float = .05


@dataclass(frozen=True)
class FrameQuantum:
    deadline: float
    ready: Callable[[], bool]
    clock: Callable[[], float] = time.perf_counter

    def should_yield(self):
        # Called AFTER one complete guarded frame: ordinary queries cannot
        # starve native progress. Urgent revocation is checked before frames.
        return self.clock() >= self.deadline or self.ready()

    @classmethod
    def bounded(cls, seconds=.004):
        return cls(time.perf_counter() + seconds, lambda: False)


class RuntimeScheduler:
    def __init__(self, signal, *, limits=None, clock=None, counter=None):
        self.signal = signal
        self.limits = limits or ServiceLimits()
        self.clock = clock or time.monotonic
        self.counter = counter or time.perf_counter

    def begin_turn(self):
        return self.signal.version

    def frame_quantum(self, observed, ready):
        return FrameQuantum(self.counter() + self.limits.frame_seconds,
                            lambda: self.signal.changed(observed) or ready(), self.counter)

    def wait(self, observed, due, ready):
        now = self.clock()
        deadline = min(due, now + self.limits.watchdog_seconds)
        return self.signal.wait(observed, max(0.0, deadline - now), ready)


def next_frame_at(last_tick, budget, speed):
    """Real monotonic deadline; budget/press durations remain emulated frames."""
    return last_tick + max(0.0, 1.0 - budget) / (59.7275 * speed)
