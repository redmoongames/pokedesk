"""ETA selection, safe routing, calibration provenance and immutable evaluations."""
from pathlib import Path
import copy,json,sys,tempfile,time,unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from test_grind import mon
from pokemon_red.optimizer import (make_training_plan,forecast_cycle,read_evidence,
    compatible_cycles,remaining_xp,world_key,snapshot_navigator,map_names)
from pokemon_red.planning import make_plan
from pokemon_red.run_context import build_context,planning_key
from pokemon_red.history import History,FPS
from pokemon_red.catalog import catalog,species

class OptimizerTests(unittest.TestCase):
    def setUp(self):
        self.team=[mon(25,12,'t',[84,98]),mon(19,10,'r',[33],ability_id=50),mon(21,16,'s',[64]),mon(12,14,'b',[93]),mon(56,14,'m',[2]),mon(7,14,'w',[55]),mon(1,14,'v',[22])]
        self.inv=dict(ready=True,party=self.team[:6],boxes=[dict(self.team[6],location='box')])
        self.cfg=dict(training_policy='eta',route='Route1',trainee='t',target=20,strategy='adaptive',heal_percent=40)
        self.plan=make_plan(self.inv,self.cfg,ROOT)
        self.geo=dict(farm=dict(hub='Viridian',pair=[[12,6],[13,6]],cost=[0,40]),travel_seconds=20.,preparation_seconds=30.,preparation_steps=80)
        self.empty=dict(cycles=[],battles=[])
    def record(self,xp=100,seconds=300,status='completed'):
        return dict(id=1,route='Route1',target_uid='t',status=status,target_xp=xp,game_seconds=seconds,battles=3,
            body=dict(context=build_context(ROOT,self.cfg,self.plan),team_base_fingerprint=self.plan['team_fingerprint'],clinic='Viridian',area=[[12,6],[13,6]],speed_intervals=[dict(speed=1)]))
    def test_auto_requires_world_and_fixed_route_remains_compatible(self):
        with self.assertRaisesRegex(ValueError,'карт'):make_training_plan(self.inv,dict(self.cfg,route='Auto'),ROOT)
        self.assertEqual(make_training_plan(self.inv,self.cfg,ROOT)['route'],'Route1')
    def test_eta_charges_preparation_not_just_highest_rate(self):
        def geometry(nav,route,root):return dict(self.geo,preparation_seconds=0 if route=='Route1' else 900)
        def forecast(plan,config,root,geo,evidence):
            return dict(xp_game_minute=100 if plan['route']=='Route1' else 200,remaining_game_seconds=600 if plan['route']=='Route1' else 300,evidence={'exact_cycles':0})
        with patch('pokemon_red.optimizer.routes_for',return_value=('Route1','Route2')),patch('pokemon_red.optimizer.route_geometry',side_effect=geometry),patch('pokemon_red.optimizer.forecast_cycle',side_effect=forecast):
            p=make_training_plan(self.inv,dict(self.cfg,route='Auto'),ROOT,navigator=object(),evidence=self.empty)
        self.assertEqual(p['route'],'Route1');self.assertEqual(p['selection']['mode'],'Auto');self.assertLess(p['forecast']['eta_game_seconds'],1200)
        self.assertLess(p['forecast']['xp_game_minute'],max(a['xp_game_minute'] for a in p['selection']['alternatives']))
    def test_unreachable_route_is_excluded_without_input_or_fallback(self):
        def geometry(nav,route,root):
            if route=='Route2':raise RuntimeError('Односторонний уступ')
            return self.geo
        with patch('pokemon_red.optimizer.routes_for',return_value=('Route1','Route2')),patch('pokemon_red.optimizer.route_geometry',side_effect=geometry):
            p=make_training_plan(self.inv,dict(self.cfg,route='Auto'),ROOT,navigator=object(),evidence=self.empty)
        self.assertEqual(p['route'],'Route1');self.assertIn('уступ',p['selection']['excluded'][0]['reason'])
        self.assertEqual(len(set(p['team_uids'])),len(p['team_uids']));self.assertIn('r',p['team_uids']);self.assertTrue(set(p['team_uids'])<=set(m['uid'] for m in self.team))
    def test_exact_calibration_aggregates_rewards_and_time_with_prior(self):
        raw=forecast_cycle(self.plan,self.cfg,ROOT,self.geo,self.empty)
        rows=[self.record(60,60),dict(self.record(60,180),id=2)]
        f=forecast_cycle(self.plan,self.cfg,ROOT,self.geo,dict(cycles=rows,battles=[]))
        self.assertEqual(f['evidence']['exact_cycles'],2);self.assertEqual(f['source_ids']['cycles'],[1,2])
        self.assertAlmostEqual(f['xp_game_minute'],60*(2*raw['model']['target_xp']+120)/(2*raw['model']['game_seconds']+240))
    def test_legacy_other_rules_and_other_team_cannot_calibrate(self):
        rows=[]
        for change in ('legacy','team','policy','clinic','threshold'):
            r=copy.deepcopy(self.record())
            if change=='legacy':r['body']['context']=None
            elif change=='team':r['body']['team_base_fingerprint']='other'
            elif change=='policy':r['body']['context']['versions']['policy']='other'
            elif change=='clinic':r['body']['clinic']='Pewter'
            else:r['body']['context']['rules']['heal_percent']=80
            rows.append(r)
        f=forecast_cycle(self.plan,self.cfg,ROOT,self.geo,dict(cycles=rows,battles=[]));self.assertEqual(f['evidence']['exact_cycles'],0);self.assertEqual(f['evidence']['legacy_cycles'],1)
    def test_different_mixed_and_missing_speeds_do_not_calibrate(self):
        for speeds in ([],[4],[1,8]):
            row=self.record();row['body']['speed_intervals']=[dict(speed=s) for s in speeds]
            self.assertEqual(compatible_cycles(self.plan,self.cfg,ROOT,self.geo['farm'],dict(cycles=[row])),[])
        row=self.record();self.assertEqual(len(compatible_cycles(self.plan,self.cfg,ROOT,self.geo['farm'],dict(cycles=[row]))),1)
    def test_failure_cost_is_retained_and_manual_stop_is_distinct(self):
        base=forecast_cycle(self.plan,self.cfg,ROOT,self.geo,self.empty)
        bad=forecast_cycle(self.plan,self.cfg,ROOT,self.geo,dict(cycles=[self.record(0,600,'partial:battle_lost')],battles=[]))
        manual=forecast_cycle(self.plan,self.cfg,ROOT,self.geo,dict(cycles=[self.record(0,600,'partial:script_stopped')],battles=[]))
        self.assertLess(bad['xp_game_minute'],base['xp_game_minute']);self.assertEqual(bad['evidence']['failed_cycles'],1);self.assertEqual(manual['xp_game_minute'],base['xp_game_minute'])
    def test_pp_and_healing_distance_change_predicted_rate(self):
        cfg=dict(self.cfg,trainee='s');plan=make_plan(self.inv,cfg,ROOT);base=forecast_cycle(plan,cfg,ROOT,self.geo,self.empty)
        exhausted=copy.deepcopy(plan)
        for m in exhausted['team']:
            for a in m['moves']:a['max_pp']=1
        low=forecast_cycle(exhausted,cfg,ROOT,self.geo,self.empty)
        far=forecast_cycle(plan,cfg,ROOT,dict(self.geo,travel_seconds=300),self.empty)
        self.assertLess(low['battles'],base['battles']);self.assertLess(far['xp_game_minute'],base['xp_game_minute']);self.assertGreater(far['remaining_game_seconds'],base['remaining_game_seconds'])
    def test_snapshot_key_invalidates_on_location_obstacles_and_stats_revision(self):
        world=dict(state=dict(map={'name':'Route1'},position={'x':1,'y':1}),grids={'Route1':dict(obstacles=[],trainers=[],script_triggers=[])},revision=0)
        first=planning_key(dict(self.inv,_planning=world),self.cfg)
        for change in ('position','obstacle','revision'):
            w=copy.deepcopy(world)
            if change=='position':w['state']['position']['x']=2
            elif change=='obstacle':w['grids']['Route1']['obstacles']=[[2,2]]
            else:w['revision']=1
            self.assertNotEqual(first,planning_key(dict(self.inv,_planning=w),self.cfg))
    def test_forecast_is_frozen_and_partial_end_has_no_full_cycle_error(self):
        with tempfile.TemporaryDirectory() as d:
            h=History(Path(d));s=dict(ready=True,frame=100,party=self.plan['team'],map={'name':'Route1'},battle=None);h.observe(s)
            f=forecast_cycle(self.plan,self.cfg,ROOT,self.geo,self.empty);f['eta_game_seconds']=1000
            h.training_event('training_run_start',dict(route='Route1',strategy='adaptive',trainee='t',target=20,forecast=f),s)
            h.training_event('cycle_start',dict(number=1,forecast=f),s);original=f['game_seconds'];f['game_seconds']=1
            s['frame']+=round(FPS*120);self.team[0]['experience']+=50;h.training_event('cycle_complete',{},s)
            row=h.forecast_results('t')[0];body=row['body'];self.assertEqual(body['forecast']['game_seconds'],original);self.assertAlmostEqual(body['evaluation']['actual_game_seconds'],120,places=1);self.assertEqual(body['evaluation']['actual_target_xp'],50)
            h.training_event('cycle_start',dict(number=2,forecast=f),s);s['frame']+=round(FPS*20);self.team[0]['experience']+=10;h.end_run('target_reached',s)
            row=h.forecast_results('t')[0];self.assertEqual(row['body']['evaluation']['kind'],'partial');self.assertNotIn('time_error_percent',row['body']['evaluation']);self.assertEqual(len(h.comparisons()),1)
            run=json.loads(h.db.execute('SELECT body FROM training_runs').fetchone()[0]);self.assertEqual(run['forecast']['game_seconds'],original);self.assertTrue(run['session_evaluation']['goal_reached']);self.assertAlmostEqual(run['session_evaluation']['game_seconds'],140,places=1);self.assertEqual(run['session_evaluation']['target_xp'],60);h.close()
    def test_read_evidence_does_not_open_timeline_or_end_run(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);h=History(root);s=dict(frame=1,party=self.plan['team']);h.training_event('training_run_start',dict(route='Route1',strategy='adaptive',trainee='t',target=20),s)
            before=h.db.execute('SELECT count(*) FROM timelines').fetchone()[0];read_evidence(root)
            self.assertEqual(before,h.db.execute('SELECT count(*) FROM timelines').fetchone()[0]);self.assertIsNone(h.db.execute('SELECT ended_at FROM training_runs').fetchone()[0]);h.close()
    def test_actual_rom_snapshot_only_recommends_round_trip_routes(self):
        from pokemon_red.engine import Game
        from pokemon_red.telemetry import read_map
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'Data').mkdir();(root/'Data/FireRed.gba').symlink_to(ROOT/'Data/FireRed.gba')
            for name in ('vendor','native'):(root/name).symlink_to(ROOT/name)
            with Game(root,resume=False) as game:
                world=dict(state=dict(map={'name':'Route4'},position={'x':85,'y':17}),grids={n:read_map(game,n) for n in map_names(root)})
                nav=snapshot_navigator(root,world)
                with self.assertRaises(RuntimeError):nav.plan('Route4',(85,17),'Route1',(12,0))
                p=make_training_plan(dict(self.inv,_planning=world),dict(self.cfg,route='Auto'),root,evidence=self.empty)
                self.assertEqual(p['route'],'Route4');self.assertTrue(p['selection']['excluded']);self.assertGreater(p['forecast']['eta_game_seconds'],0)

if __name__=='__main__':unittest.main()
