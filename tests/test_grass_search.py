"""Search correctness: ranking, private frontiers and interruptible movement."""
import hashlib,json,tempfile,unittest,sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from pokemon_red.search_candidates import CandidateStore,rank_candidates
from pokemon_red.grass_search import grass_corridor,generated_enemy,settle_encounter,sample_grass
from pokemon_red.acquisition_play import AcquisitionAttention,JobPaused
ROOT=Path(__file__).resolve().parents[1]

class Ranking(unittest.TestCase):
 def candidate(self,n,uid=None):
  data=bytes([n]);return dict(rank=[n],score=n,pokemon=dict(uid=uid or str(n)),sha256=hashlib.sha256(data).hexdigest()),data
 def test_true_top_three_including_non_record_second_and_third(self):
  with tempfile.TemporaryDirectory() as tmp:
   store=CandidateStore(tmp,'wild');history=[]
   for n in (100,90,95,94,99,98,97):
    candidate,data=self.candidate(n);history=store.record(history,candidate,data,top_k=True)
   self.assertEqual([v['score'] for v in history],[100,99,98]);self.assertEqual(store.rows(),history)
   for c in history:self.assertEqual(hashlib.sha256(store.checkpoint(c['sha256'])).hexdigest(),c['sha256'])
   self.assertEqual(len(list(store.folder.glob('*.state'))),3)
 def test_uid_dedup_and_stable_equal_score(self):
  rows=[self.candidate(n,uid)[0] for n,uid in ((50,'a'),(60,'b'),(70,'a'),(55,'c'),(55,'d'))]
  self.assertEqual([v['pokemon']['uid'] for v in rank_candidates(rows)],['a','b','c'])
 def test_starter_record_history_policy_unchanged(self):
  with tempfile.TemporaryDirectory() as tmp:
   store=CandidateStore(tmp,'starter');history=[]
   for n in (100,90,95):
    c,d=self.candidate(n);history=store.record(history,c,d)
   self.assertEqual([v['score'] for v in history],[100])
 def test_bad_checkpoint_hash_cannot_enter_top_three(self):
  with tempfile.TemporaryDirectory() as tmp:
   c,d=self.candidate(10);self.assertFalse(CandidateStore(tmp,'wild').record([],c,b'bad',top_k=True))

