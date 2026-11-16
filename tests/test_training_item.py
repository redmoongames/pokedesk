"""Held-item menu round trips, validation and out-of-band cancellation."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import sys,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.training_item import TrainingItemRuntime
from pokemon_red.telemetry import read_state
from pokemon_red.engine import Game
from pokemon_red.field_actions import FieldMismatch

class TrainingItemTests(unittest.TestCase):
    def test_native_menu_take_and_give_roundtrip_preserves_party_and_item(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);(root/'Data').mkdir()
            for name in ('native','vendor'):(root/name).symlink_to(ROOT/name)
            (root/'Data/FireRed.gba').symlink_to(ROOT/'Data/FireRed.gba')
            for name in ('FireRed.state','FireRed.sav'):(root/'Data'/name).write_bytes((ROOT/'templates/items/antidote-v1/ready'/name).read_bytes())
            with Game(root) as game:
                before=read_state(game)['party'];uid=next(m['uid'] for m in before if m['held_item']==14)
                for take in (True,False):
                    if take:runtime=TrainingItemRuntime(game,dict(uid=uid,take=True))
                    else:
                        with patch.object(TrainingItemRuntime,'quantity',return_value=1):runtime=TrainingItemRuntime(game,dict(uid=uid))
                    # Antidote is available in a verified fixture; use the same
                    # production menu path without writing any game memory.
                    runtime.item=14;runtime.before=runtime.quantity(game)
                    for _ in range(5401):
                        if runtime.poll(game):break
                        game.advance(1,runtime.mask)
                    else:self.fail('Held item round trip did not finish')
                    self.assertEqual(runtime.result['taken'],take)
                self.assertEqual([(m['uid'],m['held_item']) for m in before],[(m['uid'],m['held_item']) for m in read_state(game)['party']])
    def runtime(self,held=0,**args):
        game=SimpleNamespace(frame=100,root=ROOT);mon=dict(uid='t',slot=1,held_item=held);state=dict(party=[mon],controls=dict(callback='CB2_Overworld',field_locked=False))
        with patch('pokemon_red.training_item.read_state',return_value=state),patch.object(TrainingItemRuntime,'quantity',return_value=1):runtime=TrainingItemRuntime(game,dict(uid='t',**args))
        return game,mon,runtime
    def test_lucky_egg_id_and_take_validation(self):
        game,mon,runtime=self.runtime();self.assertEqual(runtime.item,197)
        for item in (0,121,132):
            with self.assertRaises(ValueError):self.runtime(item,take=True)
        with self.assertRaises(ValueError):self.runtime(197)
    def test_cancelled_action_never_sends_late_button(self):
        game,mon,runtime=self.runtime();runtime.mask=1;runtime.cancel();game.frame+=100
        self.assertFalse(runtime.poll(game));self.assertEqual(runtime.mask,0)
    def test_wrong_selected_party_member_cannot_receive_item(self):
        game,mon,runtime=self.runtime();runtime.phase='party';controls=dict(tasks=[dict(name='Task_HandleSelectionMenuInput')],party_cursor=2,party_actions=[0,1,3,2],menu_cursor=2)
        with patch('pokemon_red.training_item.read_controls',return_value=controls),patch('pokemon_red.training_item.read_walk_state',return_value={}),patch('pokemon_red.training_item.read_learning_mon',return_value=mon),patch('pokemon_red.training_item.symbols',return_value={'gPaletteFade':0}):
            game.read8=lambda _:0
            with self.assertRaises(FieldMismatch):runtime.poll(game)
