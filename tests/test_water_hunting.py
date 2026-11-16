import unittest,copy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from pokemon_red.water_hunting import water_spot,water_path,shore_paths,swim_step
from pokemon_red.hunt_planning import HuntPlanner
from pokemon_red.engine import ROOT


def grid():
 return dict(name='Route6',width=8,height=6,tiles=[[[0,0,3,0] if x<4 else [0,0x10,1,2] for x in range(8)] for y in range(6)],obstacles=[],objects=[],trainers=[],script_triggers=[],warps=[])

class WaterGeometryTests(unittest.TestCase):
 def test_fishing_uses_reachable_land_facing_real_water(self):
  g=grid();spot=water_spot(g,(1,2),'good_rod')
  self.assertEqual(spot['shore'],(3,2));self.assertEqual(spot['entry'],(4,2));self.assertEqual(spot['pair'],[(3,2),(3,2)]);self.assertTrue(all(x<4 for x,y in spot['path']))
 def test_surf_requires_two_encounter_cells_and_a_return_shore(self):
  g=grid();spot=water_spot(g,(1,2),'water_mons');self.assertEqual(spot['shore'],(3,2));self.assertEqual(len(spot['pair']),2)
  for a,b in zip(spot['pair'],spot['pair'][1:]):self.assertEqual(abs(a[0]-b[0])+abs(a[1]-b[1]),1)
  water_path(g,spot['pair'][-1],spot['entry'])
 def test_water_search_can_start_afloat(self):
  g=grid();spot=water_spot(g,(6,3),'water_mons');self.assertTrue(spot['start_water']);self.assertEqual(spot['shore'][0],3)
 def test_currents_and_waterfalls_are_not_hunting_cells(self):
  for behavior in (0x11,0x13):
   g=grid()
   for row in g['tiles']:
    for tile in row[4:]:tile[1]=behavior
   with self.assertRaises(RuntimeError):water_spot(g,(1,2),'water_mons')
 def test_dynamic_npcs_and_scripts_block_water_path(self):
  g=grid();g['obstacles']=[[5,y] for y in range(6)]
  with self.assertRaises(RuntimeError):water_path(g,(4,2),(6,2))
  g=grid();g['script_triggers']=[[5,y] for y in range(6)]
  with self.assertRaises(RuntimeError):water_path(g,(4,2),(6,2))
 def test_elevation_does_not_create_a_false_shore_route(self):
  g=grid()
  for y in range(6):g['tiles'][y][2][2]=4
  self.assertNotIn((3,2),shore_paths(g,(1,2),[(3,2)]))
 def test_battle_transition_releases_swimming_before_any_button(self):
  p=SimpleNamespace(g=SimpleNamespace(advance=Mock()),advance=Mock(),state=lambda:dict(map=dict(name='Route6'),position=dict(x=4,y=2),in_battle=False))
  with patch('pokemon_red.water_hunting.read_walk_state',return_value=dict(battle_pending=True)):
   self.assertFalse(swim_step(p,(5,2)))
  p.advance.assert_not_called()

class WaterRequirementsTests(unittest.TestCase):
 def planner(self,**changes):
  mon=dict(uid='hunter',checksum_valid=True,is_egg=False,hp=100,max_hp=100,level=30,species_id=3,moves=[dict(id=79,current_pp=15)],nickname='V',location='party')
  inv=dict(party=[mon],boxes=[],field_badges=[5],bag=dict(items=[]));inv.update(changes)
  trainer=SimpleNamespace(root=ROOT,state=lambda:dict(map=dict(name='Route6'),position=dict(x=1,y=2)))
  with patch('pokemon_red.hunt_planning.Navigator') as nav:
   nav.return_value.configure_tools.return_value=SimpleNamespace(spec=dict(links=[]))
   return HuntPlanner(trainer,inv)
 def test_missing_rod_has_specific_reason(self):
  row=self.planner().row(dict(map='Route6',method='super_rod'));self.assertFalse(row['available']);self.assertIn('Super Rod',row['reason'])
 def test_surf_needs_badge_and_existing_move(self):
  row=self.planner(field_badges=[]).row(dict(map='Route6',method='water_mons'));self.assertIn('Soul Badge',row['reason'])
  row=self.planner().row(dict(map='Route6',method='water_mons'));self.assertIn('уже выученным Surf',row['reason'])


class WaterBattleTransitionTests(unittest.TestCase):
 def test_init_battle_callback_is_pending_even_after_start_task_is_gone(self):
  import struct
  from pokemon_red.telemetry import read_walk_state
  sy=dict(gPlayerAvatar=100,gObjectEvents=200,gMain=300,CB2_Overworld=1000,CB2_InitBattle=2000,gTasks=400,gMapHeader=500,sLockFieldControls=600)
  avatar=bytes([8,0,0,0,0,0,0,0]);objects=bytearray(16*36);objects[0]=1;struct.pack_into('<hh',objects,16,11,9)
  g=SimpleNamespace(root=ROOT,frame=10,read_bytes=lambda a,n:avatar if a==100 else bytes(objects) if a==200 else bytes(n),read32=lambda a:2001 if a==304 else 0,read8=lambda a:0)
  with patch('pokemon_red.telemetry.symbols',return_value=sy),patch('pokemon_red.telemetry.save_block',return_value=0x02001000),patch('pokemon_red.telemetry.main_flags',return_value=0),patch('pokemon_red.telemetry.game_flag',return_value=False),patch('pokemon_red.telemetry.maps',return_value={(0,0):'Route6'}):
   state=read_walk_state(g)
  self.assertTrue(state['battle_pending']);self.assertFalse(state['in_battle']);self.assertFalse(state['open'])

if __name__=='__main__':unittest.main()
