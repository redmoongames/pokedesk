import sys,unittest,copy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from pokemon_red.capture_target import CaptureTarget,hunt_atlas,candidates,gender_of,genders
from pokemon_red.models import STAT_KEYS
from pokemon_red.autocatch import verified_enemy
from pokemon_red.acquisition_play import AcquisitionAttention
from pokemon_red.worker_pacing import FramePacer
ROOT=Path(__file__).resolve().parents[1]

class CaptureFilters(unittest.TestCase):
 def mon(self):return dict(species_id=19,checksum_valid=True,is_egg=False,shiny=False,level=5,personality=0,ivs=dict.fromkeys(STAT_KEYS,10))
 def test_defaults_and_inclusive_boundaries(self):
  t=CaptureTarget.parse(dict(species_id=19),ROOT);self.assertEqual(t.min_ivs,(10,)*6);self.assertEqual(t.gender,'female');self.assertFalse(t.shiny);self.assertTrue(t.matches(self.mon(),ROOT))
  for k in STAT_KEYS:
   m=self.mon();m['ivs'][k]=9;self.assertFalse(t.matches(m,ROOT))
 def test_exact_identity_all_fields(self):
  t=CaptureTarget.parse(dict(species_id=19),ROOT)
  for key,value in [('checksum_valid',False),('is_egg',True),('species_id',16),('shiny',True),('personality',None),('level',0),('ivs',{})]:
   m=self.mon();m[key]=value;self.assertFalse(t.matches(m,ROOT),(key,value))
 def test_gender_threshold_and_exceptions(self):
  ratio=hunt_atlas(ROOT)['species']['19']['gender_ratio'];m=self.mon();m['personality']=ratio-1;self.assertEqual(gender_of(m,ROOT),'female');m['personality']=ratio;self.assertEqual(gender_of(m,ROOT),'male')
  for n,want in [(81,'genderless'),(32,'male'),(29,'female')]:
   t=CaptureTarget.parse(dict(species_id=n),ROOT);self.assertEqual(t.gender,want);self.assertEqual(genders(n,ROOT),(want,))
   with self.assertRaises(ValueError):CaptureTarget.parse(dict(species_id=n,gender='male' if want!='male' else 'female'),ROOT)
 def test_invalid_configuration(self):
  for update in [dict(min_level=0),dict(min_level=50,max_level=49),dict(shiny=1),dict(min_ivs={}),dict(min_ivs=dict.fromkeys(STAT_KEYS,32)),dict(species_id=True),dict(method='gift'),dict(route='unknown')]:
   with self.assertRaises(ValueError):CaptureTarget.parse(dict(dict(species_id=19),**update),ROOT)
 def test_roundtrip_and_exact_level_table(self):
  t=CaptureTarget.parse(dict(species_id=19,min_level=4,max_level=4,route='Route1'),ROOT);self.assertEqual(CaptureTarget.parse(t.as_dict(),ROOT),t)
  rows=candidates(t,ROOT);self.assertTrue(rows);self.assertTrue(all(set(r['levels'])=={4} for r in rows));self.assertTrue(all(r['probability']==sum(r['levels'].values()) for r in rows))
  self.assertFalse(candidates(CaptureTarget.parse(dict(species_id=19,min_level=100,max_level=100),ROOT),ROOT))
 def test_atlas_has_all_maps_and_real_cells(self):
  a=hunt_atlas(ROOT);self.assertEqual(len(a['maps']),425)
  for data in a['maps'].values():
   for area in data.get('terrain',{}).values():
    for path in area['entry_paths']:
     self.assertEqual(len(path['pair']),2)
     if not path['path']:self.assertEqual(path['entry'],path['pair'][0])
 def test_verified_battle_identity(self):
  mon=dict(self.mon(),uid='same',slot=1);live=dict(uid='same',party_slot=1,identity_valid=True);s=dict(battle=dict(flags=0,enemies=[live],enemy_party=[mon]));self.assertIs(verified_enemy(s),mon)
  live['uid']='stale';self.assertIsNone(verified_enemy(s));live['uid']='same';live['identity_valid']=False;self.assertIsNone(verified_enemy(s))
  for flags in (1,8,0x80):
   s['battle']['flags']=flags
   with self.assertRaises(AcquisitionAttention):verified_enemy(s)

class HuntAreaSafety(unittest.TestCase):
 def test_precomputed_strip_is_rejected_after_live_script_appears(self):
  from pokemon_red.hunt_spots import hunting_spot
  g=dict(name='TestMap',width=15,height=8,tiles=[[[0,2,3,1] for _ in range(15)] for _ in range(8)],obstacles=[],objects=[],trainers=[],script_triggers=[],warps=[])
  atlas=dict(version_key='test',maps=dict(TestMap=dict(terrain=dict(grass=dict(entry_paths=[dict(entry=[2,4],path=[],pair=[[2,4],[10,4]],strip=[[x,4] for x in range(2,11)])])))))
  cache=Mock();cache.get.return_value=None
  with patch('pokemon_red.hunt_spots.hunt_atlas',return_value=atlas),patch('pokemon_red.hunt_spots.shared_cache',return_value=cache),patch('pokemon_red.hunt_spots.safe_grass_pair',side_effect=RuntimeError('blocked')):
   self.assertEqual(hunting_spot(ROOT,g,(2,4))['pair'],[[2,4],[10,4]])
   g['script_triggers']=[[6,4]]
   with self.assertRaises(RuntimeError):hunting_spot(ROOT,g,(2,4))

