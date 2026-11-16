"""Regression contracts for the architecture/UX audit, without touching live saves."""
from pathlib import Path
import copy,json,sqlite3,tempfile,time,threading,unittest
from unittest.mock import patch
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from test_grind import mon
from pokemon_red.history import History,FPS
from pokemon_red.run_context import RunConfig,build_context,comparison_key,team_fingerprint
from pokemon_red.planning import make_plan
from pokemon_red.planning_service import PlanningService
from pokemon_red.presentation import present,RunState
from pokemon_red.database import connect,SCHEMA_VERSION

class AuditDataTests(unittest.TestCase):
    def test_load_any_frame_forks_before_accepting_xp_and_keeps_old_partial_gain(self):
        for destination in (20,120,220):
            with self.subTest(destination=destination),tempfile.TemporaryDirectory() as d:
                h=History(Path(d));m=mon(25,12,'t',[84]);m['experience']=100
                battle=dict(outcome=0,enemies=[dict(battler=1,species_id=19,species='RATTATA',level=3)])
                s=dict(ready=True,frame=100,party=[m],map={'name':'Route1'},battle=battle);h.observe(s)
                h.training_event('training_run_start',dict(route='Route1',strategy='adaptive',trainee='t',target=15),s);h.training_event('cycle_start',dict(number=1),s)
                m['experience']=110;s['frame']=120;h.observe(s);before=h.timeline_id
                h.change_timeline('load_slot','other-slot');m['experience']=500;s.update(frame=destination,battle=None);h.observe(s)
                self.assertNotEqual(before,h.timeline_id);self.assertEqual(len(h.rows()),1);self.assertEqual(h.rows()[0]['xp'],10);self.assertTrue(h.rows()[0]['detail']['interrupted']);self.assertEqual(h.cycles()[0]['target_xp'],10);self.assertEqual(h.comparisons(),[])
                self.assertEqual(h.db.execute('SELECT parent_id FROM timelines WHERE id=?',(h.timeline_id,)).fetchone()[0],before);h.close()
    def test_context_separates_items_thresholds_and_versions_and_marks_legacy(self):
        team=[mon(25,12,'t',[84]),mon(19,10,'r',[33],ability_id=50)];inv=dict(ready=True,party=team,boxes=[]);cfg=dict(route='Route1',trainee='t',target=20,heal_percent=40)
        plan=make_plan(inv,cfg,ROOT);ctx=build_context(ROOT,cfg,plan);base=team_fingerprint(team);key=comparison_key(base,ctx,'Viridian',[[1,2],[2,2]])
        equipped=copy.deepcopy(team);equipped[0]['held_item']=197;self.assertNotEqual(team_fingerprint(equipped),base)
        for change in ('threshold','version','role'):
            other=copy.deepcopy(ctx)
            if change=='threshold':other['rules']['heal_percent']=80
            elif change=='version':other['versions']['policy']='different'
            else:other['roles']['runner']='t'
            self.assertNotEqual(key,comparison_key(base,other,'Viridian',[[1,2],[2,2]]))
        with tempfile.TemporaryDirectory() as d:
            h=History(Path(d));s=dict(ready=True,frame=1,party=team,map={'name':'Route1'},battle=None);h.observe(s)
            for number,context in enumerate((None,ctx,dict(ctx,rules=dict(ctx['rules'],heal_percent=80))),1):
                h.training_event('training_run_start',dict(route='Route1',strategy='adaptive',trainee='t',target=20,context=context),s);h.training_event('cycle_start',dict(number=number,clinic='Viridian',area=[[1,2],[2,2]]),s);s['frame']+=round(FPS*60);team[0]['experience']+=60;h.training_event('cycle_complete',{},s);h.end_run('done',s)
            rows=h.comparisons();self.assertEqual(len(rows),3);self.assertEqual(sum(r['context_complete'] for r in rows),2)
            out=Path(d)/'export.json';h.export(out);self.assertEqual(len(json.loads(out.read_text())['cycles']),3);h.close()
    def test_effective_stats_cohort_does_not_fragment_on_latent_evs(self):
        a=mon(25,12,'t',[84]);a['evs']={'speed':0};a['friendship']=70;first=team_fingerprint([a]);a['evs']['speed']=3;a['friendship']=71;self.assertEqual(first,team_fingerprint([a]));a['moves']=[dict(id=216,name='RETURN',pp=20,max_pp=20)];first=team_fingerprint([a]);a['friendship']=100;self.assertNotEqual(first,team_fingerprint([a]))
    def test_latest_context_uses_end_timestamp_and_real_speed_is_explicit(self):
        with tempfile.TemporaryDirectory() as d:
            h=History(Path(d));m=mon(25,12,'t',[84]);s=dict(ready=True,frame=1,party=[m],map={'name':'Route1'},battle=None);h.observe(s,speed=1)
            h.training_event('training_run_start',dict(route='Route1',strategy='adaptive',trainee='t',target=20),s)
            for number,clinic,date in [(1,'Viridian','2026-11-01T00:00:00+00:00'),(2,'Pewter','2026-11-02T00:00:00+00:00'),(3,'Viridian','2026-11-03T00:00:00+00:00')]:
                h.training_event('cycle_start',dict(number=number,clinic=clinic,area=[[1,2],[2,2]]),s);s['frame']+=round(FPS*60);m['experience']+=10;h.observe(s,speed=8)
                with patch('pokemon_red.history.now',return_value=date):h.training_event('cycle_complete',{},s)
            latest=max(h.comparisons(),key=lambda r:r['last_sample_at']);self.assertEqual(latest['clinic'],'Viridian');self.assertEqual(latest['cycles'],2);self.assertEqual(latest['speeds'],[1,8]);self.assertEqual(latest['speed_note'],'разные скорости');h.close()
    def test_migration_preserves_existing_data_and_rejects_newer_schema(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'Data').mkdir();p=root/'Data/history.sqlite3';old=sqlite3.connect(p);old.execute('CREATE TABLE sentinel (value TEXT)');old.execute("INSERT INTO sentinel VALUES('keep')");old.commit();old.close()
            db=connect(root);self.assertEqual(db.execute('SELECT value FROM sentinel').fetchone()[0],'keep');self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],SCHEMA_VERSION)
            backups=list((root/'Data/backups/database').glob('*.sqlite3'));self.assertEqual(len(backups),1)
            with sqlite3.connect(backups[0]) as backup:self.assertEqual(backup.execute('SELECT value FROM sentinel').fetchone()[0],'keep')
            db.execute('PRAGMA user_version=999');db.close()
            with self.assertRaisesRegex(RuntimeError,'новой'):connect(root)
    def test_renamed_script_can_request_training_guards(self):
        from pokemon_red.automation import Automation,Request
        with tempfile.TemporaryDirectory() as d:
            controller=Automation(Path(d),snapshot=lambda:{},checkpoint=lambda _:None,set_speed=lambda _:None,release=lambda:None)
            request=Request(object(),'safety_profile',dict(profile='training'));controller._dispatch(request);self.assertEqual(controller.safety_profile,'training');self.assertTrue(request.done.is_set());controller.close()
    def test_attention_presentation_wins_over_generic_validation(self):
        for paused in (False,True):
            view=present(dict(running=False,status='attention',reason='Выбери приём'),paused,8,'Сначала закончи бой');self.assertEqual(view.state,RunState.ATTENTION);self.assertEqual(view.message,'Выбери приём');self.assertIn('вручную',view.primary)
        self.assertIn('8×',present(dict(running=True,status='running'),True,8).secondary)

