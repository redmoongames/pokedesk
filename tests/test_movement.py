"""Continuous walking must release before settling, hazards and player takeover."""
from pathlib import Path
from types import SimpleNamespace
import copy,sys,tempfile,threading,time,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.movement import safe_segment,straight_path,WalkSegment,npc_envelope
from pokemon_red.navigation import safe_grass_pair
from pokemon_red.automation import Automation,Request
from pokemon_red.engine import BUTTONS

def grid():
    return dict(name='TestMap',width=22,height=10,tiles=[[[0,0,3,0] for _ in range(22)] for _ in range(10)],obstacles=[],objects=[],trainers=[],script_triggers=[],portal_points=[],warps=[],signs=[],sign_approaches=[])

def sample(x=2,y=4,frame=100,**extra):
    return dict(dict(frame=frame,ready=True,open=True,map='TestMap',position=[x,y],moving=False,actors=[],in_battle=False),**extra)

class CorridorTests(unittest.TestCase):
    def test_plain_segment_stops_before_corner_and_caps_length(self):
        g=grid();p=straight_path((2,4),(10,4))+[(10,5),(10,6)]
        self.assertEqual(safe_segment(g,(2,4),p)[-1],(9,4));self.assertEqual(len(safe_segment(g,(2,4),straight_path((2,4),(20,4)))),16)
    def test_npc_wander_envelope_and_portal_margin_force_single_steps(self):
        g=grid();p=straight_path((2,4),(16,4));g['objects']=[dict(x=10,y=3,movement=5,range_x=2,range_y=0)]
        self.assertEqual(safe_segment(g,(2,4),p)[-1],(7,4));self.assertFalse(safe_segment(g,(8,4),straight_path((8,4),(16,4))))
        g=grid();g['portal_points']=[[10,4]];self.assertEqual(safe_segment(g,(2,4),p)[-1],(8,4))
    def test_signs_scripts_ledge_height_and_water_are_never_batched(self):
        for kind in ('sign','script','ledge','height','water'):
            with self.subTest(kind=kind):
                g=grid();p=straight_path((2,4),(16,4))
                if kind=='sign':g['sign_approaches']=[[9,4]]
                elif kind=='script':g['script_triggers']=[[9,4]]
                elif kind=='ledge':g['tiles'][4][9]=[1,0x38,0,0]
                elif kind=='height':g['tiles'][4][9][2]=4
                else:g['tiles'][4][9][1]=0x10
                self.assertLess(safe_segment(g,(2,4),p)[-1][0],9)
    def test_grass_is_batched_only_in_search_mode(self):
        g=grid()
        for x in range(3,13):g['tiles'][4][x]=[0,2,3,1]
        path=straight_path((2,4),(12,4));self.assertEqual(safe_segment(g,(2,4),path),[]);self.assertEqual(safe_segment(g,(2,4),path,search=True),path)
    def test_cave_transit_uses_explicit_flag_without_enabling_grass(self):
        g=grid();path=straight_path((2,4),(12,4))
        for x in range(2,13):g['tiles'][4][x]=[0,8,3,1]
        self.assertFalse(safe_segment(g,(2,4),path))
        self.assertEqual(safe_segment(g,(2,4),path,allow_encounters=True),path)
        g['tiles'][4][7]=[0,2,3,1]
        self.assertEqual(safe_segment(g,(2,4),path,allow_encounters=True)[-1],(6,4))
        g['portal_points']=[[6,4]]
        self.assertEqual(safe_segment(g,(2,4),path,allow_encounters=True)[-1],(4,4))
    def test_long_strip_avoids_trainer_and_keeps_full_encounter_path(self):
        g=grid()
        for y in (4,7):
            for x in range(2,19):g['tiles'][y][x]=[0,2,3,1]
        g['trainers']=[dict(x=10,y=3,movement=8,sight=3,defeated=False)]
        found=safe_grass_pair(g,(2,8));self.assertGreaterEqual(found['length'],8);self.assertEqual(found['pair'][0][1],7)
        path=straight_path(found['pair'][0],found['pair'][1]);self.assertEqual(safe_segment(g,found['pair'][0],path,search=True),path)
    def test_small_grass_uses_safe_two_cell_fallback(self):
        g=grid();g['tiles'][4][3]=[0,2,3,1];g['tiles'][4][4]=[0,2,3,1]
        found=safe_grass_pair(g,(2,4));self.assertFalse(found['continuous']);self.assertEqual(found['length'],2)
    def test_strip_floor_and_bounds_do_not_cross_different_areas(self):
        g=grid()
        for x in range(2,19):g['tiles'][4][x]=[0,8,3,1]
        f=safe_grass_pair(g,(2,6),[6,3,15,6],terrain='cave');self.assertTrue(all(6<=x<=15 for x,y in f['strip']));self.assertTrue(all(g['tiles'][y][x][1]==8 for x,y in f['strip']))

