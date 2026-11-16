"""Goal-first planning, directed detours and nonblocking persistence contracts."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
import json,sqlite3,sys,tempfile,time,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.navigation import Navigator
from pokemon_red.map_repository import lazy_world
from pokemon_red.optimizer import snapshot_navigator
from pokemon_red.planning_state import PlanningCache
from pokemon_red.history import History
from pokemon_red.settings import Settings
from pokemon_red.audio import Playback
from pokemon_red.operations import MainOperation
from test_grind import mon

def grid(name):
    return dict(name=name,width=6,height=4,tiles=[[[0,0,3,0] for _ in range(6)] for _ in range(4)],objects=[],trainers=[],obstacles=[],script_triggers=[],warps=[])
def edge(a,b,point=(4,1),arrival=(0,1)):
    return dict(source=a,destination=b,point=list(point),arrival=list(arrival),direction='RIGHT')

class DemandPlanningTests(unittest.TestCase):
    def test_lazy_repository_does_not_read_other_maps(self):
        provider=Mock(side_effect=grid);state=dict(map={'name':'A'},position={'x':0,'y':1})
        world=lazy_world(state,'flags-1',provider);self.assertEqual(len(world['grids']),0)
        nav=snapshot_navigator(ROOT,world);nav.spec=dict(links=[edge('A','B'),edge('B','D'),edge('A','Unrelated')],hubs={})
        nav.plan('A',(0,1),'D',(3,1))
        self.assertEqual(set(c.args[0] for c in provider.call_args_list),{'A','B','D'})
        provider.reset_mock();nav.plan('A',(0,1),'D',(3,1));provider.assert_not_called()
    def test_blocked_short_corridor_expands_to_verified_detour(self):
        maps={n:grid(n) for n in ('A','B','C','D','E')};maps['B']['obstacles']=[[2,y] for y in range(4)]
        nav=snapshot_navigator(ROOT,lazy_world(dict(map={'name':'A'},position={'x':0,'y':1}),'flags',maps.__getitem__))
        nav.spec=dict(links=[edge('A','B'),edge('B','D'),edge('A','C',point=(4,2)),edge('C','E'),edge('E','D')],hubs={})
        plan=nav.plan('A',(0,1),'D',(3,1));self.assertEqual([e['destination'] for e in plan['links']],['C','E','D'])
        with self.assertRaises(RuntimeError):nav.plan('D',(3,1),'A',(0,1))
    def test_farm_geometry_survives_movement_but_flags_and_cut_invalidate(self):
        cache=PlanningCache();world=lazy_world(dict(map={'name':'A'},position={'x':0,'y':1}),'v1',grid)
        nav=SimpleNamespace(planning_world=world,cut_enabled=False);compute=Mock(return_value=[dict(pair=[[1,1],[2,1]])])
        cache.route_farms(nav,'Route1',ROOT,compute);world['state']['position']['x']=2
        cache.route_farms(nav,'Route1',ROOT,compute);self.assertEqual(compute.call_count,1)
        world['map_revision']='v2';cache.route_farms(nav,'Route1',ROOT,compute);self.assertEqual(compute.call_count,2)
        nav.cut_enabled=True;cache.route_farms(nav,'Route1',ROOT,compute);self.assertEqual(compute.call_count,3)
    def test_default_audio_off_and_explicit_choice_survives(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);settings=Settings(root);self.assertFalse(settings['sound_enabled']);settings.set('sound_enabled',True);self.assertTrue(Settings(root)['sound_enabled'])
        lib=Mock();playback=Playback(lib)
        for speed in (8,4,12,8):playback.configure(active=True,rate=32768,speed=speed,enabled=False,volume=80)
        lib.pokemon_output_open.assert_not_called();lib.pokemon_output_close.assert_not_called();playback.close()
    def test_output_device_survives_speed_switches_and_pause_closes_once(self):
        lib=Mock();playback=Playback(lib)
        for speed in (8,4,12,8,1,.5,16):
            playback.configure(active=True,rate=32768,speed=speed,enabled=True,volume=80);playback.write(b'\0\0\0\0'*400)
        lib.pokemon_output_open.assert_called_once_with(48000);lib.pokemon_output_close.assert_not_called()
        playback.configure(active=False,rate=32768,speed=8,enabled=True,volume=80);lib.pokemon_output_close.assert_called_once();playback.close()

class SemanticRevisionTests(unittest.TestCase):
    def test_step_counters_ignored_but_flags_event_variables_and_map_invalidate(self):
        from pokemon_red.planning_state import read_world_revision
        block=bytearray(0x320);map_id=bytearray(b'\0\x01');base=0x02001000
        game=SimpleNamespace(root=ROOT,_navigation_variables=(0x4050,),read32=lambda _:base)
        game.read_bytes=lambda address,size:bytes(map_id) if address==base+4 else bytes(block)
        with patch('pokemon_red.telemetry.symbols',return_value={'gSaveBlock1Ptr':123}):
            before=read_world_revision(game)
            block[0x120+(0x4021-0x4000)*2]=3
            block[0x120+(0x4022-0x4000)*2]=8
            self.assertEqual(before,read_world_revision(game))
            block[2]=1;flag=read_world_revision(game);self.assertNotEqual(before,flag)
            block[0x120+(0x4050-0x4000)*2]=4;event=read_world_revision(game);self.assertNotEqual(flag,event)
            map_id[0]=2;self.assertNotEqual(event,read_world_revision(game))
    def test_cancelled_snapshot_does_not_become_cached_blocked_route(self):
        from pokemon_red.planning_state import PlanningSnapshotExpired
        provider=Mock(side_effect=PlanningSnapshotExpired('changed'))
        nav=snapshot_navigator(ROOT,lazy_world(dict(map={'name':'A'},position={'x':0,'y':1}),'flags',provider))
        nav.spec=dict(links=[edge('A','B')],hubs={})
        with self.assertRaises(PlanningSnapshotExpired):nav.plan('A',(0,1),'B',(3,1))
        self.assertEqual(nav.path_failures,{})

class JournalTests(unittest.TestCase):
    def test_external_disk_lock_does_not_block_ui_and_order_is_durable_on_close(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);history=History(root,async_writer=True);lock=sqlite3.connect(root/'Data/history.sqlite3');lock.execute('BEGIN IMMEDIATE')
            try:
                started=time.perf_counter()
                for n in range(8):history.event('test','event '+str(n),dict(number=n))
                elapsed=time.perf_counter()-started;self.assertLess(elapsed,.05);self.assertEqual(len(history.events()),8)
            finally:lock.rollback();lock.close();history.close()
            db=sqlite3.connect(root/'Data/history.sqlite3');self.assertEqual([r[0] for r in db.execute('SELECT message FROM events ORDER BY id')],['event '+str(n) for n in range(8)]);db.close()
    def test_writer_failure_reports_once_and_retains_recovery_without_recursive_logging(self):
        from concurrent.futures import Future
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);history=History(root,async_writer=True)
            history.db.writer.close()
            future=Future();future.set_exception(OSError('disk unavailable'))
            with patch.object(history.db.writer,'submit',return_value=future):
                history.event('failed','failed batch')
            with self.assertRaisesRegex(RuntimeError,'остановлена'):history.db.check_health()
            # Error reporting and taking control may emit more events. They must
            # remain readable without throwing recursively or retrying disk IO.
            history.event('script_stopped','control returned');history.db.check_health()
            self.assertEqual(len(history.events()),2)
            from pokemon_red.file_writer import FileWriter
            history.db.writer=FileWriter();history.close()
            recovery=list((root/'Data').glob('journal-recovery-*.json'))
            self.assertEqual(len(recovery),1)
            payload=json.loads(recovery[0].read_text());self.assertGreaterEqual(len(payload['batches']),2)
    def test_completed_cycle_future_waits_for_durable_writer_without_blocking_ui(self):
        import threading
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);history=History(root,async_writer=True);gate=threading.Event();entered=threading.Event()
            history.db.writer.submit(lambda:(entered.set(),gate.wait(3)));self.assertTrue(entered.wait(1))
            try:
                team=[mon(25,12,'t',[84])];state=dict(frame=1,party=team,ready=True,map={'name':'Route1'})
                history.observe(state);history.training_event('training_run_start',dict(route='Route1',strategy='adaptive',trainee='t',target=20),state)
                history.training_event('cycle_start',dict(number=1),state);history.end_cycle('completed',state)
                self.assertFalse(history.completed_write.done());gate.set();history.completed_write.result(2)
                db=sqlite3.connect(root/'Data/history.sqlite3');self.assertEqual(db.execute('SELECT status FROM training_cycles').fetchone()[0],'completed');db.close()
            finally:gate.set();history.close()
    def test_cycle_ids_and_projection_match_durable_database(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);history=History(root,async_writer=True);team=[mon(25,12,'t',[84])];state=dict(frame=1,party=team,ready=True,map={'name':'Route1'})
            history.observe(state);history.training_event('training_run_start',dict(route='Route1',strategy='adaptive',trainee='t',target=20),state)
            history.training_event('cycle_start',dict(number=1),state);first=history.cycle['id'];revision=history.completed_revision
            state['frame']+=60;history.sync_cycle(state);self.assertEqual(history.completed_revision,revision)
            history.end_cycle('completed',state);self.assertGreater(history.completed_revision,revision);projected=history.cycles();history.close()
            db=sqlite3.connect(root/'Data/history.sqlite3');row=db.execute('SELECT id,status FROM training_cycles').fetchone();db.close();self.assertEqual(row,(first,'completed'));self.assertEqual(projected[0]['id'],first)

class PortableSessionTests(unittest.TestCase):
    def test_moving_project_preserves_job_links_and_worker_roots(self):
        import hashlib,os
        from pokemon_red.acquisition import TEMPLATE,prepare_job,AcquisitionConfig
        from pokemon_red.acquisition_worker import Worker
        from pokemon_red.operation_worker import Worker as OperationWorker
        from pokemon_red.operations import clone_session
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'Old';template=root/TEMPLATE;template.mkdir(parents=True)
            for name in ('FireRed.state','FireRed.sav','metadata.json'):(template/name).write_bytes(name.encode())
            (template/'manifest.json').write_text(json.dumps(dict(algorithm='sha256',files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in template.iterdir()})))
            for name in ('src','native','vendor','assets','runtime','Bots','Data'):(root/name).mkdir()
            (root/'Data/FireRed.gba').write_bytes(b'fixture')
            job=prepare_job(root,AcquisitionConfig(7,True));job_id=job.name
            operation=root/'Sessions/operations/op';operation.mkdir(parents=True)
            snapshot=SimpleNamespace(publish=lambda folder:None)
            clone_session(root,operation/'main',snapshot)
            (operation/'operation.json').write_text(json.dumps(dict(project=os.path.relpath(root,operation),kind='local',config={})))
            moved=root.with_name('Moved');root.rename(moved);job=moved/'Sessions/acquisition'/job_id
            from pokemon_red.paths import session_paths,LAYOUT_FILE
            self.assertFalse(Path(json.loads((job/LAYOUT_FILE).read_text())['installation']).is_absolute())
            self.assertEqual((job/'Data/FireRed.gba').read_bytes(),b'fixture')
            self.assertEqual(session_paths(moved/'Sessions/operations/op/main').installation.root,moved.resolve())
            with patch('pokemon_red.acquisition_worker.os.nice'):
                worker=Worker(job);worker.db.close()
            self.assertEqual(OperationWorker(moved/'Sessions/operations/op').project,moved.resolve())

class OperationPreparationTests(unittest.TestCase):
    def test_cancel_during_backup_never_launches_worker(self):
        from concurrent.futures import Future
        monitor=SimpleNamespace(notice='',game=SimpleNamespace(frame=10),paused=True,keys=set(),update_panel=Mock(),close_after_operation=False)
        monitor.folder=ROOT;operation=MainOperation(monitor);operation.job=Path('/private/test');operation.kind='local';operation.game=monitor.game;operation.frame=10;operation.prepare_future=Future();operation.launch=Mock()
        operation.command('cancel');operation.prepare_future.set_result(None);operation.poll();operation.launch.assert_not_called();self.assertFalse(operation.active);self.assertEqual(operation.result['status'],'cancelled')

if __name__=='__main__':unittest.main()
