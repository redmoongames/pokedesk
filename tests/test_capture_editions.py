"""Every capture selector uses the current edition, not a merged Pokédex."""
from pathlib import Path
import json,sys,tempfile,unittest
from unittest.mock import patch,Mock
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.capture_target import hunt_atlas,catchable_species
from pokemon_red.pokemon_sources import encounter_index
from pokemon_red.hunting_template import wild_options

class CaptureEditions(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.base=Path(self.temp.name)
 def root(self,game):
  root=self.base/game;(root/'Data').mkdir(parents=True);(root/'vendor').symlink_to(ROOT/'vendor');(root/'Data/game.json').write_text(json.dumps(dict(game=game)));return root
 def test_complete_fire_and_leaf_target_sets_never_include_other_editions_exclusives(self):
  fire=self.root('firered');leaf=self.root('leafgreen');f=set(encounter_index(fire));l=set(encounter_index(leaf));fc=catchable_species(fire);lc=catchable_species(leaf)
  self.assertTrue(l-f);self.assertFalse(fc & (l-f));self.assertFalse(lc & (f-l));self.assertTrue(fc<=f);self.assertTrue(lc<=l)
  self.assertNotIn(27,fc);self.assertNotIn(37,fc);self.assertNotIn(69,fc);self.assertIn(23,fc);self.assertIn(58,fc);self.assertIn(43,fc)
 def test_event_only_altering_cave_tables_are_not_normal_capture_targets(self):
  from pokemon_red.capture_target import CaptureTarget,candidates
  fire=self.root('firered')
  for number in (179,190,204,213,216,228,234,235):
   self.assertNotIn(number,catchable_species(fire));self.assertFalse(candidates(CaptureTarget.parse(dict(species_id=number),fire),fire))

 def test_stale_background_template_cannot_offer_leaf_exclusives_in_firered(self):
  fire=self.root('firered');meta={'routes':{'Route1':{'population':[{'species_id':19},{'species_id':27},{'species_id':37}]}}}
  with patch('pokemon_red.hunting_template.read_json',return_value=meta):self.assertEqual(wild_options(fire),[19])
 def test_opening_impossible_capture_is_rejected_before_any_ui_mutation(self):
  from pokemon_red.catch_view import open_autocatch
  panel=Mock();panel.monitor.folder=self.root('firered')
  with self.assertRaises(ValueError):open_autocatch(panel,27)
  panel.monitor.show_battle_panel.assert_not_called()
 def test_wrong_edition_atlas_fails_closed(self):
  fire=self.root('firered');wrong=dict(hunt_atlas(fire),rom_sha1='leafgreen')
  hunt_atlas.cache_clear()
  with patch('pokemon_red.capture_target.json.loads',return_value=wrong):
   with self.assertRaises(ValueError):hunt_atlas(fire)
  hunt_atlas.cache_clear()