class PlannerTests(unittest.TestCase):
    def test_real_planner_subprocess_returns_serializable_snapshot(self):
        team=[mon(25,12,'t',[84]),mon(19,10,'r',[33],ability_id=50)];service=PlanningService()
        try:
            service.request('real',dict(ready=True,party=team,boxes=[]),dict(route='Route1',trainee='t',target=20),ROOT);deadline=time.monotonic()+5
            while (result:=service.poll()) is None and time.monotonic()<deadline:time.sleep(.01)
            self.assertIsNotNone(result);self.assertIsNone(result[1]);self.assertEqual(result[0]['trainee'],'t');self.assertNotEqual(service.process.pid,__import__('os').getpid())
        finally:service.close()

    def test_latest_only_coalesces_and_does_not_publish_stale_result(self):
        gate=threading.Event();entered=threading.Event();calls=[]
        def compute(inv,cfg,root):
            calls.append(cfg['id'])
            if cfg['id']=='A':entered.set();gate.wait(2)
            return cfg['id']
        service=PlanningService(compute)
        try:
            service.request('A',{},dict(id='A'),ROOT);self.assertTrue(entered.wait(1));service.request('B',{},dict(id='B'),ROOT);service.request('C',{},dict(id='C'),ROOT);self.assertIsNone(service.poll());gate.set();deadline=time.monotonic()+2
            while (result:=service.poll()) is None and time.monotonic()<deadline:time.sleep(.005)
            self.assertEqual(result,('C',None));self.assertEqual(calls,['A','C']);service.request('A',{},dict(id='A'),ROOT);self.assertEqual(service.poll(),('A',None))
        finally:gate.set();service.close()

class WidgetTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        self.tk=tk
        try:self.root=tk.Tk()
        except tk.TclError as error:self.skipTest(str(error))
        self.root.withdraw()
    def tearDown(self):
        if hasattr(self,'root'):
            self.root.destroy()
            import gc
            gc.collect()
    def test_icon_has_real_geometry_and_select_keyboard_focus_returns(self):
        from pokemon_red.ui import IconButton,Select
        root=self.root;root.deiconify();root.configure(bg='#101720');gear=IconButton(root,'⚙',width=38,height=38);gear.pack();v=self.tk.StringVar(value='Route1');select=Select(root,v,['Route1','Route2','Route3']);select.pack();root.update()
        self.assertFalse(any(gear.type(item)=='text' and gear.itemcget(item,'text')=='…' for item in gear.find_all()));self.assertGreater(len(gear.find_all()),2)
        select.focus_force();root.update();select.event_generate('<Return>',when='now');root.update();lb=select.listing;self.assertIs(root.focus_get(),lb);lb.event_generate('<Down>',when='now');lb.event_generate('<Return>',when='now');root.update();self.assertEqual(v.get(),'Route2');
        # Cocoa focus events are asynchronous; await the outcome instead of a fixed 80 ms.
        deadline=time.monotonic()+1
        while root.focus_get() is not select and time.monotonic()<deadline:root.update();time.sleep(.005)
        self.assertIs(root.focus_get(),select);select.open();root.update();select.popup.event_generate('<Escape>',when='now');root.update();self.assertIsNone(select.popup)

    def test_training_preview_is_responsive_and_attention_is_sticky(self):
        from types import SimpleNamespace
        from pokemon_red.training_view import TrainingSetup
        root=self.root;root.deiconify();root.geometry('540x800');root.configure(bg='#101720')
        team=[mon(11,8,'t',[106]),mon(19,10,'r',[33],ability_id=50),mon(25,14,'p',[84]),mon(21,16,'s',[64]),mon(12,14,'b',[93]),mon(56,14,'m',[2])]
        inventory=dict(ready=True,party=team,boxes=[]);info=dict(running=False,status='idle',stage=None)
        state=dict(ready=True,in_battle=False,map={'name':'Route1'},controls=dict(callback='CB2_Overworld',field_locked=False),party=team)
        monitor=SimpleNamespace(folder=ROOT,last_inventory=inventory,last_state=state,inventory_snapshot=lambda:inventory,settings={'speed':8},paused=False,automation=SimpleNamespace(info=lambda:info),history=SimpleNamespace(stats_revision=0,run=None,comparisons=lambda:[]))
        panel=SimpleNamespace(monitor=monitor,inspect_uid=lambda *a:None);parent=self.tk.Frame(root,bg='#101720');parent.pack(fill='both',expand=True);setup=TrainingSetup(panel,parent)
        try:
            setup.refresh(state);root.update()
            self.assertFalse(setup.team_frame.winfo_manager());self.assertFalse(setup.explanation_button.winfo_manager())
            setup.trainee.set('t');setup.route.set('Route3');setup.target.set(20);deadline=time.monotonic()+5
            while not setup.plan and time.monotonic()<deadline:root.update();time.sleep(.01)
            self.assertIsNotNone(setup.plan,setup.error);self.assertEqual(len(setup.team_cards),6);self.assertEqual(setup.columns,3);self.assertLess(setup.measured.winfo_rooty(),setup.setup.winfo_rooty())
            for frame in setup.team_cells:
                for child in frame.winfo_children():
                    if isinstance(child,self.tk.Label) and child.cget('text'):self.assertGreaterEqual(child.winfo_width(),child.winfo_reqwidth(),child.cget('text'))
            cfg=setup.current_config();cfg['allow_two_hits']=False;cfg['target']=99;preview=dict(setup.plan,target=99);monitor.history.run=dict(id='sdk-run',context=build_context(ROOT,cfg,preview),preview=preview);info.update(running=True,status='running');setup.refresh(state);root.update();self.assertEqual(setup.target.get(),99);self.assertFalse(setup.allow_two_hits.get());self.assertEqual(setup.two_hit_toggle.cget('state'),'disabled');self.assertTrue(setup.setup.winfo_ismapped());self.assertEqual(setup.choose_button.cget('state'),'disabled');self.assertFalse(setup.choose_button.winfo_manager());self.assertFalse(setup.start.winfo_manager());self.assertFalse(setup.team_frame.winfo_manager());monitor.history.run=None
            info.update(running=False,status='attention',reason='Выбери новый приём');state['in_battle']=True;setup.refresh(state);self.assertEqual(setup.status.cget('text'),'Выбери новый приём');self.assertTrue(setup.choose_button.winfo_manager());self.assertTrue(setup.start.winfo_manager());self.assertTrue(setup.team_frame.winfo_manager())
            order=parent.pack_slaves();self.assertLess(order.index(setup.team_head),order.index(setup.team_frame));self.assertLess(order.index(setup.team_frame),order.index(setup.estimate))
        finally:setup.close()
