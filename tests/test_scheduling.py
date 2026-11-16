"""Deterministic wake races and real-core fairness under ready-work pressure."""
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
import queue,socket,sys,threading,time,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.scheduling import WorkSignal,RuntimeScheduler,FrameQuantum,next_frame_at
from pokemon_red.automation import Request,Session
from test_engine_runtime import ProbeRuntime
from test_runtime_performance import PrivateSessionTestCase


class SignalTests(unittest.TestCase):
    def test_notification_before_wait_is_retained(self):
        signal=WorkSignal();version=signal.version;signal.notify()
        with patch.object(signal.condition,'wait') as wait:
            self.assertFalse(signal.wait(version,1,lambda:False));wait.assert_not_called()

    def test_unprocessed_ready_work_does_not_depend_on_new_notification(self):
        signal=WorkSignal();version=signal.version
        with patch.object(signal.condition,'wait') as wait:
            self.assertFalse(signal.wait(version,1,lambda:True));wait.assert_not_called()

    def test_publish_between_predicate_and_sleep_cannot_lose_wakeup(self):
        signal=WorkSignal();version=signal.version;checking=threading.Event();published=threading.Event();done=threading.Event()
        def producer():
            checking.wait(2);published.set();signal.notify();done.set()
        thread=threading.Thread(target=producer);thread.start()
        def ready():
            checking.set();self.assertTrue(published.wait(2));return False
        try:
            self.assertTrue(signal.wait(version,2,ready))
            self.assertTrue(done.wait(1));self.assertTrue(signal.changed(version))
        finally:thread.join(2)
        self.assertFalse(thread.is_alive())

    def test_incomplete_future_may_sleep_and_ready_future_may_not(self):
        signal=WorkSignal();future=Future();version=signal.version
        with patch.object(signal.condition,'wait') as wait:
            self.assertTrue(signal.wait(version,.5,future.done));wait.assert_called_once_with(.5)
        future.set_result(None)
        with patch.object(signal.condition,'wait') as wait:
            self.assertFalse(signal.wait(version,.5,future.done));wait.assert_not_called()

    def test_concurrent_producers_do_not_overwrite_versions(self):
        signal=WorkSignal();threads=[threading.Thread(target=lambda:[signal.notify() for _ in range(100)]) for _ in range(4)]
        for thread in threads:thread.start()
        for thread in threads:thread.join(2)
        self.assertEqual(signal.version,400)

    def test_policy_waits_until_due_task_and_bounds_idle_watchdog(self):
        signal=WorkSignal();scheduler=RuntimeScheduler(signal,clock=lambda:100.)
        with patch.object(signal,'wait',return_value=True) as wait:
            scheduler.wait(7,100.02,lambda:False);self.assertAlmostEqual(wait.call_args.args[1],.02)
            scheduler.wait(7,1000,lambda:False);self.assertAlmostEqual(wait.call_args.args[1],.05)
            scheduler.wait(7,99,lambda:False);self.assertEqual(wait.call_args.args[1],0)

    def test_frame_quantum_responds_to_existing_work_new_notification_and_deadline(self):
        signal=WorkSignal();clock=[10.];scheduler=RuntimeScheduler(signal,counter=lambda:clock[0]);version=scheduler.begin_turn()
        quantum=scheduler.frame_quantum(version,lambda:False);self.assertFalse(quantum.should_yield())
        signal.notify();self.assertTrue(quantum.should_yield())
        quantum=scheduler.frame_quantum(signal.version,lambda:True);self.assertTrue(quantum.should_yield())
        quantum=scheduler.frame_quantum(signal.version,lambda:False);clock[0]+=1;self.assertTrue(quantum.should_yield())

    def test_pacing_uses_fractional_frame_budget_at_each_requested_speed(self):
        for speed in (8,12,16):
            self.assertAlmostEqual(next_frame_at(10,.25,speed),10+.75/(59.7275*speed))
            self.assertEqual(next_frame_at(10,2,speed),10)


