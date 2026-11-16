import sys,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from pokemon_red.search_transport import choose_transport,set_bicycle
from pokemon_red.movement import WalkSegment
from pokemon_red.engine import BUTTONS
from pokemon_red.acquisition_play import AcquisitionAttention,JobPaused

class Transport(unittest.TestCase):
 def test_auto_falls_back_by_actual_capability_and_corridor_length(self):
  a=dict(bike=True,run=True);self.assertEqual(choose_transport(a,8),'bike');self.assertEqual(choose_transport(a,3),'walk')
  self.assertEqual(choose_transport(dict(bike=False,run=True),8),'run');self.assertEqual(choose_transport(dict(bike=False,run=False),8),'walk')
  self.assertEqual(choose_transport(a,8,'walk'),'walk');self.assertEqual(choose_transport(a,8,'run'),'run')
 def test_short_hunts_avoid_mount_cost_and_long_hunts_can_amortize_it(self):
  a=dict(bike=True,run=True)
  self.assertEqual(choose_transport(a,8,expected_encounters=27,workers=1),'run')
  self.assertEqual(choose_transport(a,8,expected_encounters=200,workers=2),'run')
  self.assertEqual(choose_transport(a,8,expected_encounters=2000,workers=6),'bike')
  self.assertEqual(choose_transport(a,8,'bike',expected_encounters=1),'bike')
 def test_unknown_mode_is_not_silently_accepted(self):
  with self.assertRaises(ValueError):choose_transport(dict(bike=True,run=True),8,'teleport')
 def sample(self,**kw):
  d=dict(on_foot=False,on_bike=True,bike_allowed=True,can_run=False,ready=True,open=True,map='Route14',position=[3,5],frame=100,moving=False,actors=[]);d.update(kw);return d
 def test_bike_has_no_B_press_and_releases_before_settling(self):
  segment=WalkSegment('Route14',(3,5),(8,5),100,mode='bike');self.assertEqual(segment.next(self.sample())[0],BUTTONS['RIGHT'])
  self.assertEqual(segment.next(self.sample(position=[8,5],moving=True,frame=120)),(0,None));self.assertEqual(segment.next(self.sample(position=[8,5],frame=125))[1]['reason'],'reached')
 def test_bike_guards_transport_map_actors_and_battle(self):
  for kw,reason in [(dict(on_bike=False),'unsupported_transport'),(dict(bike_allowed=False),'unsupported_transport'),(dict(map='City'),'map_changed'),(dict(actors=[[5,5]]),'obstacle'),(dict(battle_pending=True),'battle'),(dict(position=[9,5]),'off_corridor')]:
   mask,result=WalkSegment('Route14',(3,5),(8,5),100,mode='bike').next(self.sample(**kw));self.assertEqual(mask,0);self.assertEqual(result['reason'],reason)
 def test_walking_segment_cannot_implicitly_acquire_bike(self):
  self.assertEqual(WalkSegment('Route14',(3,5),(8,5),100).next(self.sample())[1]['reason'],'unsupported_transport')
 def test_cancel_during_mount_stabilization_sends_no_menu_input(self):
  p=Mock();p.g=Mock();p.advance.side_effect=JobPaused
  state=self.sample(on_bike=False,on_foot=True,in_battle=False,battle_pending=False)
  with patch('pokemon_red.search_transport.read_walk_state',return_value=state),patch('pokemon_red.search_transport.capabilities',return_value=dict(bike=True)),patch('pokemon_red.field_item_menu.use_field_item') as menu:
   with self.assertRaises(JobPaused):set_bicycle(p,True)
   menu.assert_not_called()
