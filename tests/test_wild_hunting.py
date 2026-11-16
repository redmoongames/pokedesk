"""Wild hunt policy, template isolation, recovery and slot completion contracts."""
import hashlib,json,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.capture import VenusaurPolicy,catch_probability
from pokemon_red.acquisition import AcquisitionConfig,prepare_job,WILD_TEMPLATE,write_json,read_json
from pokemon_red.hunt_board import HuntBoard
from pokemon_red.hunting_template import choose_route
from pokemon_red.wild_capture import restore_capture
from pokemon_red.acquisition_play import AcquisitionAttention

class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.enemy=dict(uid='target',hp=80,max_hp=80,level=20,status_code=0,types=[0],ability_id=50,status3=0)
        self.hunter=dict(moves=[dict(id=79,current_pp=15),dict(id=73,current_pp=10)])
        self.balls={4:20,3:2,2:1};self.policy=VenusaurPolicy()
    def decide(self,rate=45,**changes):return self.policy.decide(dict(self.enemy,**changes),self.hunter,self.balls,rate)
    def test_high_chance_throws_without_sleep(self):
        row=self.decide(255);self.assertEqual((row['action'],row['ball_id']),('throw',4))
    def test_sleep_then_basic_ball_above_ten_percent(self):
        self.assertEqual(self.decide()['move_id'],79)
        row=self.decide(status_code=2);self.assertEqual((row['action'],row['ball_id']),('throw',4));self.assertGreaterEqual(row['probability'],.1)
    def test_better_ball_before_seed(self):
        row=self.decide(35,status_code=3);self.assertEqual(row['action'],'throw');self.assertEqual(row['ball_id'],3)
    def test_low_chance_sleep_then_seed_then_wait_then_stop_at_hp_boundary(self):
        self.assertEqual(self.decide(3)['move_id'],79)
        self.assertEqual(self.decide(3,status_code=2)['move_id'],73)
        row=self.decide(3,status_code=2,status3=4,hp=60);self.assertTrue(row['wait_seed'])
        row=self.decide(3,status_code=2,status3=4,hp=20);self.assertEqual(row['action'],'throw')
        row=self.decide(3,status3=4,hp=20);self.assertEqual(row['move_id'],79)
    def test_grass_immunity_no_sleep_ability_and_no_pp_do_not_loop(self):
        self.assertEqual(self.decide(3,status_code=2,types=[12])['action'],'throw')
        self.assertEqual(self.decide(45,ability_id=15)['action'],'throw')
        self.hunter['moves']=[];self.assertEqual(self.decide(3)['action'],'throw')
    def test_no_seed_at_low_hp_and_no_master_ball(self):
        self.assertEqual(self.decide(3,status_code=2,hp=20)['action'],'throw')
        self.balls={1:1};self.assertEqual(self.decide()['action'],'attention')
    def test_seed_wakeup_retries_sleep_before_other_actions(self):
        self.assertEqual(self.decide(255,status3=4)['move_id'],79)
    def test_boundaries_use_inclusive_thresholds(self):
        with patch('pokemon_red.capture.catch_probability',return_value=dict(probability=.2)):
            self.assertEqual(self.decide()['action'],'throw')
        with patch('pokemon_red.capture.catch_probability',return_value=dict(probability=.1)):
            self.assertEqual(self.decide(status_code=1)['ball_id'],4)