class GrassSafety(unittest.TestCase):
 def grid(self):return dict(name='Test',width=16,height=9,tiles=[[[0,2,3,1] for x in range(16)] for y in range(9)],obstacles=[],objects=[],trainers=[],script_triggers=[],warps=[])
 def test_entire_strip_must_be_encounter_terrain(self):
  g=self.grid();self.assertTrue(grass_corridor(g,[(3,4),(11,4)]));g['tiles'][4][8][3]=0;self.assertFalse(grass_corridor(g,[(3,4),(11,4)]))
 def test_events_npcs_warps_and_reverse_ledge_are_rejected(self):
  for field,value in [('script_triggers',[[7,4]]),('warps',[dict(x=7,y=4)]),('objects',[dict(x=7,y=4,movement=0)])]:
   g=self.grid();g[field]=value;self.assertFalse(grass_corridor(g,[(3,4),(11,4)]),field)
  g=self.grid();g['tiles'][4][8][1]=0x38;self.assertFalse(grass_corridor(g,[(3,4),(11,4)]))
 def test_small_two_tile_strip_is_supported_safely(self):
  self.assertTrue(grass_corridor(self.grid(),[(4,4),(5,4)]))
 def test_stale_or_field_enemy_is_never_counted(self):
  g=Mock();g.root=ROOT;g.read_bytes.return_value=b'old';g.read32.return_value=0
  with patch('pokemon_red.grass_search.symbols',return_value=dict(gBattleTypeFlags=1,gEnemyParty=2)),patch('pokemon_red.grass_search.decode_mon') as decode:
   self.assertIsNone(generated_enemy(g,dict(battle_pending=False,in_battle=False),b'other'))
   self.assertIsNone(generated_enemy(g,dict(battle_pending=True),b'old'));decode.assert_not_called()
 def test_trainer_roamer_scripted_battle_rejected_before_decode(self):
  g=Mock();g.root=ROOT
  with patch('pokemon_red.grass_search.symbols',return_value=dict(gBattleTypeFlags=1,gEnemyParty=2)),patch('pokemon_red.grass_search.decode_mon') as decode:
   for flag in (1,2,8,0x80,0x400,0x20000):
    g.read32.return_value=flag
    with self.assertRaises(AcquisitionAttention):generated_enemy(g,dict(battle_pending=True),b'old')
   decode.assert_not_called()
 def test_master_and_battle_entry_flags_are_not_misclassified(self):
  g=Mock();g.root=ROOT;g.read_bytes.return_value=b'new';mon=dict(checksum_valid=True,species_id=21,is_egg=False,level=15)
  with patch('pokemon_red.grass_search.symbols',return_value=dict(gBattleTypeFlags=1,gEnemyParty=2)),patch('pokemon_red.grass_search.decode_mon',return_value=mon):
   for flag in (0,4,0x24):
    g.read32.return_value=flag;self.assertIs(generated_enemy(g,dict(battle_pending=True),b'old'),mon)
 def test_interrupt_before_first_speculative_frame(self):
  game=Mock(root=ROOT);worker=Mock();worker.request=dict(lane=0);worker.before_frame.side_effect=JobPaused
  # The real Player.advance guard owns every frame, including neutral RNG delay.
  from pokemon_red.acquisition_play import Player
  player=Player(game,worker)
  with patch('pokemon_red.grass_search.read_walk_state',return_value=dict(map='Route11',position=[3,4],open=True,moving=False)):
   with self.assertRaises(JobPaused):sample_grass(player,dict(species_id=21,gender='any'),dict(selected=dict(map='Route11'),grass_frontier=dict(pair=[[3,4],[11,4]])))
  game.advance.assert_not_called()
 def test_settle_does_not_send_menu_input_and_checks_identity(self):
  g=Mock(root=ROOT);g.read32.return_value=4;p=Mock(g=g)
  with patch('pokemon_red.grass_search.symbols',return_value=dict(gBattleTypeFlags=1)),patch('pokemon_red.grass_search.read_controls',return_value=dict(callback='BattleMainCB2',controllers=['HandleInputChooseAction'])),patch('pokemon_red.autocatch.verified_enemy',return_value=dict(uid='new')):
   self.assertEqual(settle_encounter(p,'new'),dict(uid='new'));p.advance.assert_not_called()
   with self.assertRaises(AcquisitionAttention):settle_encounter(p,'old')

if __name__=='__main__':unittest.main()

class CandidatePanel(unittest.TestCase):
 def test_all_three_visible_and_selection_survives_new_rank_order(self):
  import tkinter as tk,gc
  from pokemon_red.search_candidates_ui import SearchCandidatesView
  from pokemon_red.capture_target import CaptureTarget
  from pokemon_red.models import STAT_KEYS
  gc.collect();root=tk.Tk();root.geometry('350x650');root.update();command=Mock()
  try:
   target=CaptureTarget.parse(dict(species_id=21,gender='any',min_ivs=dict.fromkeys(STAT_KEYS,31)),ROOT)
   rows=[]
   for value in (30,29,28):
    mon=dict(uid=str(value),species_id=21,personality=value,nature=value%25,level=15,ivs=dict.fromkeys(STAT_KEYS,value),shiny=False,checksum_valid=True)
    rows.append(dict(target.assess(mon,ROOT),sha256=str(value)*32))
   view=SearchCandidatesView(root,ROOT,command);view.update(rows,True);root.update()
   self.assertEqual(len(view.cards.winfo_children()),3);self.assertLess(view.frame.winfo_reqheight(),500)
   view.choose(rows[2]['sha256']);view.update(rows[::-1],True);view.action.invoke();command.assert_called_once_with(rows[2]['sha256'])
   view.update(rows,False);self.assertEqual(view.action.cget('state'),'disabled')
  finally:root.destroy();gc.collect()

class SnapshotRetention(unittest.TestCase):
 def test_recent_offered_candidates_survive_rank_rotation_with_bounded_files(self):
  with tempfile.TemporaryDirectory() as tmp:
   store=CandidateStore(tmp,'wild',retention=8);history=[]
   for n in range(20):
    data=bytes([n]);c=dict(rank=[n],pokemon=dict(uid=str(n)),sha256=hashlib.sha256(data).hexdigest());history=store.record(history,c,data,top_k=True)
   self.assertEqual(store.checkpoint(hashlib.sha256(bytes([15])).hexdigest()),bytes([15]))
   self.assertEqual(len(list(store.folder.glob('*.state'))),8)
   self.assertEqual([r['rank'][0] for r in store.rows()],[19,18,17])
