"""Long-search controls use safe frontiers and explicitly accepted candidates."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import sys,unittest,tempfile,json,time,hashlib,os,signal
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.starter_search import LaneHealth,search
from pokemon_red.starter_candidates import assess
from pokemon_red.new_game_config import NewGameConfig,STATS
from pokemon_red.acquisition_play import JobPaused
from pokemon_red.engine import Game
from pokemon_red.engine_runtime import EngineRuntime
from pokemon_red.journey import Journey
from pokemon_red.prologue import Prologue

class HealthTests(unittest.TestCase):
    def test_one_stalled_lane_is_detected_while_other_lanes_progress(self):
        health=LaneHealth(2,0,timeout=15);process=SimpleNamespace(poll=lambda:None)
        health.check([dict(attempts=5),dict(attempts=5)],[process]*2,1)
        with self.assertRaises(RuntimeError):health.check([dict(attempts=5),dict(attempts=100)],[process]*2,17)
    def test_dead_lane_is_not_hidden_by_live_peers(self):
        health=LaneHealth(2,0)
        with self.assertRaises(RuntimeError):health.check([{},{}],[SimpleNamespace(poll=lambda:1),SimpleNamespace(poll=lambda:None)],1)
    def test_best_prioritizes_required_identity_and_explains_iv_shortfall(self):
        cfg=NewGameConfig.parse(dict(gender='male',natures=[10],min_ivs=[20,0,25,31,0,25]))
        mon=dict(uid='a',species_id=1,checksum_valid=True,personality=31,nature=10,shiny=False,level=5,ivs=dict(zip(STATS,[25,0,25,30,0,25])))
        best=assess(cfg,mon);self.assertEqual(best['missing'],[dict(kind='iv',stat='speed',actual=30,required=31)])
        wrong=assess(cfg,dict(mon,personality=0,ivs=dict.fromkeys(STATS,31)));self.assertIsNone(wrong)

    def test_excess_points_never_compensate_for_a_missing_target_point(self):
        cfg=NewGameConfig.parse(dict(min_ivs=[0,5,0,20,0,0]))
        mon=dict(uid='a',species_id=1,checksum_valid=True,personality=31,nature=10,shiny=False,level=5,ivs=dict(zip(STATS,[0,5,0,10,0,0])))
        old=assess(cfg,mon);worse=assess(cfg,dict(mon,ivs=dict(zip(STATS,[31,30,31,9,31,31]))));equal=assess(cfg,dict(mon,ivs=dict(zip(STATS,[31,30,31,10,31,31]))))
        self.assertEqual(old['score'],15);self.assertEqual(worse['score'],14);self.assertEqual(old['rank'],equal['rank'])
    def test_only_three_strict_record_improvements_are_retained(self):
        from pokemon_red.starter_candidates import record,load
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'Data').mkdir();cfg=NewGameConfig.parse(dict(min_ivs=[31,0,0,0,0,0]));history=[]
            for value in range(1,6):
                mon=dict(uid=str(value),species_id=1,checksum_valid=True,personality=31,nature=10,shiny=False,level=5,ivs=dict(zip(STATS,[value,31,31,31,31,31])));data=bytes([value]);candidate=dict(assess(cfg,mon),sha256=hashlib.sha256(data).hexdigest());history=record(root,history,candidate,data)
            self.assertEqual([v['score'] for v in load(root,cfg)],[5,4,3]);self.assertEqual(len(list((root/'Data/starter-candidates').glob('*.state'))),3)

    def test_orphaned_operation_cancels_without_generating_more_candidates(self):
        from pokemon_red.operation_worker import Worker
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);job=root/'Sessions/operations/job';job.mkdir(parents=True)
            (job/'operation.json').write_text(json.dumps(dict(kind='prologue',project=str(root),config={})));worker=Worker(job)
            with patch('pokemon_red.operation_worker.os.getppid',return_value=-1),self.assertRaises(JobPaused):worker.heartbeat()
            self.assertTrue(worker.cancel)

class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);(self.root/'Data').mkdir()
        for n in ('src','native','vendor','assets','runtime','Bots'):(self.root/n).symlink_to(ROOT/n)
        (self.root/'Data/FireRed.gba').symlink_to(ROOT/'Data/FireRed.gba')
        with Game(self.root,resume=False) as game:
            game.load_state(ROOT/'templates/FireRed/ALEX-before-starter-v1/FireRed.state');worker=SimpleNamespace(pacer=None,heartbeat=lambda:None,safe_point=lambda:None,update=lambda **kw:None)
            Prologue(Journey(game,worker),{}).choice();game.save_to(self.root/'Data')
        self.cfg=NewGameConfig.parse(dict(gender='male',natures=[10],shiny=False,min_ivs=[31]*6,search_workers=1))
        (self.root/'Data/new-game.json').write_text(json.dumps(dict(config=self.cfg.json(),status='paused',progress=dict(phase='search',attempts=0))))
    def actor(self):
        class Runtime(EngineRuntime):
            def _dispatch(self,c,method,args):
                if method=='probe':return args[0](c)
                return super()._dispatch(c,method,args)
        actor=Runtime(self.root,paused=True);actor.ready.result(15)
        def close():actor.take_control(close=True);actor.finished.result(20)
        self.addCleanup(close);return actor
    def until(self,actor,predicate,limit=30):
        deadline=time.monotonic()+limit
        while time.monotonic()<deadline:
            model=actor.latest
            if model and predicate(model):return model
            time.sleep(.025)
        self.fail(str(actor.latest.operation))
    def paused(self,actor):return self.until(actor,lambda m:not m.operation['active'] and m.operation.get('result',{}).get('applied') and not m.status['saving'])
    def test_pause_restart_edit_and_resume_preserve_the_opening(self):
        actor=self.actor();actor.submit('operation_begin','prologue',{}).result(10)
        first=self.until(actor,lambda m:m.operation.get('active') and m.operation.get('progress',{}).get('search',{}).get('attempts',0)>30);job=first.operation['job']
        actor.submit('operation_command','restart_search').result(5)
        second=self.until(actor,lambda m:m.operation['active'] and m.operation['job']!=job and m.operation.get('progress',{}).get('search',{}).get('attempts',0)>60)
        self.assertEqual(second.operation['progress']['prologue']['phase'],'search')
        actor.submit('operation_command','pause').result(5);self.paused(actor)
        best=json.loads((self.root/'Data/starter-best.json').read_text());self.assertEqual(hashlib.sha256((self.root/'Data/starter-best.state').read_bytes()).hexdigest(),best['sha256'])
        with self.assertRaises(ValueError):actor.submit('prologue_config',dict(player_name='OTHER')).result(5)
        actor.submit('prologue_config',dict(shiny=False,nature=None,natures=[],gender='any',min_ivs=[0]*6)).result(5)
        marker=actor.submit('prologue_config').result(5);self.assertEqual(marker['progress']['phase'],'search');self.assertEqual(marker['config']['player_name'],'ALEX')
        actor.submit('operation_begin','prologue',{}).result(10)
        done=self.until(actor,lambda m:not m.operation['active'] and (m.operation.get('result') or {}).get('status')=='ready',35)
        self.assertTrue(done.operation['result']['applied']);self.assertEqual(done.state['map']['name'],'PalletTown')
    def test_best_can_only_complete_after_explicit_acceptance(self):
        actor=self.actor();actor.submit('operation_begin','prologue',{}).result(10)
        self.until(actor,lambda m:bool(m.operation.get('progress',{}).get('search',{}).get('best')))
        actor.submit('operation_command','pause').result(5);self.paused(actor)
        history=json.loads((self.root/'Data/starter-candidates.json').read_text());best=history[-1];self.assertFalse(self.cfg.matches(best['pokemon']))
        actor.submit('operation_begin','prologue',dict(use_best=True,candidate_sha=best['sha256'])).result(10)
        done=self.until(actor,lambda m:not m.operation['active'] and (m.operation.get('result') or {}).get('status')=='ready',35)
        self.assertEqual(actor.submit('prologue_config').result(5)['status'],'complete');self.assertTrue(done.operation['result']['applied']);self.assertEqual(done.state['party'][0]['uid'],best['pokemon']['uid']);self.assertEqual(done.operation['result']['result']['prologue']['accepted_uid'],best['pokemon']['uid'])
    def test_nonresponsive_operation_is_recovered_after_pause(self):
        actor=self.actor();actor.submit('operation_begin','prologue',{}).result(10)
        self.until(actor,lambda m:m.operation.get('active') and m.operation.get('progress',{}).get('search',{}).get('attempts',0)>30)
        pid=actor.submit('probe',lambda c:c.operation.process.pid).result(5);os.kill(pid,signal.SIGSTOP)
        began=time.monotonic();actor.submit('operation_command','pause').result(5);paused=self.paused(actor)
        self.assertLess(time.monotonic()-began,12);self.assertEqual(paused.operation['result']['status'],'paused')
        self.assertFalse(paused.state['party']);self.assertEqual(actor.submit('prologue_config').result(5)['progress']['phase'],'search')
        actor.submit('operation_begin','prologue',{}).result(10)
        self.until(actor,lambda m:m.operation.get('active') and m.operation.get('progress',{}).get('search',{}).get('attempts',0)>20)
        actor.submit('operation_command','pause').result(5);self.paused(actor)
    def test_resume_after_manual_gift_restores_verified_pre_gift_snapshot(self):
        actor=self.actor();actor.submit('operation_begin','prologue',{}).result(10)
        self.until(actor,lambda m:m.operation.get('active') and m.operation.get('progress',{}).get('search',{}).get('attempts',0)>30)
        actor.submit('operation_command','pause').result(5);self.paused(actor)
        def receive(c):
            c.game.press('A',frames=2,release_frames=60)
            return bool(Journey(c.game,SimpleNamespace()).state()['party'])
        self.assertTrue(actor.submit('probe',receive).result(5))
        actor.submit('operation_begin','prologue',{}).result(10)
        self.until(actor,lambda m:m.operation.get('active') and m.operation.get('progress',{}).get('search',{}).get('attempts',0)>100)
        actor.submit('operation_command','pause').result(5);done=self.paused(actor)
        self.assertFalse(done.state['party']);self.assertEqual(done.operation['result']['status'],'paused')
    def test_frozen_native_lane_is_killed_and_leaves_a_valid_frontier(self):
        frozen=[];health=LaneHealth(4,time.monotonic(),timeout=1)
        def update(**kw):
            if frozen or kw.get('search',{}).get('attempts',0)<10:return
            from pokemon_red.paths import session_paths
            folder=next((session_paths(self.root).workspaces.root/'search-workers').iterdir());p=json.loads((folder/'0/progress.json').read_text());os.kill(p['pid'],signal.SIGSTOP);frozen.append(p['pid'])
        worker=SimpleNamespace(safe_point=lambda:None,update=update,accept_best=False)
        with Game(self.root) as game,patch('pokemon_red.starter_search.LaneHealth',return_value=health):
            with self.assertRaises(RuntimeError):search(game,__import__('dataclasses').replace(self.cfg,search_workers=4),worker,dict(attempts=0))
            self.assertFalse(Journey(game,SimpleNamespace()).state()['party'])
        self.assertEqual(len(frozen),1)
        with self.assertRaises(ProcessLookupError):os.kill(frozen[0],0)

class ContextTests(unittest.TestCase):
    def test_progress_editor_and_confirmation_reuse_the_same_context_frame(self):
        import tkinter as tk
        from concurrent.futures import Future
        from unittest.mock import Mock
        from pokemon_red.automation_context import AutomationContext
        root=tk.Tk();root.withdraw()
        try:
            cfg=NewGameConfig.parse(dict(gender='male',natures=[10],min_ivs=[20,0,25,31,0,25],search_workers=4))
            mon=dict(uid='a',species_id=1,checksum_valid=True,personality=31,nature=10,shiny=False,level=5,ivs=dict(zip(STATS,[25,0,25,30,0,25])))
            best=dict(assess(cfg,mon),sha256='a'*64);marker=dict(config=cfg.json(),status='paused',progress=dict(phase='search'),best=best);submitted=[]
            def submit(method,*args):
                submitted.append((method,args));future=Future()
                if args:marker['config'].update(args[0])
                future.set_result(marker);return future
            op=SimpleNamespace(data=dict(active=True,job='one',kind='prologue',progress=dict(prologue=dict(phase='search',attempts=100),search=dict(attempts=100,seconds=1,rate=100,workers=4,best=best))),active=True,command=Mock(),begin=Mock())
            m=SimpleNamespace(operation=op,runtime=SimpleNamespace(submit=submit),watch=lambda f,success,failure:success(f.result()),prologue_marker=marker,automation=SimpleNamespace(running=False,info=lambda:dict(running=False)),status={},last_state={},pending_start=False,history=SimpleNamespace(meta={}))
            panel=SimpleNamespace(window=root,monitor=m);view=AutomationContext(panel);view.frame.pack();before=[w for w in root.winfo_children() if isinstance(w,tk.Toplevel)]
            self.assertTrue(view.wants());view.update({});self.assertIn('100',view.metrics.cget('text'));self.assertIn('30',view.best_label.cget('text'))
            view.ask_best();op.command.assert_called_with('pause');view.pending=None;op.active=False;view.ask_best();self.assertTrue(view.confirm.winfo_manager());view.dismiss_confirm();op.active=True;view.edit();op.command.assert_called_with('pause')
            op.data=dict(active=False,result=dict(kind='prologue',prologue=dict(phase='search')));op.active=False;view.update({});self.assertIsNotNone(view.editor)
            view.ivs['speed'].set(20);view.save_editor();self.assertTrue(any(method=='prologue_config' and args and args[0]['min_ivs'][3]==20 for method,args in submitted));op.begin.assert_called_with('prologue',{})
            self.assertEqual([w for w in root.winfo_children() if isinstance(w,tk.Toplevel)],before)
        finally:root.destroy()

    def test_other_automation_does_not_show_an_old_starter_result(self):
        import tkinter as tk
        from pokemon_red.automation_context import AutomationContext
        root=tk.Tk();root.withdraw()
        try:
            m=SimpleNamespace(operation=SimpleNamespace(data=dict(active=False,result=dict(kind='prologue',stage='OLD RESULT'))),automation=SimpleNamespace(running=True,info=lambda:dict(running=True,reason='TRAINING',stage='ROUTE')),status={},last_state={},pending_start=False,prologue_marker=None,history=SimpleNamespace(meta={}))
            view=AutomationContext(SimpleNamespace(window=root,monitor=m));self.assertTrue(view.wants());view.update({});self.assertEqual(view.stage.cget('text'),'TRAINING');self.assertEqual(view.metrics.cget('text'),'ROUTE')
        finally:root.destroy()
