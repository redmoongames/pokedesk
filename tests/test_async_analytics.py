"""Owner integration for asynchronous history, stale results and ordered export."""
from concurrent.futures import Future, CancelledError
from pathlib import Path
from types import SimpleNamespace
import json
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from test_runtime_performance import PrivateSessionTestCase
from test_engine_runtime import ProbeRuntime
from pokemon_red.history import History
from pokemon_red.runtime_data import DetachedResult,PreparedHistoryExport
from public.test_analytics_service import seed


class ProjectionBoundTests(unittest.TestCase):
    def test_already_reported_writer_fault_cannot_fall_back_to_old_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);history=History(root,async_writer=True)
            old=Future();old.set_result(None);history.db.last_write=old
            history.db.error=OSError('journal unavailable');history.db.error_reported=True
            with self.assertRaisesRegex(OSError,'journal unavailable'):history.query_barrier().result()
            history.close()

    def test_projection_keeps_active_records_even_if_wall_clock_moves_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);db=seed(root,1)
            db.executemany('INSERT INTO timelines VALUES(?,?,?,?,?,?)',[(str(i),None,'z','old',0,'{}') for i in range(2001)])
            db.executemany('INSERT INTO training_runs VALUES(?,?,?,?,?,?,?,?,?,?)',[(str(i),'z','z','Route1','adaptive','target',15,'completed','team','{}') for i in range(201)])
            db.commit();db.close();history=History(root,async_writer=True)
            self.assertIsNotNone(history.db.execute('SELECT id FROM timelines WHERE id=?',(history.timeline_id,)).fetchone())
            history.db.execute("INSERT INTO training_runs VALUES('active','a',NULL,'Route1','adaptive','target',15,'running','team','{}')")
            for _ in range(100):history.db.commit()
            self.assertIsNotNone(history.db.execute("SELECT id FROM training_runs WHERE id='active'").fetchone())
            history.change_timeline('test')
            self.assertEqual(history.db.active_timeline,history.timeline_id);history.close()

    def test_historical_projection_is_bounded_and_new_ids_stay_durable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);db=seed(root,2505);db.close();history=History(root,async_writer=True)
            self.assertEqual(history.db.execute('SELECT count(*) FROM training_cycles').fetchone()[0],2000)
            from pokemon_red.analytics import AnalyticsService
            service=AnalyticsService(root)
            try:self.assertEqual(service.request('comparisons',barrier=history.query_barrier()).result(10).value[0]['cycles'],2505)
            finally:service.close();service.thread.join(3)
            cursor=history.db.execute("INSERT INTO training_cycles(run_id,number,status,body) VALUES('run',2506,'completed','{}')")
            self.assertEqual(cursor.lastrowid,2506);history.db.commit().result(5);history.close()
            import sqlite3
            with sqlite3.connect(root/'Data/history.sqlite3') as check:
                self.assertEqual(check.execute('SELECT count(*) FROM training_cycles').fetchone()[0],2506)


class AnalyticsActorTests(PrivateSessionTestCase):
    def setUp(self):
        super().setUp();self.runtime=ProbeRuntime(self.root,paused=True);self.runtime.ready.result(10)

    def tearDown(self):
        if not self.runtime.finished.done():self.runtime.take_control(close=True)
        self.runtime.finished.result(10);self.runtime.thread.join(2);super().tearDown()

    def probe(self,fn):return self.runtime.submit('probe',fn).result(5)

    def test_takeover_does_not_wait_for_a_history_write_barrier(self):
        barrier=Future()
        def setup(c):
            c.history.query_barrier=lambda:barrier
            c.history.comparisons=Mock(side_effect=AssertionError('owner must not aggregate'))
        self.probe(setup);query=self.runtime.submit('history_read','comparisons',())
        self.probe(lambda c:None);epoch=self.runtime.take_control(pause=True)
        end=time.monotonic()+2
        while self.runtime.latest.epoch<epoch and time.monotonic()<end:time.sleep(.001)
        self.assertGreaterEqual(self.runtime.latest.epoch,epoch);self.assertFalse(query.done())
        barrier.set_result(None);self.assertEqual(query.result(10),[])

    def test_same_frame_reload_rejects_late_history_and_export(self):
        for export in (False,True):
            pending=Future();service=Mock();service.request.return_value=pending
            self.runtime.analytics=service
            path=self.root/'old-export.json'
            query=self.runtime.submit('history_export',path) if export else self.runtime.submit('history_read','comparisons',())
            self.probe(lambda c:c.game.load_state(self.root/'Data/FireRed.state'))
            pending.set_result(PreparedHistoryExport(path,b'{}') if export else DetachedResult(['old']))
            with self.assertRaises(CancelledError):query.result(5)
            self.assertFalse(path.exists())

    def test_real_export_is_durable_and_preserves_pending_future_chaining(self):
        self.probe(lambda c:c.history.event('test','off-owner export'))
        path=self.root/'history-export.json';self.runtime.submit('history_export',path).result(15)
        data=json.loads(path.read_text());self.assertEqual(data['schema'],2)
        self.assertIsInstance(data['cycles'],list);self.assertIsInstance(data['comparisons'],list)

    def test_analytics_can_restart_if_game_stays_open_after_close_attempt(self):
        self.runtime.submit('history_read','comparisons',()).result(10)
        previous=self.runtime.analytics;previous.close();previous.thread.join(3)
        self.assertEqual(self.runtime.submit('history_read','comparisons',()).result(10),[])
        self.assertIsNot(previous,self.runtime.analytics)

    def test_inventory_result_is_detached_readonly_and_periodic_boxes_are_shared(self):
        self.probe(lambda c:c.game.load_state(ROOT/'tests/fixtures/fire_red/clinic.state'))
        first=self.runtime.submit('inventory').result(5)
        with self.assertRaises(TypeError):first['party'][0].update(hp=0)
        before=self.runtime.latest.inventory['boxes']
        self.probe(lambda c:self.runtime.publish(c,force=True))
        self.assertIs(before,self.runtime.latest.inventory['boxes'])

    def test_autosave_and_frames_continue_while_analytics_waits_for_journal(self):
        barrier=Future()
        def setup(c):
            c.history.query_barrier=lambda:barrier
            c.settings.values.update(autosave_enabled=True,autosave_seconds=5)
            c.last_save=time.monotonic()-10;c.set_speed(16)
            return c.last_saved_frame
        before=self.probe(setup);query=self.runtime.submit('history_read','comparisons',())
        try:
            end=time.monotonic()+5
            while self.runtime.latest.status['last_saved_frame']<=before and time.monotonic()<end:time.sleep(.005)
            self.assertGreater(self.runtime.latest.status['last_saved_frame'],before)
            self.assertFalse(query.done());self.assertTrue((self.root/'Data/FireRed.state').is_file())
        finally:
            self.runtime.take_control(pause=True);barrier.set_result(None)
        query.result(10)