class SessionScheduleTests(unittest.TestCase):
    def controller(self):
        from pokemon_red.session_controller import SessionController
        c=SessionController.__new__(SessionController);c.paused=True;c.closing=False;c.session_transition=False;c.save_failed=False
        c.last_tick=0;c.budget=60;c.last_video=c.last_panel=c.last_export=100;c.last_save=100
        c.game=SimpleNamespace(frame=300);c.last_saved_frame=300;c.settings=dict(autosave_enabled=True,autosave_seconds=5,speed=16)
        c.critical_save_pending=lambda:False;c.operation=SimpleNamespace(active=False,next_poll_at=lambda:None);c.delivery=SimpleNamespace(next_poll_at=lambda:None)
        return c
    def test_pause_and_checkpoint_do_not_leave_an_overdue_frame_deadline(self):
        c=self.controller()
        with patch('pokemon_red.session_controller.time.monotonic',return_value=100):
            self.assertAlmostEqual(c.next_deadline(),100+1/30)
            c.paused=False;c.critical_save_pending=lambda:True
            self.assertAlmostEqual(c.next_deadline(),100+1/30)
    def test_autosave_and_worker_status_remain_scheduled_when_paused(self):
        c=self.controller();c.game.frame=301;c.last_save=95
        with patch('pokemon_red.session_controller.time.monotonic',return_value=100):
            self.assertEqual(c.next_deadline(),100)
            c.pending_save_frame=301;c.operation.next_poll_at=lambda:100.01
            self.assertEqual(c.next_deadline(),100.01)
    def test_ordinary_ready_work_yields_only_after_a_guarded_frame(self):
        # Exercise the native-independent frame loop with an always-ready quantum.
        from pokemon_red.session_controller import SessionController
        c=SessionController.__new__(SessionController);masks=[];guards=[]
        c.transport=SimpleNamespace(consume_interrupt=lambda _:False,after_frame=lambda _:None)
        c.closed=c.closing=c.session_transition=c.paused=False;c.last_tick=100;c.last_video=c.last_panel=c.last_export=100.01
        c.settings=dict(speed=16);c.budget=0;c.keys=set();c.game=SimpleNamespace(frame=10,clear_audio=Mock())
        c.game.advance=lambda n,mask:(masks.append(mask),setattr(c.game,'frame',c.game.frame+n))
        c.automation=SimpleNamespace(running=True,next_mask=lambda _:1,after_frame=Mock())
        c.critical_save_pending=lambda:False;c.check_shiny_encounter=lambda:False
        c.check_training_decision=lambda:(guards.append(c.game.frame),False)[1]
        c.sync_audio=Mock();c.playback=SimpleNamespace(handle=False);c.save_if_due=Mock();c.error=Mock();c.diagnostics=SimpleNamespace(measure=Mock())
        with patch('pokemon_red.session_controller.time.monotonic',return_value=100.01):
            c.tick(quantum=FrameQuantum(1000,lambda:True,lambda:0))
        c.error.assert_not_called();self.assertEqual(masks,[1]);self.assertEqual(guards,[10,11])


