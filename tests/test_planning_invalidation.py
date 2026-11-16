"""Planning dependencies: moving NPCs, story changes and independent stages."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
import sys,unittest

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.planning_state import planning_grid,planning_world,geometry_key,PlanningCache
from pokemon_red.optimizer import world_key,make_training_plan
from pokemon_red.navigation import Navigator
from pokemon_red.training import TrainingProblem,path_to
from pokemon_red.training_view import TrainingSetup
from pokemon_red.run_context import planning_key
from test_grind import mon


def world():
    obj=dict(local_id=1,x=3,y=1,anchor_x=2,anchor_y=1,movement=2,range_x=1,range_y=0,flag=0)
    trainer=dict(local_id=2,x=6,y=1,anchor_x=6,anchor_y=1,movement=1,sight=2,defeated=False,facing=1)
    grid=dict(name='Route1',width=9,height=3,tiles=[[[0,0,3,0] for _ in range(9)] for _ in range(3)],objects=[obj],obstacles=[[3,1],[6,1],[8,1]],trainers=[trainer],script_triggers=[],warps=[])
    return dict(state=dict(map={'name':'Route1'},position={'x':0,'y':0}),grids={'Route1':grid},revision=0,speed=1)


class InvalidationTests(unittest.TestCase):
    def test_idle_npc_motion_preserves_key_and_conservative_occupancy(self):
        old=world();new=deepcopy(old);g=new['grids']['Route1']
        g['objects'][0]['x']=1;g['obstacles'][0]=[1,1];g['trainers'][0]['facing']=4
        self.assertEqual(world_key(old),world_key(new))
        canonical=planning_grid(g)
        self.assertTrue({(1,1),(2,1),(3,1),(8,1)}<=set(map(tuple,canonical['obstacles'])))
        self.assertEqual(new['grids']['Route1']['objects'][0]['x'],1)
        inv=dict(party=[mon(25,12,'t',[84])],boxes=[],_planning=old)
        cfg=dict(trainee='t',route='Auto',target=20)
        self.assertEqual(planning_key(inv,cfg),planning_key(dict(inv,_planning=new),cfg))

    def test_story_obstacle_trainer_and_position_invalidate_geometry(self):
        initial=world();first=geometry_key(initial)
        for change in ('story','trainer','tree','position','unknown_obstacle'):
            w=deepcopy(initial);g=w['grids']['Route1']
            if change=='story':g['script_triggers']=[[4,1]]
            elif change=='trainer':g['trainers'][0]['defeated']=True
            elif change=='tree':g['objects']=[]
            elif change=='position':w['state']['position']['x']=1
            else:g['obstacles'].append([7,2])
            self.assertNotEqual(first,geometry_key(w),change)
        for field in ('speed','revision'):
            w=deepcopy(initial);w[field]=8
            self.assertEqual(first,geometry_key(w));self.assertNotEqual(world_key(initial),world_key(w))

    def test_bulk_reachability_skips_diagnosis_but_explicit_diagnosis_remains(self):
        t=SimpleNamespace(root=ROOT,bot=SimpleNamespace(map=lambda _:world()['grids']['Route1']),state=lambda:world()['state'])
        nav=Navigator(t);nav.spec={'links':[],'hubs':{'remote':{'map':'Elsewhere','nurse':[0,0]}}}
        with patch('pokemon_red.navigation.path_block_reason',side_effect=AssertionError('expensive diagnosis in enumeration')):
            with self.assertRaises(TrainingProblem):nav.nearest_clinic()
        nav.spec={'links':[]};grid=world()['grids']['Route1'];grid['obstacles']=[[4,y] for y in range(3)];grid['objects']=[];grid['trainers']=[]
        nav.grids={'Route1':grid}
        with patch('pokemon_red.navigation.path_block_reason',return_value='Explicit blocked connection') as diagnose:
            with self.assertRaisesRegex(TrainingProblem,'Explicit blocked connection'):nav.plan('Route1',(0,0),'Route1',(8,0))
            diagnose.assert_called_once()

    def test_clinic_failure_reports_blocked_onward_road_when_clinic_is_reachable(self):
        t=SimpleNamespace(root=ROOT,bot=SimpleNamespace(map=Mock()),state=lambda:world()['state'])
        nav=Navigator(t);nav.spec=dict(links=[],hubs={'local':dict(map='Clinic',nurse=[0,0])})
        nav.clinic_lower_bounds=Mock(return_value={'local':0});nav.current_plan=Mock(return_value=dict(cost=(0,2)))
        nav.plan=Mock(side_effect=TrainingProblem('blocked','Проход занят зоной движения NPC · Маршрут 13'))
        with self.assertRaisesRegex(TrainingProblem,'Маршрут 13'):nav.nearest_clinic(('End',None))
        self.assertEqual(nav.nearest_clinic()[0],'local')

    def test_unchanged_save_flags_do_not_schedule_another_map_scan(self):
        setup=object.__new__(TrainingSetup);setup.monitor=SimpleNamespace(planning_revision=lambda:'same',folder=ROOT)
        setup.closed=False;setup.world=world();setup.world_revision='same';setup.header=Mock()
        with patch('pokemon_red.telemetry.read_map') as read:setup.collect_world()
        setup.header.after.assert_not_called();read.assert_not_called()

    def test_world_generation_is_small_and_changed_flags_reject_map_request(self):
        from concurrent.futures import Future
        from pokemon_red.planning_state import PlanningSnapshotExpired
        setup=object.__new__(TrainingSetup);future=Future();callbacks=[]
        setup.monitor=SimpleNamespace(folder=ROOT,planning_revision=lambda:'old',planning_map=Mock(return_value=future),watch=lambda f,s,e:callbacks.append(e))
        setup.closed=False;setup.world=None;setup.header=Mock();setup.signature='old';setup.planner=Mock()
        with patch('pokemon_red.telemetry.read_map') as read:
            setup.collect_world();self.assertEqual(setup.world['grids'],{})
            self.assertIs(setup.read_planning_map('Route1'),future);read.assert_not_called()
            error=PlanningSnapshotExpired('Изменились препятствия');future.set_exception(error);callbacks[0](error)
            self.assertIsNone(setup.world);self.assertIsNone(setup.signature)

    def test_direct_start_cannot_use_a_retained_preview_while_update_is_pending(self):
        setup=object.__new__(TrainingSetup);setup.monitor=Mock()
        setup.plan={'old':'preview'};setup.signature='new';setup.display_key='old'
        setup.current_config=Mock(return_value={});setup.refresh=Mock();setup.status=Mock()
        with patch('pokemon_red.training_view.validate_start'):
            setup.run()
        setup.monitor.start_bot.assert_not_called();setup.refresh.assert_called_once()


class StageCacheTests(unittest.TestCase):
    def test_forecast_edits_reuse_geometry_and_matchups_and_movement_reuses_matchups(self):
        from pokemon_red.coverage import matchup_rows
        team=[mon(25,12,'t',[84,98]),mon(19,10,'r',[33],ability_id=50),mon(21,16,'s',[64])]
        inv=dict(ready=True,party=team,boxes=[],field_badges=[],_planning=world())
        cfg=dict(trainee='t',route='Route1',target=20);cache=PlanningCache()
        geo=dict(farm=dict(hub='Viridian',pair=[[1,1],[2,1]],cost=[0,40]),travel_seconds=20.,preparation_seconds=30.,preparation_steps=80,required_tools=[])
        with patch('pokemon_red.optimizer._route_geometry',return_value=geo) as geometry,patch('pokemon_red.coverage.matchup_rows',wraps=matchup_rows) as battles:
            first=make_training_plan(inv,cfg,ROOT,cache=cache,evidence={})
            inv['_planning']['speed']=2.75;inv['_planning']['revision']=3
            updated=make_training_plan(inv,dict(cfg,target=22),ROOT,cache=cache,evidence={})
            self.assertEqual(geometry.call_count,1);self.assertEqual(battles.call_count,3)
            self.assertEqual(updated['forecast']['speed'],2.75);self.assertEqual(updated['target'],22)
            self.assertEqual(first['route'],updated['route'])
            inv['_planning']['state']['position']['x']=1
            make_training_plan(inv,cfg,ROOT,cache=cache,evidence={})
            self.assertEqual(geometry.call_count,2);self.assertEqual(battles.call_count,3)
            team[0]['stats']['special_attack']+=1
            make_training_plan(inv,cfg,ROOT,cache=cache,evidence={})
            self.assertEqual(geometry.call_count,2);self.assertEqual(battles.call_count,4)

    def test_cut_changes_and_cached_failures_remain_safe_and_bounded(self):
        cache=PlanningCache(limit=2);inv=dict(party=[],boxes=[],field_badges=[2])
        nav=SimpleNamespace(tool_inventory=inv,cut_enabled=False,planning_world=planning_world(world()))
        fail=Mock(side_effect=TrainingProblem('blocked','Still blocked'))
        for _ in range(2):
            with self.assertRaisesRegex(TrainingProblem,'Still blocked'):cache.route_geometry(nav,'Route1',ROOT,fail)
        fail.assert_called_once()
        inv['party']=[mon(19,10,'cut',[15])];nav.cut_enabled=True
        success=Mock(return_value={'cost':[1,2]})
        value=cache.route_geometry(nav,'Route1',ROOT,success);value['cost'][0]=99
        self.assertEqual(cache.route_geometry(nav,'Route1',ROOT,success)['cost'][0],1)
        cache.route_geometry(nav,'Route2',ROOT,success)
        self.assertEqual(len(cache.geometry),2)


if __name__=='__main__':unittest.main()
