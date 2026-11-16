import math,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from pokemon_red.search_odds import trial_estimate,hunt_estimates,estimate
from pokemon_red.capture_target import CaptureTarget
ROOT=Path(__file__).resolve().parents[1]

class Estimates(unittest.TestCase):
 def test_mean_and_quantiles_are_distinct_and_inclusive(self):
  r=trial_estimate(.05);self.assertEqual(r['mean'],20);self.assertEqual(r['p90'],45)
  self.assertGreaterEqual(1-(1-.05)**r['p90'],.9);self.assertLess(1-(1-.05)**(r['p90']-1),.9)
 def test_very_rare_events_do_not_round_to_impossible(self):
  r=trial_estimate(1e-18);self.assertAlmostEqual(r['mean']/1e18,1);self.assertGreater(r['p90'],2e18)
 def test_impossible_guaranteed_and_invalid(self):
  self.assertIsNone(trial_estimate(0)['mean']);self.assertEqual(trial_estimate(1),dict(mean=1,median=1,p90=1,p95=1))
  for value in (-.1,1.1,float('nan'),float('inf')):
   with self.assertRaises(ValueError):trial_estimate(value)
 def test_encounter_filters_and_throws_are_not_multiplied_into_one_count(self):
  odds=estimate([0]*6,gender='any',encounter=.1,throw=.25);r=hunt_estimates(odds)
  self.assertEqual(r['encounters']['mean'],10);self.assertEqual(r['throws']['mean'],4)
 def test_stars_do_not_change_filter_probability(self):
  from pokemon_red.search_odds import wild_odds
  cfg=dict(species_id=43,gender='any');a=wild_odds(CaptureTarget.parse(cfg,ROOT),ROOT,encounter=.35);b=wild_odds(CaptureTarget.parse(dict(cfg,priority_ivs=['speed']),ROOT),ROOT,encounter=.35)
  self.assertEqual(hunt_estimates(a),hunt_estimates(b))
 def test_six_wild_workers_are_supported_without_changing_starter_limit(self):
  from pokemon_red.new_game_config import NewGameConfig
  self.assertEqual(CaptureTarget.parse(dict(species_id=43,search_workers=6),ROOT).search_workers,6)
  with self.assertRaises(ValueError):CaptureTarget.parse(dict(species_id=43,search_workers=7),ROOT)
  with self.assertRaises(ValueError):NewGameConfig.parse(dict(search_workers=5))
