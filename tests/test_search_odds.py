"""Explicit probability units, OR-nature filters and bounded native search lanes."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import hashlib,sys,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.search_odds import estimate,starter_odds,wild_odds,gender_chance,percent
from pokemon_red.new_game_config import NewGameConfig
from pokemon_red.capture_target import CaptureTarget
from pokemon_red.nature_preferences import accepted,STATS
from pokemon_red.models import STAT_KEYS

class ProbabilityTests(unittest.TestCase):
    def test_bulbasaur_ten_ivs_male_modest_and_four_natures(self):
        cfg=NewGameConfig.parse(dict(min_ivs=[10]*6,gender='male',natures=[15]))
        odds=starter_odds(cfg);expected=(22/32)**6*(225/256)/25
        self.assertAlmostEqual(odds['filters'],expected);self.assertEqual(odds['throw'],1);self.assertEqual(odds['encounter'],1)
        broad=starter_odds(NewGameConfig.parse(dict(cfg.json(),nature=None,natures=[5,10,15,20])))
        self.assertAlmostEqual(broad['filters'],expected*4)
    def test_wild_encounter_and_throw_are_separate_from_traits(self):
        target=CaptureTarget.parse
        cfg=SimpleNamespace(species_id=25,required_ivs=(0,)*6,min_ivs=(0,)*6,gender='any',natures=(15,),shiny=False)
        with patch('pokemon_red.capture_target.hunt_atlas',return_value=dict(species={'25':dict(gender_ratio=127)})),patch('pokemon_red.catalog.species',return_value=dict(catch_rate=190)):
            odds=wild_odds(cfg,ROOT,encounter=.05)
        self.assertAlmostEqual(odds['filters'],(8191/8192)/25)
        self.assertAlmostEqual(odds['target'],.05*odds['filters'])
        self.assertAlmostEqual(odds['captured'],odds['target']*odds['throw']);self.assertLess(odds['throw'],1)
    def test_gender_boundaries_and_impossible_gender_have_zero_probability(self):
        self.assertEqual(gender_chance('male',31),225/256)
        self.assertEqual(gender_chance('genderless',255),1);self.assertEqual(gender_chance('female',255),0)
        self.assertEqual(gender_chance('female',254),1);self.assertEqual(gender_chance('male',0),1)
        self.assertEqual(estimate([0]*6,gender='female',ratio=0)['target'],0)
    def test_worker_bounds_and_nature_values_are_strict(self):
        for workers in (0,5,True,2.5):
            with self.assertRaises(ValueError):NewGameConfig.parse(dict(search_workers=workers))
        for values in ([-1],[25],[True],'15'):
            with self.assertRaises(ValueError):NewGameConfig.parse(dict(natures=values))
        self.assertEqual(NewGameConfig.parse(dict(nature=15)).natures,(15,))
        self.assertEqual(NewGameConfig.parse(dict(natures=[20,15,15])).natures,(15,20))
    def test_rare_filters_remain_visible_instead_of_rounding_to_zero(self):
        odds=starter_odds(NewGameConfig.parse(dict(min_ivs=[31]*6,gender='female',natures=[15],shiny=True)))
        self.assertGreater(odds['filters'],0)
        self.assertNotEqual(percent(odds['filters']),'0.00%')
        self.assertIn('e-',percent(odds['filters']))

class NaturePriorityTests(unittest.TestCase):
    def test_priorities_generate_one_or_several_actual_natures(self):
        roles=dict.fromkeys(STATS,'protect');roles.update(attack='dump',special_attack='prefer')
        self.assertEqual(accepted(roles),(15,))
        roles['special_defense']='prefer';self.assertEqual(accepted(roles),(15,20))
        self.assertEqual(accepted(dict.fromkeys(STATS,'protect')),(0,6,12,18,24))
        self.assertEqual(len(accepted(dict.fromkeys(STATS,'any'))),25)
    def test_wild_matcher_enforces_the_nature_or_list(self):
        target=CaptureTarget(25,False,'any',(0,)*6,natures=(5,15))
        mon=dict(checksum_valid=True,species_id=25,level=5,shiny=False,personality=15,ivs=dict.fromkeys(STAT_KEYS,10))
        self.assertTrue(target.matches(mon,ROOT));self.assertFalse(target.matches(dict(mon,personality=3),ROOT))

class NativeLaneTests(unittest.TestCase):
    def setUp(self):
        from pokemon_red.engine import Game
        from pokemon_red.journey import Journey
        from pokemon_red.prologue import Prologue
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);root=self.root=Path(self.temp.name);(root/'Data').mkdir()
        for n in ('native','vendor','assets','runtime'):(root/n).symlink_to(ROOT/n)
        (root/'Data/FireRed.gba').symlink_to(ROOT/'Data/FireRed.gba')
        self.g=Game(root,resume=False);self.addCleanup(self.g.close)
        fixture=ROOT/'templates/FireRed/ALEX-before-starter-v1/FireRed.state';self.before=hashlib.sha256(fixture.read_bytes()).hexdigest();self.fixture=fixture
        self.g.load_state(fixture)
        self.worker=SimpleNamespace(pacer=None,heartbeat=lambda:None,safe_point=lambda:None,update=lambda **kw:None,event=lambda *a,**kw:None)
        Prologue(Journey(self.g,self.worker),dict(species_id=1)).choice()
    def test_two_lanes_are_distinct_and_found_state_is_verified(self):
        from pokemon_red.starter_search import search
        cfg=NewGameConfig.parse(dict(min_ivs=[10]*6,gender='male',natures=[15],search_workers=2))
        mon,stats=search(self.g,cfg,self.worker,dict(attempts=0))
        self.assertTrue(cfg.matches(mon));self.assertEqual(stats['workers'],2)
        samples=[set(v.get('sample',[])) for v in stats['lanes']];self.assertFalse(samples[0]&samples[1])
        self.assertEqual(hashlib.sha256(self.fixture.read_bytes()).hexdigest(),self.before)
    def test_cancelled_pool_preserves_a_pre_gift_frontier_and_can_resume(self):
        from pokemon_red.starter_search import search
        from pokemon_red.acquisition_play import JobPaused
        from pokemon_red.telemetry import symbols
        progress=dict(attempts=0)
        def cancel():
            if progress['attempts']>=1:raise JobPaused()
        self.worker.safe_point=cancel
        with self.assertRaises(JobPaused):search(self.g,NewGameConfig.parse(dict(min_ivs=[31]*6,shiny=True)),self.worker,progress)
        self.assertGreater(progress['attempts'],0);self.assertEqual(self.g.read8(symbols(self.root)['gPlayerPartyCount']),0)
        previous=progress['attempts'];self.worker.safe_point=lambda:None
        mon,stats=search(self.g,NewGameConfig.parse(dict(gender='male')),self.worker,progress)
        self.assertEqual(mon['species_id'],1);self.assertGreater(progress['attempts'],previous)
    def test_cancellation_during_child_shutdown_rejects_a_late_winner(self):
        import subprocess
        from pokemon_red.starter_search import search
        from pokemon_red.acquisition_play import JobPaused
        from pokemon_red.telemetry import symbols
        cancelled=False;original=subprocess.Popen
        def spawn(*args,**kwargs):
            process=original(*args,**kwargs);wait=process.wait
            def joined(*a,**kw):
                nonlocal cancelled
                result=wait(*a,**kw);cancelled=True;return result
            process.wait=joined;return process
        def safe_point():
            if cancelled:raise JobPaused()
        self.worker.safe_point=safe_point
        with patch('pokemon_red.starter_search.subprocess.Popen',side_effect=spawn),self.assertRaises(JobPaused):
            search(self.g,NewGameConfig.parse(dict(search_workers=1)),self.worker,dict(attempts=0))
        self.assertEqual(self.g.read8(symbols(self.root)['gPlayerPartyCount']),0)
