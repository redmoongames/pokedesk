"""Acquisition safety: integer catch odds, isolation and permanent checkpoints."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.capture import catch_probability,ball_multiplier,CapturePolicy
from pokemon_red.acquisition import AcquisitionConfig,prepare_job,verify_template,TEMPLATE
from pokemon_red.acquisition_play import Player,AcquisitionAttention

class CatchTests(unittest.TestCase):
    def test_firered_integer_vectors(self):
        for rate,hp,maximum,ball,status,odds,threshold in [(255,20,20,4,0,85,49931),(45,20,20,4,0,15,32767),(45,1,20,4,1,86,52428),(45,20,20,2,0,30,38835)]:
            result=catch_probability(rate,hp,maximum,ball_id=ball,status=status)
            self.assertEqual(result['odds'],odds);self.assertEqual(result['shake_threshold'],threshold)
        self.assertTrue(catch_probability(255,1,20,status=1)['guaranteed'])
        self.assertEqual(catch_probability(3,20,20,ball_id=1)['probability'],1)
        self.assertEqual(catch_probability(1,20,20)['probability'],0)
    def test_ball_conditions_and_hp_validation(self):
        self.assertEqual(ball_multiplier(6,types=[11]),30);self.assertEqual(ball_multiplier(6,types=[0]),10)
        self.assertEqual(ball_multiplier(8,level=5),35);self.assertEqual(ball_multiplier(10,turns=99),40)
        with self.assertRaises(ValueError):catch_probability(45,0,20)
        with self.assertRaises(ValueError):catch_probability(45,21,20)
        with self.assertRaises(ValueError):catch_probability(45,20,20,ball_id=5)
    def test_policy_rejects_possible_ko_or_unverified_damage(self):
        safe=dict(move_id=33,max_critical_damage=4,verified_bound=True,catch_probability_after=.35,survival_probability=1)
        self.assertEqual(CapturePolicy().decide(.2,10,[safe])['action'],'throw')
        self.assertEqual(CapturePolicy().decide(.1,10,[safe])['action'],'weaken')
        for changes in [dict(max_critical_damage=10),dict(verified_bound=False),dict(residual_damage=True),dict(recoil=True),dict(survival_probability=.8)]:
            self.assertEqual(CapturePolicy().decide(.1,10,[dict(safe,**changes)])['action'],'throw')

class IsolationTests(unittest.TestCase):
    def test_only_three_starters_and_strict_options(self):
        for data in [dict(species_id=25),dict(species_id=True),dict(target_level=101),dict(shiny=1),dict(train='yes')]:
            with self.assertRaises(ValueError):AcquisitionConfig.parse(data)
    def test_template_copy_is_independent_and_corruption_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);template=root/TEMPLATE;template.mkdir(parents=True)
            for name in ['FireRed.state','FireRed.sav','metadata.json']:(template/name).write_bytes(name.encode())
            manifest=dict(algorithm='sha256',files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in template.iterdir()})
            (template/'manifest.json').write_text(json.dumps(manifest))
            job=prepare_job(root,AcquisitionConfig(7,True));(job/'Data/FireRed.state').write_bytes(b'changed')
            self.assertEqual((template/'FireRed.state').read_bytes(),b'FireRed.state');self.assertFalse((job/'Data/FireRed.sav').is_symlink())
            (template/'FireRed.sav').write_bytes(b'bad')
            with self.assertRaises(ValueError):verify_template(root)
            manifest['files']['../outside']='0';(template/'manifest.json').write_text(json.dumps(manifest))
            with self.assertRaises(ValueError):verify_template(root)
    def test_found_checkpoint_is_immutable_to_worker_and_hash_checked(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'checkpoints').mkdir()
            def save(folder):
                folder.mkdir();(folder/'FireRed.state').write_bytes(b'found');(folder/'FireRed.sav').write_bytes(b'flash')
            game=SimpleNamespace(root=root,frame=4,save_to=save)
            player=Player(game,None)
            with patch.object(player,'state',return_value={'party':[]}):folder=player.checkpoint('found',permanent=True)
            self.assertEqual(os.stat(folder/'FireRed.state').st_mode&0o777,0o444)
            self.assertEqual(player.checkpoint('found',permanent=True),folder)
            folder.chmod(0o755);state=folder/'FireRed.state';state.chmod(0o644);state.write_bytes(b'corrupt')
            with self.assertRaises(AcquisitionAttention):player.checkpoint('found',permanent=True)
            for p in folder.iterdir():p.chmod(0o644)

if __name__=='__main__':unittest.main()
