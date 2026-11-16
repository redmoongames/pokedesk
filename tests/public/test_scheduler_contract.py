"""No-core checks for wakeup and frame budgets used by cancellation scheduling."""
from concurrent.futures import Future
import unittest
from unittest.mock import patch
from pokemon_red.scheduling import RuntimeScheduler, WorkSignal


class SchedulerContractTests(unittest.TestCase):
    def test_notification_before_wait_cannot_be_lost(self):
        signal = WorkSignal();version = signal.version;signal.notify()
        with patch.object(signal.condition, 'wait') as wait:
            self.assertFalse(signal.wait(version, 1, lambda:False));wait.assert_not_called()

    def test_ready_work_does_not_need_another_notification(self):
        signal = WorkSignal()
        with patch.object(signal.condition, 'wait') as wait:
            self.assertFalse(signal.wait(signal.version, 1, lambda:True));wait.assert_not_called()

    def test_unfinished_future_may_sleep(self):
        signal = WorkSignal();future = Future()
        with patch.object(signal.condition, 'wait') as wait:
            self.assertTrue(signal.wait(signal.version, .1, future.done));wait.assert_called_once()

    def test_new_notification_yields_after_one_guarded_frame(self):
        signal = WorkSignal();scheduler = RuntimeScheduler(signal, counter=lambda:0)
        quantum = scheduler.frame_quantum(signal.version, lambda:False)
        self.assertFalse(quantum.should_yield());signal.notify();self.assertTrue(quantum.should_yield())
