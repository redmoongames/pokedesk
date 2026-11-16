"""Straight paths retain their geometry while live hazards and battles still win."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,Mock
import copy,sys,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.training import path_to,RouteTrainer
from pokemon_red.walking_route import WalkingRoute,direction,waypoints
from pokemon_red.movement import safe_segment,straight_path


def grid():
    return dict(name='TestMap',width=22,height=12,tiles=[[[0,0,3,0] for _ in range(22)] for _ in range(12)],obstacles=[],objects=[],trainers=[],script_triggers=[],warps=[])


def turns(start,path,heading=None):
    result=0
    for point in path:
        new=direction(start,point);result+=heading is not None and new!=heading;start=point;heading=new
    return result


class StraightPathTests(unittest.TestCase):
    def test_equal_length_path_has_one_turn_and_respects_initial_heading(self):
        g=grid()
        for heading in ((1,0),(0,1)):
            p=path_to(g,(2,2),(12,8),heading=heading)
            self.assertEqual(len(p),16);self.assertEqual(turns((2,2),p,heading),1)
            self.assertEqual(direction((2,2),p[0]),heading)
    def test_encounter_avoidance_precedes_distance_and_turn_count(self):
        g=grid();g['tiles'][4][7]=[0,2,3,1]
        p=path_to(g,(2,4),(12,4));self.assertEqual(len(p),12)
        self.assertNotIn((7,4),p);self.assertEqual(turns((2,4),p),2)
        p=path_to(g,(2,4),(12,4),avoid_grass=False)
        self.assertEqual(len(p),10);self.assertEqual(turns((2,4),p),0)
    def test_obstacle_routes_keep_shortest_length_before_fewer_turns(self):
        g=grid();g['obstacles']=[[6,y] for y in range(4,9)]
        p=path_to(g,(2,6),(12,6));self.assertEqual(len(p),16)
        self.assertEqual(turns((2,6),p),2)
        self.assertFalse(set(p)&set(map(tuple,g['obstacles'])))
    def test_ledge_is_directional_and_never_becomes_held_movement(self):
        g=grid()
        for y in range(g['height']):g['tiles'][y][6]=[1,0x38,3,0]
        p=path_to(g,(4,4),(9,4));self.assertIn((7,4),p);self.assertNotIn((6,4),p)
        self.assertFalse(safe_segment(g,(5,4),p[p.index((7,4)):]))
        with self.assertRaises(RuntimeError):path_to(g,(9,4),(4,4))
    def test_scripts_warps_and_trainer_sight_remain_blocked(self):
        g=grid();g['script_triggers']=[[5,4]];g['warps']=[dict(x=6,y=4)]
        g['trainers']=[dict(x=10,y=2,movement=8,sight=4,defeated=False)]
        p=path_to(g,(2,4),(14,4))
        self.assertFalse(set(p)&{(5,4),(6,4),(10,2),(10,3),(10,4),(10,5),(10,6)})


class RetainedRouteTests(unittest.TestCase):
    def test_waypoints_and_progress_survive_benign_npc_motion(self):
        g=grid();p=straight_path((2,4),(10,4))+[(10,5),(10,6)]
        r=WalkingRoute((2,4),p);self.assertEqual(r.waypoints,[(10,4),(10,6)])
        self.assertTrue(r.validate(g));self.assertTrue(r.advance((7,4)))
        self.assertEqual(r.remaining[0],(8,4));self.assertEqual(r.heading,(1,0))
        g['objects']=[dict(x=16,y=8,movement=5,range_x=1,range_y=0)]
        self.assertTrue(r.validate(g));self.assertEqual(r.waypoints,[(10,4),(10,6)])
        self.assertFalse(r.advance((7,5)))
    def test_new_obstacles_scripts_or_ledge_changes_invalidate_remaining_path(self):
        for hazard in ('obstacle','script','warp','tile','trainer'):
            with self.subTest(hazard=hazard):
                g=grid();r=WalkingRoute((2,4),straight_path((2,4),(12,4)));self.assertTrue(r.validate(g));r.advance((5,4))
                if hazard=='obstacle':g['obstacles']=[[9,4]]
                elif hazard=='script':g['script_triggers']=[[9,4]]
                elif hazard=='warp':g['warps']=[dict(x=9,y=4)]
                elif hazard=='tile':g['tiles'][4][9]=[1,0x39,3,0]
                else:g['trainers']=[dict(x=9,y=3,movement=8,sight=2,defeated=False)]
                self.assertFalse(r.validate(g))
    def test_consumed_cells_need_not_stay_walkable(self):
        g=grid();r=WalkingRoute((2,4),straight_path((2,4),(12,4)));r.advance((6,4));g['obstacles']=[[3,4]]
        self.assertTrue(r.validate(g));self.assertFalse(r.advance((3,4)))
    def test_go_replans_after_a_live_blocker_and_uses_fresh_fallback(self):
        g=grid();s=dict(map=dict(name='TestMap'),position=dict(x=2,y=4),in_battle=False,party=[],controls=dict(callback='CB2_Overworld',field_locked=False,moving=False))
        t=object.__new__(RouteTrainer);t.state=lambda:s;t.wait=Mock();calls=[];visited=[]
        def walk(name,start,goal,**opts):
            calls.append(goal)
            if len(calls)==1:g['obstacles']=[[7,4]];return dict(reason='obstacle')
            s['position'].update(x=goal[0],y=goal[1]);return dict(reason='reached')
        def step(d):
            dx,dy={'RIGHT':(1,0),'LEFT':(-1,0),'UP':(0,-1),'DOWN':(0,1)}[d]
            point=(s['position']['x']+dx,s['position']['y']+dy);self.assertNotEqual(point,(7,4));visited.append(point)
            s['position'].update(x=point[0],y=point[1]);return True
        t.bot=SimpleNamespace(map=lambda:g,walk_segment=walk);t.step=step
        with patch('pokemon_red.training.path_to',wraps=path_to) as find:t.go((13,4))
        self.assertEqual(find.call_count,2);self.assertTrue(visited);self.assertEqual(s['position'],dict(x=13,y=4))
    def test_go_keeps_one_path_across_encounter_and_irrelevant_npc_changes(self):
        g=grid()
        for row in g['tiles']:
            for tile in row:tile[1]=8;tile[3]=1
        s=dict(map=dict(name='TestMap'),position=dict(x=2,y=4),in_battle=False,party=[],controls=dict(callback='CB2_Overworld',field_locked=False,moving=False))
        t=object.__new__(RouteTrainer);t.state=lambda:s;t.want_heal=False;t.wait=Mock();calls=[]
        def fresh():
            g['objects']=[dict(x=16+len(calls)%2,y=9,movement=0)];return g
        def walk(name,start,goal,**opts):
            calls.append(opts)
            if len(calls)==1:s['position'].update(x=4,y=4);s['in_battle']=True;return dict(reason='battle')
            s['position'].update(x=goal[0],y=goal[1]);return dict(reason='reached')
        def step(d):
            dx,dy={'RIGHT':(1,0),'LEFT':(-1,0),'UP':(0,-1),'DOWN':(0,1)}[d]
            s['position']['x']+=dx;s['position']['y']+=dy;return True
        def fight(**opts):
            self.assertEqual(opts,dict(retreat=True,travel=True));s['in_battle']=False
        t.bot=SimpleNamespace(map=fresh,walk_segment=walk);t.step=step;t.fight=Mock(side_effect=fight)
        with patch('pokemon_red.training.path_to',wraps=path_to) as find:t.go((13,7))
        self.assertEqual(find.call_count,1);t.fight.assert_called_once()
        self.assertGreaterEqual(len(calls),2);self.assertTrue(all(c==dict(search=False,allow_encounters=True) for c in calls))
        self.assertEqual(s['position'],dict(x=13,y=7))


if __name__=='__main__':unittest.main()
