"""New-game validation, isolated native prologues and cancellation frontiers."""
from pathlib import Path
from types import SimpleNamespace
import hashlib,json,shutil,sys,tempfile,time,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.new_game_config import NewGameConfig,valid_name,mon_gender,STATS
from pokemon_red.models import STAT_KEYS
from pokemon_red.engine import Game
from pokemon_red.journey import Journey
from pokemon_red.prologue import Prologue
from pokemon_red.acquisition_play import JobPaused
from pokemon_red.telemetry import read_state,symbols
from pokemon_red.game_layout import save_block

class ConfigTests(unittest.TestCase):
    def test_names_match_game_keyboard_and_seven_character_limit(self):
        for name in ('ALEX','Max7!','A B','Abcdef7','M…♀','O’NEIL'):self.assertEqual(valid_name(name),name)
        for name in ('','        ','12345678','Алекс','A\nB',' A','A ','_','🙂',None):
            with self.subTest(name=name),self.assertRaises(ValueError):valid_name(name)
    def test_options_are_strict_and_share_the_decoded_stat_order(self):
        self.assertEqual(STATS,STAT_KEYS)
        for patch in (dict(min_ivs=[32]*6),dict(min_ivs=[True]*6),dict(min_ivs=[1]*5),dict(nature=25),dict(nature=True),dict(player_gender=True),dict(shiny=1),dict(gender='boy'),dict(species_id=25)):
            with self.subTest(patch=patch),self.assertRaises(ValueError):NewGameConfig.parse(patch)
        with self.assertRaises(ValueError):NewGameConfig.parse({},'ruby')
    def test_matching_checks_all_six_ivs_shiny_gender_and_nature(self):
        cfg=NewGameConfig.parse(dict(species_id=7,min_ivs=[1,2,3,4,5,6],shiny=True,gender='male',nature=3))
        mon=dict(species_id=7,checksum_valid=True,personality=256+31,nature=3,shiny=True,ivs=dict(zip(STATS,[1,2,3,4,5,6])))
        self.assertTrue(cfg.matches(mon));self.assertEqual(mon_gender(dict(personality=30)),'female');self.assertEqual(mon_gender(dict(personality=31)),'male')
        for key in STATS:
            changed=dict(mon,ivs=dict(mon['ivs']));changed['ivs'][key]-=1;self.assertFalse(cfg.matches(changed))
        for patch in (dict(shiny=False),dict(personality=30),dict(nature=4),dict(checksum_valid=False),dict(is_egg=True)):self.assertFalse(cfg.matches(dict(mon,**patch)))
    def test_rarity_estimate_does_not_promise_a_completion_time(self):
        self.assertEqual(NewGameConfig().expected_attempts(),1)
        self.assertEqual(NewGameConfig(shiny=True).expected_attempts(),8192)
        self.assertGreater(NewGameConfig(shiny=True,min_ivs=(31,)*6).expected_attempts(),10**12)

class Worker:
    pacer=None
    def __init__(self):self.stop_after=None;self.prologue=None
    def heartbeat(self):pass
    def update(self,**kw):pass
    def event(self,*a,**kw):pass
    def safe_point(self):
        if self.stop_after is not None and self.prologue.progress['attempts']>=self.stop_after:raise JobPaused()

class NativePrologueTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);(self.root/'Data').mkdir()
        for name in ('src','native','vendor','assets','runtime','Bots'):(self.root/name).symlink_to(ROOT/name)
        (self.root/'Data/FireRed.gba').symlink_to(ROOT/'Data/FireRed.gba')
    def test_custom_names_female_character_and_selected_starter_reach_free_world(self):
        with Game(self.root,resume=False) as game:
            game.advance(120);worker=Worker();p=Journey(game,worker)
            config=NewGameConfig.parse(dict(player_name='M A7!',rival_name='Green',player_gender=1,species_id=4,gender='male',nature=3,min_ivs=[0,10,0,0,0,0]))
            prologue=Prologue(p,config.json());worker.prologue=prologue;mon=prologue.run();s=p.state()
            self.assertTrue(config.matches(mon));self.assertEqual(s['player'],'M A7!');self.assertEqual(s['map']['name'],'PalletTown')
            self.assertEqual(game.read8(save_block(game,2)+8),1);self.assertFalse(s['controls']['field_locked']);self.assertFalse(s['in_battle']);self.assertEqual(prologue.progress['phase'],'complete')
            self.assertEqual(s['party'][0]['uid'],prologue.progress['found']['uid']);self.assertEqual(p.var(0x4055),4)
    def test_cancelled_search_preserves_empty_party_and_resumes_new_candidates(self):
        fixture=ROOT/'templates/FireRed/ALEX-before-starter-v1'
        before=hashlib.sha256((fixture/'FireRed.state').read_bytes()).hexdigest()
        with Game(self.root,resume=False) as game:
            game.load_state(fixture/'FireRed.state');worker=Worker();p=Journey(game,worker)
            impossible=NewGameConfig.parse(dict(species_id=7,min_ivs=[31]*6,shiny=True))
            prologue=Prologue(p,impossible.json());worker.prologue=prologue;prologue.choice();prologue.progress['phase']='search';worker.stop_after=3
            with self.assertRaises(JobPaused):prologue.search()
            self.assertGreaterEqual(prologue.progress['attempts'],3);self.assertFalse(p.state()['party'])
            worker.stop_after=None;resume=Prologue(p,dict(species_id=7),prologue.progress);worker.prologue=resume
            mon=resume.run();self.assertEqual(mon['species_id'],7);self.assertEqual(p.state()['player'],'ALEX');self.assertGreater(resume.progress['attempts'],3)
        self.assertEqual(hashlib.sha256((fixture/'FireRed.state').read_bytes()).hexdigest(),before)

class NewGameFormTests(unittest.TestCase):
    def test_new_profile_config_is_validated_before_creating_any_directory(self):
        from pokemon_red.profiles import Profiles
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'Data').mkdir();store=Profiles(root)
            with self.assertRaises(ValueError):store.create(prologue=dict(player_name='TooLong!'))
            self.assertFalse((root/'Profiles').exists());self.assertFalse((root/'Data/profiles.json').exists())
    def test_form_uses_ids_and_exposes_iv_inputs_with_fixed_footer(self):
        import tkinter as tk
        from unittest.mock import Mock
        from pokemon_red.game_selection import NewGameDialog
        root=tk.Tk();root.withdraw()
        try:
            home=SimpleNamespace(root=root,folder=ROOT,store=Mock(),choose=Mock());dialog=NewGameDialog(home)
            dialog.skip.set(True);dialog.refresh();dialog.window.update_idletasks()
            self.assertEqual(len(dialog.ivs),6);self.assertEqual(dialog.config().species_id,1)
            dialog.nature.set(3);dialog.ivs['attack'].set(31);self.assertEqual(dialog.config().nature,3);self.assertEqual(dialog.config().min_ivs[1],31)
            self.assertLessEqual(dialog.start.winfo_rooty()+dialog.start.winfo_height(),dialog.window.winfo_rooty()+dialog.window.winfo_height())
            dialog.game.set('ruby');dialog.refresh();self.assertFalse(dialog.skip.get());dialog.close()
        finally:root.destroy()