class SchedulerActorTests(PrivateSessionTestCase):
    def setUp(self):
        super().setUp();self.runtime=ProbeRuntime(self.root,paused=True);self.runtime.ready.result(5)
    def probe(self,fn):return self.runtime.submit('probe',fn).result(5)
    def wait(self,predicate,timeout=3):
        end=time.monotonic()+timeout
        while not predicate() and time.monotonic()<end:time.sleep(.001)
        self.assertTrue(predicate())
    def tearDown(self):
        if not self.runtime.finished.done():self.runtime.take_control(close=True)
        self.runtime.finished.result(8);self.runtime.thread.join(1);super().tearDown()

    def intercept_wait(self):
        entered=threading.Event();release=threading.Event();skipped=[];original=self.runtime.work.wait
        def intercept(version,timeout,ready):
            self.runtime.work.wait=original;entered.set();release.wait(3)
            result=original(version,timeout,ready);skipped.append(not result);return result
        self.probe(lambda c:setattr(self.runtime.work,'wait',intercept))
        self.assertTrue(entered.wait(2));return release,skipped

    def test_preferences_arriving_before_sleep_are_applied_without_wait(self):
        release,skipped=self.intercept_wait()
        try:version=self.runtime.set_preferences(dict(volume=17));release.set();self.wait(lambda:self.runtime.latest.status['preferences_version']>=version)
        finally:release.set()
        self.assertEqual(skipped,[True]);self.assertEqual(self.probe(lambda c:c.settings['volume']),17)

    def test_generic_future_completion_wakes_owner_before_sleep(self):
        future=Future();reply=self.runtime.submit('probe',lambda c:future)
        release,skipped=self.intercept_wait()
        try:future.set_result('ready');release.set();self.assertEqual(reply.result(2),'ready')
        finally:release.set()
        self.assertEqual(skipped,[True])

    def test_real_file_writer_completion_is_consumed_before_sleep(self):
        writer_gate=threading.Event();written=threading.Event();published=[];futures=[]
        def setup(c):futures.append(c.submit_write(lambda:(writer_gate.wait(3),written.set()),success=lambda _:published.append(threading.get_ident())))
        self.probe(setup)
        release,skipped=self.intercept_wait()
        try:
            writer_gate.set();self.assertTrue(written.wait(2))
            futures[0].result(2)
            release.set();self.wait(lambda:bool(published))
        finally:writer_gate.set();release.set()
        self.assertEqual(skipped,[True]);self.assertEqual(published,[self.runtime.thread.ident])

    def test_pending_frame_action_is_not_busy_work_while_paused(self):
        def setup(c):
            c.automation.session=Session(socket.socket());c.automation._dispatch(Request(c.automation.session,'press',dict(button='A',frames=30)))
            return self.runtime.ready_work(c)
        self.assertFalse(self.probe(setup));before=self.runtime.latest.frame;time.sleep(.06)
        self.assertEqual(self.runtime.latest.frame,before)

    def test_journal_failure_wakes_paused_owner_without_advancing_frames(self):
        before=self.runtime.latest.frame
        def fail():raise OSError('journal test failure')
        def setup(c):
            store=c.history.db;future=store.writer.submit(fail);store.pending.append((future,()))
        self.probe(setup)
        self.wait(lambda:'Ошибка журнала SQLite' in self.runtime.latest.status['notice'])
        self.assertTrue(self.runtime.latest.status['paused']);self.assertEqual(self.runtime.latest.frame,before)
        self.assertFalse(self.probe(lambda c:c.history.ready_work()))

    def test_flooded_command_sources_allow_frames_autosaves_and_urgent_takeover(self):
        start=[];stop=threading.Event();errors=[];sessions=[];queues=[]
        def setup(c):
            session=Session(socket.socket());c.automation.session=session;c.automation._dispatch(Request(session,'press',dict(button='A',frames=3600)))
            c.settings.values.update(autosave_enabled=True,autosave_seconds=.05);c.set_speed(16);start.append(c.game.frame);sessions.append(session);queues.append(c.automation.requests)
        self.probe(setup);session=sessions[0]
        def flood():
            try:
                while not stop.is_set():
                    for _ in range(12):
                        self.runtime.submit('probe',lambda c:None)
                        try:queues[0].put_nowait(Request(session,'state',{}))
                        except queue.Full:pass
                    self.runtime.wake();time.sleep(.001)
            except Exception as error:errors.append(error)
        thread=threading.Thread(target=flood);thread.start()
        try:
            self.wait(lambda:self.runtime.latest.frame>start[0]+30 and self.runtime.latest.status['last_saved_frame']>start[0],timeout=5)
            epoch=self.runtime.take_control(pause=True);self.wait(lambda:self.runtime.latest.epoch>=epoch)
            self.assertFalse(self.runtime.latest.status['automation']['running']);self.assertTrue(self.runtime.latest.status['paused'])
        finally:stop.set();thread.join(2)
        self.assertFalse(errors);self.assertFalse(thread.is_alive())


if __name__=='__main__':unittest.main()