class WildJobsTests(unittest.TestCase):
    def test_config_source_is_explicit_and_strict(self):
        self.assertEqual(AcquisitionConfig.parse(dict(species_id=19,source='wild')).source,'wild')
        for cfg in (dict(species_id=19),dict(species_id=19,source='wild',train=True),dict(species_id=19,source='../bad'),dict(species_id=True,source='wild')):
            with self.assertRaises(ValueError):AcquisitionConfig.parse(cfg)
    def test_progressed_template_copied_not_shared_and_unsupported_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'vendor').symlink_to(ROOT/'vendor');f=root/WILD_TEMPLATE;f.mkdir(parents=True)
            (f/'FireRed.state').write_bytes(b'state');(f/'FireRed.sav').write_bytes(b'flash')
            write_json(f/'metadata.json',dict(routes={'Route1':dict(population=[dict(species_id=19)])}))
            write_json(f/'manifest.json',dict(algorithm='sha256',files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in f.iterdir()}))
            job=prepare_job(root,dict(species_id=19,source='wild'))
            (job/'Data/FireRed.state').write_bytes(b'changed');self.assertEqual((f/'FireRed.state').read_bytes(),b'state')
            with self.assertRaises(ValueError):prepare_job(root,dict(species_id=25,source='wild'))
    def test_completed_transfer_frees_slot_and_retains_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            b=HuntBoard(Path(tmp));b.assign(0,dict(species_id=1));b.slot(0)['job_id']='a'*32;b.save()
            b.reconcile([dict(id='a'*32,status='ready')]);self.assertIsNotNone(b.slot(0)['config'])
            b.reconcile([dict(id='a'*32,status='transferred')]);self.assertEqual(b.slot(0),dict(config=None,job_id=None));self.assertEqual(len(b.data['history']),1)
            b.reconcile([dict(id='a'*32,status='transferred')]);self.assertEqual(len(b.data['history']),1)
    def test_unstarted_assignment_can_be_cancelled(self):
        with tempfile.TemporaryDirectory() as tmp:
            b=HuntBoard(Path(tmp));b.assign(1,dict(species_id=7));b.cancel(1);self.assertIsNone(b.slot(1)['config'])
    def test_route_prioritizes_frequency_then_level(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'vendor').symlink_to(ROOT/'vendor');f=root/WILD_TEMPLATE;f.mkdir(parents=True)
            def route(p,l):return dict(population=[dict(species_id=19,probability=p,min_level=l,max_level=l,hp_max=20)],encounter_rate=21,area=dict(cost=[0,30]))
            write_json(f/'metadata.json',dict(routes={'low':route(30,2),'frequent':route(50,5),'harder':route(50,20)}))
            with patch('pokemon_red.catalog.species',return_value=dict(catch_rate=255)):self.assertEqual(choose_route(root,19),'frequent')
    def test_interrupted_retry_falls_back_to_verified_original_encounter(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);step=root/'checkpoints/capture-current';base=root/'checkpoints/encounter-a';base.mkdir(parents=True);step.mkdir()
            for f in (step,base):
                (f/'FireRed.state').write_bytes(b'valid');(f/'FireRed.sav').write_bytes(b'sav')
                write_json(f/'manifest.json',{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in f.iterdir()})
            (step/'FireRed.state').write_bytes(b'corrupt')
            write_json(root/'capture-session.json',dict(uid='a',encounter='checkpoints/encounter-a'))
            game=SimpleNamespace(root=root,load_state=Mock());p=SimpleNamespace(g=game,persist=Mock())
            restore_capture(p);game.load_state.assert_called_once_with(base/'FireRed.state')
            (base/'FireRed.sav').write_bytes(b'broken')
            with self.assertRaises(AcquisitionAttention):restore_capture(p)
    def test_encounter_survives_crash_before_journal_publication(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);base=root/'checkpoints/encounter-a';base.mkdir(parents=True)
            (base/'FireRed.state').write_bytes(b'found');(base/'FireRed.sav').write_bytes(b'sav')
            write_json(base/'metadata.json',dict(state=dict(battle=dict(enemies=[dict(uid='a',species_id=19,shiny=True)]))))
            write_json(base/'manifest.json',{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in base.iterdir()})
            game=SimpleNamespace(root=root,load_state=Mock());p=SimpleNamespace(g=game,persist=Mock(),w=SimpleNamespace(config=AcquisitionConfig.parse(dict(species_id=19,source='wild',shiny=True))))
            restore_capture(p);game.load_state.assert_called_once_with(base/'FireRed.state');self.assertEqual(read_json(root/'capture-session.json')['uid'],'a')

if __name__=='__main__':unittest.main()
