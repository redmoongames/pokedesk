"""Read-only process queries, durable barriers and bounded lifecycle, no game."""
from concurrent.futures import Future, CancelledError
from pathlib import Path
import hashlib
import json
import os
import tempfile
import time
import unittest
from pokemon_red.database import connect
from pokemon_red.analytics import AnalyticsService
from pokemon_red.history_queries import query
from pokemon_red.runtime_data import DetachedResult, PreparedHistoryExport


def seed(root,count=3):
    db=connect(root)
    db.execute('CREATE TABLE events (id INTEGER PRIMARY KEY,time TEXT,code TEXT,message TEXT,detail TEXT)')
    db.execute('CREATE TABLE battles (id INTEGER PRIMARY KEY,time TEXT,map TEXT,outcome TEXT,xp INTEGER,frames INTEGER,detail TEXT)')
    db.execute('INSERT INTO training_runs VALUES(?,?,?,?,?,?,?,?,?,?)',('run','t','t','Route1','adaptive','target',15,'completed','team','{}'))
    body=json.dumps(dict(team=[],clinic='clinic',area=[],context={},speed_intervals=[dict(speed=8)]))
    db.executemany('INSERT INTO training_cycles(run_id,number,started_at,ended_at,status,game_seconds,active_seconds,target_xp,team_xp,battles,team_fingerprint,body) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(('run',i,'t','t','completed',120,20,100,100,1,'team',body) for i in range(count)))
    db.commit();return db


class AnalyticsProcessTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.db=seed(self.root)
        self.service=AnalyticsService(self.root)

    def tearDown(self):
        self.service.close();self.service.thread.join(3);self.assertFalse(self.service.thread.is_alive());self.db.close()

    def test_process_aggregation_matches_sync_and_does_not_modify_database(self):
        before=hashlib.sha256((self.root/'Data/history.sqlite3').read_bytes()).hexdigest()
        future=self.service.request('comparisons');result=future.result(10)
        self.assertIsInstance(result,DetachedResult);self.assertNotEqual(future.worker_pid,os.getpid())
        self.assertEqual(result.value,query(self.db,'comparisons'));self.assertEqual(result.value[0]['cycles'],3)
        self.assertEqual(before,hashlib.sha256((self.root/'Data/history.sqlite3').read_bytes()).hexdigest())

    def test_read_waits_for_committed_data_without_blocking_requester(self):
        barrier=Future();started=time.perf_counter();future=self.service.request('cycles',(200,),barrier=barrier)
        self.assertLess(time.perf_counter()-started,.1);self.assertFalse(future.done());self.assertIsNone(future.worker_pid)
        self.db.execute("UPDATE training_cycles SET target_xp=345 WHERE number=0");self.db.commit();barrier.set_result(None)
        rows=future.result(10).value;self.assertEqual(next(r for r in rows if r['number']==0)['target_xp'],345)

    def test_failed_durable_write_is_not_hidden_by_older_disk_data(self):
        barrier=Future();barrier.set_exception(OSError('journal unavailable'))
        future=self.service.request('comparisons',barrier=barrier)
        with self.assertRaisesRegex(OSError,'journal unavailable'):future.result(3)
        self.assertIsNone(future.worker_pid)

    def test_export_is_prepared_off_owner_but_not_published_by_worker(self):
        destination=self.root/'report.json';result=self.service.request('export',export_path=destination).result(10)
        self.assertIsInstance(result,PreparedHistoryExport);self.assertFalse(destination.exists())
        data=json.loads(result.payload);self.assertEqual(len(data['cycles']),3);self.assertEqual(data['comparisons'][0]['target_xp'],300)

    def test_query_allowlist_and_arguments(self):
        for name,params in [('close',()),('cycles',(-1,)),('cycles',(True,)),('events',(100001,)),('comparisons',(1,))]:
            with self.subTest(name=name),self.assertRaises(ValueError):self.service.request(name,params)
        with self.assertRaises(ValueError):self.service.request('export')

    def test_bounded_queue_and_close_cancel_pending_barrier(self):
        self.service.close();self.service.thread.join(3);self.service=AnalyticsService(self.root,capacity=1)
        barrier=Future();first=self.service.request('comparisons',barrier=barrier)
        end=time.monotonic()+2
        while not first.running() and time.monotonic()<end:time.sleep(.001)
        second=self.service.request('comparisons');third=self.service.request('comparisons')
        with self.assertRaisesRegex(RuntimeError,'queue is full'):third.result(1)
        at=time.perf_counter();self.service.close();self.assertLess(time.perf_counter()-at,.1)
        with self.assertRaises(CancelledError):first.result(3)
        self.assertTrue(second.cancelled())

    def test_close_terminates_its_worker_without_waiting_on_owner(self):
        future=self.service.request('comparisons');end=time.monotonic()+3
        while future.worker_pid is None and time.monotonic()<end:time.sleep(.001)
        self.assertIsNotNone(future.worker_pid)
        self.service.close()
        try:future.result(5)
        except CancelledError:pass
        self.service.thread.join(3);self.assertFalse(self.service.thread.is_alive())
