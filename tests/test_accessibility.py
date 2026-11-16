"""Unlocking is proved by current collisions, save flags and safe round trips."""
from pathlib import Path
from types import SimpleNamespace
import json,sys,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.engine import Game
from pokemon_red.telemetry import visible_objects,read_map
from pokemon_red.training import path_to,TrainingProblem,RouteTrainer
from pokemon_red.navigation import Navigator,path_block_reason,grass_block_reason
from pokemon_red.zones import zone_spec
from pokemon_red.planning_service import PlanningService

class AccessibilityTests(unittest.TestCase):
    def test_temp_flag_does_not_unlock_tree_on_another_map(self):
        trees=[dict(local_id=1,graphics_id=95,x=2,y=2,flag=0x12),dict(local_id=2,x=5,y=5,flag=0x21)]
        self.assertEqual(visible_objects(trees,current=True,flag_set=lambda _:True),[])
        off=visible_objects(trees,current=False,flag_set=lambda _:True)
        self.assertEqual([o['local_id'] for o in off],[1])
    def test_permanent_story_flag_relocates_blocker_but_live_position_wins(self):
        obj=dict(local_id=1,x=31,y=12,flag=0);rule=dict(local_id=1,flag_unset=0x2a0,x=30,y=12,reason='S.S. Ticket')
        get=lambda flag:False
        self.assertEqual(visible_objects([obj],current=False,flag_set=get,rules=[rule])[0]['x'],30)
        self.assertEqual(visible_objects([obj],current=False,flag_set=lambda _:True,rules=[rule])[0]['x'],31)
        self.assertEqual(visible_objects([obj],current=True,flag_set=get,rules=[rule],live={1:dict(x=29,y=12)})[0]['x'],29)
    def test_warp_is_not_a_transit_tile(self):
        grid=dict(name='Test',width=5,height=1,tiles=[[[0,0,3,0] for _ in range(5)]],obstacles=[],warps=[dict(x=2,y=0)])
        with self.assertRaises(RuntimeError):path_to(grid,(0,0),(4,0))
    def test_cut_diagnosis_requires_proof_and_does_not_modify_grid(self):
        grid=dict(name='Route9',width=5,height=1,tiles=[[[0,0,3,0] for _ in range(5)]],obstacles=[[2,0]],objects=[dict(x=2,y=0,graphics_id=95)])
        before=json.dumps(grid);self.assertIn('Cut',path_block_reason(grid,(0,0),(4,0)));self.assertEqual(json.dumps(grid),before)
    def test_real_routes_five_to_eleven_all_have_clinic_round_trip_after_manual_clear(self):
        spec=zone_spec(ROOT)
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'Data').mkdir();(root/'Data/FireRed.gba').symlink_to(ROOT/'Data/FireRed.gba')
            for n in ('native','vendor'):(root/n).symlink_to(ROOT/n)
            with Game(root,resume=False) as game:
                for n in range(5,12):
                    key='Route'+str(n);r=spec['zones'][key];hub=spec['hubs'][r['hubs'][0]]
                    def read(name):
                        g=read_map(game,name);return dict(g,obstacles=g['signs'],objects=[],trainers=[],script_triggers=[])
                    t=SimpleNamespace(root=root,bot=SimpleNamespace(map=read),state=lambda:dict(map={'name':hub['map']},position={'x':7,'y':4}))
                    farm=Navigator(t).choose_farm(key)
                    self.assertGreaterEqual(farm['length'],3);self.assertTrue(farm['continuous'])
                    self.assertTrue(Navigator(t).plan(farm['map'],farm['pair'][0],spec['hubs'][farm['hub']]['map'],[7,4])['links'])
    def test_manual_cut_is_required_for_route_eight_fenced_grass(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'Data').mkdir();(root/'Data/FireRed.gba').symlink_to(ROOT/'Data/FireRed.gba')
            for n in ('native','vendor'):(root/n).symlink_to(ROOT/n)
            with Game(root,resume=False) as game:
                grid=read_map(game,'Route8');grid=dict(grid,trainers=[],script_triggers=[])
                # No trainer sight; still blocked by the actual fenced Cut trees.
                self.assertIn('Cut',grass_block_reason(grid,(71,10),None,'grass'))
    def test_unexpected_map_change_returns_before_next_button(self):
        t=object.__new__(RouteTrainer);states=iter([dict(map=dict(name=name),in_battle=False,controls=dict(callback='CB2_Overworld',field_locked=False,moving=False)) for name in ('Route5','Route6')]);t.state=lambda:next(states)
        t.step=lambda _:self.fail('Input after unexpected map change')
        with self.assertRaises(TrainingProblem):t.go((7,4))
    def test_unavailable_details_survive_planner_worker_error(self):
        from pokemon_red.optimizer import PlanningUnavailable
        import time
        rows=[dict(route='Route9',reason='Cut')]
        def compute(*_):raise PlanningUnavailable(rows)
        p=PlanningService(compute=compute)
        try:
            p.request('k',{}, {}, ROOT)
            for _ in range(100):
                result=p.poll()
                if result:break
                time.sleep(.001)
            self.assertIsNone(result[0]);self.assertEqual(p.availability['k'],rows)
        finally:p.close()

if __name__=='__main__':unittest.main()