class CaptureExecution(unittest.TestCase):
 def execute(self,*,unexpected=False,bad_result=False):
  from pokemon_red.autocatch import run_autocatch
  m=dict(species_id=19,checksum_valid=True,is_egg=False,shiny=unexpected,level=4,personality=0,ivs=dict.fromkeys(STAT_KEYS,10),uid='target',slot=1)
  hunter=dict(uid='hunter',hp=1,max_hp=100,moves=[dict(id=79,current_pp=0),dict(id=73)])
  before=dict(party=[hunter],boxes=[]);caught=copy.deepcopy(m)
  if bad_result:caught['ivs']['hp']=9
  state=dict(in_battle=True,controls=dict(controllers=['HandleInputChooseAction']),battle=dict(flags=0,enemies=[dict(uid='target',party_slot=1,identity_valid=True)],enemy_party=[m]))
  p=SimpleNamespace(save_game=Mock(),g=SimpleNamespace(root=ROOT),w=Mock(),state=lambda:state,checkpoint=Mock(),battle=Mock(),persist=Mock())
  selected=dict(manual_heal=True,method='land_mons',hunter_uid='hunter',map='Route1',label='Route1',farm=dict(pair=[[1,1],[2,1]]),clinic='Viridian')
  with patch('pokemon_red.autocatch.read_inventory',side_effect=[before,dict(party=[hunter],boxes=[caught])]),patch('pokemon_red.autocatch.read_field_badges',return_value=[]),patch('pokemon_red.autocatch.read_player_inventory',return_value=dict(items=[dict(id=4,quantity=10)])),patch('pokemon_red.autocatch.HuntPlanner') as planner,patch('pokemon_red.move_plan.compile_plan',return_value={}),patch('pokemon_red.learning.LearningRuntime'):
   planner.return_value.choose.return_value=selected
   if unexpected:
    from pokemon_red.acquisition_play import JobPaused
    p.w.safe_point.side_effect=JobPaused
    with self.assertRaises(JobPaused):run_autocatch(p,dict(species_id=19))
   elif bad_result:
    with self.assertRaises(AcquisitionAttention):run_autocatch(p,dict(species_id=19))
   else:self.assertEqual(run_autocatch(p,dict(species_id=19))['uid'],'target')
  return p
 def test_caught_identity_is_verified_again(self):
  p=self.execute();p.battle.assert_called_once_with('catch');p.persist.assert_called_once();self.assertEqual(p.checkpoint.call_count,2)
 def test_corrupt_or_wrong_caught_parameters_are_not_success(self):
  p=self.execute(bad_result=True);p.persist.assert_not_called()
 def test_unexpected_shiny_is_escaped_instead_of_interrupting_search(self):
  p=self.execute(unexpected=True);p.battle.assert_called_once_with('escape');p.checkpoint.assert_not_called()

class Pacing(unittest.TestCase):
 def test_wall_clock_ceiling_and_load_reset(self):
  clock=[0.];sleeps=[]
  def sleep(t):clock[0]+=t;sleeps.append(t)
  pacer=FramePacer(4,clock=lambda:clock[0],sleep=sleep);pacer.step(100);pacer.step(339);self.assertAlmostEqual(clock[0],239/(4*59.7275));self.assertLessEqual(max(sleeps),.008)
  pacer.step(10);old=clock[0];pacer.step(249);self.assertAlmostEqual(clock[0]-old,239/(4*59.7275))
 def test_os_stall_does_not_create_catchup_burst(self):
  clock=[0.];p=FramePacer(12,clock=lambda:clock[0],sleep=lambda t:clock.__setitem__(0,clock[0]+t));p.step(1);clock[0]=10;p.step(2);p.step(3);self.assertGreater(clock[0],10)

class HuntPreview(unittest.TestCase):
 def test_filters_do_not_replan_geometry(self):
  from pokemon_red.catch_view import CatchSetup
  fake=SimpleNamespace(ready_form=True,closed=False,target=lambda:None,select=Mock(),start=Mock(),activity=Mock());CatchSetup.filters_changed(fake);self.assertTrue(fake.filters_valid);fake.select.assert_called_once()
 def test_unavailable_methods_are_explicit(self):
  from pokemon_red.hunt_planning import HuntPlanner
  fake=SimpleNamespace(root=ROOT,inventory=dict(field_badges=[],party=[],boxes=[]))
  for name,method in [('Route1','water_mons'),('SafariZone_Center','land_mons')]:
   r=HuntPlanner.row(fake,dict(map=name,method=method));self.assertFalse(r['available']);self.assertTrue(r['reason'])

if __name__=='__main__':unittest.main()

class RestoredPacing(unittest.TestCase):
 def pacer(self):
  clock=[0.]
  p=FramePacer(4,clock=lambda:clock[0],sleep=lambda t:clock.__setitem__(0,clock[0]+t))
  return p,clock
 def test_restore_above_original_frame_is_still_a_restore(self):
  p,c=self.pacer();p.step(100);p.step(339);before=c[0]
  p.step(200);p.step(439)
  self.assertAlmostEqual(c[0]-before,239/(4*59.7275))
 def test_generation_change_resets_forward_and_equal_frame_restores(self):
  p,c=self.pacer();p.step(100,generation=1);p.step(200,generation=1);before=c[0]
  p.step(1000,generation=2);self.assertEqual(c[0],before)
  p.step(1239,generation=2);self.assertAlmostEqual(c[0]-before,239/(4*59.7275))
 def test_monotonic_work_counter_does_not_reset_at_replayed_game_frames(self):
  p,c=self.pacer()
  for actual_frame in range(240):p.step(actual_frame)
  self.assertAlmostEqual(c[0],239/(4*59.7275))