class FrameWalkingTests(unittest.TestCase):
    def test_release_on_entry_before_tile_settles(self):
        w=WalkSegment('TestMap',(2,4),(10,4),100);self.assertEqual(w.next(sample())[0],BUTTONS['RIGHT'])
        mask,result=w.next(sample(x=10,frame=228,moving=True));self.assertEqual(mask,0);self.assertIsNone(result)
        mask,result=w.next(sample(x=10,frame=240));self.assertEqual(mask,0);self.assertEqual(result['reason'],'reached')
    def test_dynamic_actor_battle_lock_map_and_timeout_release(self):
        cases=[(dict(actors=[[7,4]]),'obstacle'),(dict(in_battle=True),'battle'),(dict(open=False,battle_pending=True),'battle'),(dict(map='Elsewhere'),'map_changed'),(dict(frame=200),'stalled'),(dict(y=5),'off_corridor')]
        for change,reason in cases:
            with self.subTest(reason=reason):
                mask,result=WalkSegment('TestMap',(2,4),(10,4),100).next(sample(**change));self.assertEqual(mask,0);self.assertEqual(result['reason'],reason)
    def test_battle_intro_gap_releases_input_and_is_bounded(self):
        w=WalkSegment('TestMap',(2,4),(10,4),100)
        self.assertEqual(w.next(sample(open=False)),(0,None))
        self.assertEqual(w.next(sample(frame=101,open=False,battle_pending=True))[1]['reason'],'battle')
        w=WalkSegment('TestMap',(2,4),(10,4),100);w.next(sample(open=False))
        self.assertEqual(w.next(sample(frame=112,open=False))[1]['reason'],'interrupted')
    def test_cannot_overshoot_reverse_or_leave_line(self):
        for p in ((11,4),(1,4),(4,5)):
            mask,result=WalkSegment('TestMap',(2,4),(10,4),100).next(sample(x=p[0],y=p[1]));self.assertEqual(mask,0);self.assertEqual(result['reason'],'off_corridor')
    def test_all_directions_are_coordinate_based(self):
        for goal,button in [((10,4),'RIGHT'),((1,4),'LEFT'),((2,8),'DOWN'),((2,1),'UP')]:
            w=WalkSegment('TestMap',(2,4),goal,100);self.assertEqual(w.next(sample())[0],BUTTONS[button]);self.assertEqual(w.next(sample(x=goal[0],y=goal[1],frame=140))[1]['reason'],'reached')

class ControllerWalkingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.state=sample();self.g=grid();self.released=[]
        self.c=Automation(Path(self.tmp.name),snapshot=lambda:{'frame':self.state['frame']},checkpoint=lambda _:None,set_speed=lambda _:None,release=lambda:self.released.append(True),map_reader=lambda:self.g,walk_reader=lambda:self.state)
        self.session=SimpleNamespace(id='test-session',error_detail=None,cancelled=threading.Event(),finishing=False,listener=SimpleNamespace(close=lambda:None),peer=None);self.c.session=self.session;self.c.safety_profile='training'
    def tearDown(self):self.c.close();self.tmp.cleanup()
    def request(self,**extra):
        r=Request(self.session,'walk_segment',dict(dict(map='TestMap',start=[2,4],goal=[10,4],search=False),**extra));self.c._dispatch(r);return r
    def test_takeover_cancels_pending_and_late_walks_immediately(self):
        r=self.request();self.assertEqual(self.c.next_mask(0),BUTTONS['RIGHT']);self.assertIn('goal',self.c.info()['action'])
        start=time.monotonic();self.c.stop();self.assertLess(time.monotonic()-start,.1);self.assertTrue(r.response['cancelled']);self.assertIsNone(self.c.action);self.assertEqual(self.c.next_mask(BUTTONS['A']),BUTTONS['A'])
        late=Request(self.session,'walk_segment',dict(map='TestMap',start=[2,4],goal=[10,4]));self.c.requests.put(late);self.c.poll();self.assertTrue(late.response['cancelled']);self.assertTrue(self.released)
    def test_pause_does_not_consume_frames_and_finish_never_holds_again(self):
        r=self.request()
        for _ in range(5):self.c.poll()
        self.assertFalse(r.done.is_set());self.assertEqual(self.c.action['walk'].progress,0)
        self.state=sample(x=10,frame=240);self.assertEqual(self.c.next_mask(0),0);self.assertEqual(r.response['result']['reason'],'reached');self.assertEqual(self.c.next_mask(0),0)
    def test_revalidation_rejects_stale_or_unsafe_route_without_input(self):
        self.g['obstacles']=[[7,4]];r=self.request();self.assertEqual(r.response['result']['reason'],'unsafe');self.assertIsNone(self.c.action)
        self.state=sample(x=3);r=self.request();self.assertEqual(r.response['result']['reason'],'changed');self.assertIsNone(self.c.action)
    def test_cave_transit_releases_at_battle_and_takeover(self):
        for row in self.g['tiles']:
            for tile in row:tile[1]=8;tile[3]=1
        rejected=self.request();self.assertEqual(rejected.response['result']['reason'],'unsafe')
        r=self.request(allow_encounters=True);self.assertEqual(self.c.next_mask(0),BUTTONS['RIGHT'])
        self.state=sample(x=4,frame=130,open=False,battle_pending=True)
        self.assertEqual(self.c.next_mask(0),0);self.assertEqual(r.response['result']['reason'],'battle');self.assertIsNone(self.c.action)
        self.state=sample();r=self.request(allow_encounters=True);self.c.stop()
        self.assertTrue(r.response['cancelled']);self.assertIsNone(self.c.action);self.assertTrue(self.released)
    def test_encounter_flag_must_be_a_boolean(self):
        for value in (1,'true',None):
            with self.assertRaises(ValueError):self.request(allow_encounters=value)
    def test_bad_segments_do_not_press_buttons(self):
        for goal in ([2,4],[3,5],[999,4],[True,4]):
            with self.subTest(goal=goal):
                with self.assertRaises(ValueError):self.request(goal=goal)
                self.assertIsNone(self.c.action)
    def test_per_frame_training_guards_are_required(self):
        self.c.safety_profile='none'
        with self.assertRaisesRegex(ValueError,'safety_profile'):self.request()
        self.assertIsNone(self.c.action)

if __name__=='__main__':unittest.main()
