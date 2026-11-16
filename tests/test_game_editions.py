"""Edition identity, isolated profiles, exact references and native save guards."""
from pathlib import Path
from types import SimpleNamespace
import tempfile,json,sys,hashlib,shutil,unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.editions import FIRERED,LEAFGREEN,edition,rom_path,validate_rom,reference_path,install_rom
from pokemon_red.profiles import Profiles
from pokemon_red.engine import Game
from pokemon_red.telemetry import symbols,read_state
from pokemon_red.catalog import catalog
from pokemon_red.capture_target import CaptureTarget,candidates
from pokemon_red.slots import Slots
from test_runtime_performance import PrivateSessionTestCase

class EditionTests(PrivateSessionTestCase):
 def setUp(self):
  super().setUp();(self.root/'ROMs').mkdir();(self.root/'ROMs/LeafGreen-Rev1.gba').symlink_to(ROOT/'ROMs/LeafGreen-Rev1.gba');self.store=Profiles(self.root)
 def leaf(self):return self.store.folder(self.store.create('Leaf QA',game='leafgreen'))
 def test_legacy_is_firered_without_moving_or_rewriting_its_save(self):
  p=self.root/'Data/FireRed.state';before=p.read_bytes();r=self.store.list()[0];self.assertEqual(r['game'],'firered');self.assertEqual(edition(self.root),FIRERED);self.assertEqual(p.read_bytes(),before)
 def test_new_leaf_profile_is_empty_and_has_its_own_rom_and_config(self):
  leaf=self.leaf();self.assertEqual(edition(leaf),LEAFGREEN);self.assertFalse((leaf/'Data/FireRed.state').exists());self.assertFalse((leaf/'Data/FireRed.sav').exists())
  self.assertEqual(hashlib.sha1((leaf/'Data/FireRed.gba').read_bytes()).hexdigest(),LEAFGREEN.sha1);self.assertFalse((leaf/'templates/FireRed/ALEX-before-starter-v1').exists())
 def test_wrong_rom_and_unknown_edition_are_rejected(self):
  with self.assertRaises(ValueError):validate_rom((self.root/'Data/FireRed.gba').read_bytes(),'leafgreen')
  with self.assertRaises(ValueError):self.store.create(game='ruby')
 def test_native_symbols_and_references_follow_edition(self):
  leaf=self.leaf();self.assertNotEqual(symbols(leaf)['gBattleMoves'],symbols(self.root)['gBattleMoves'])
  self.assertEqual(symbols(leaf)['gPlayerParty'],symbols(self.root)['gPlayerParty']);self.assertEqual(catalog(leaf)['rom_sha1'],LEAFGREEN.sha1)
  deoxys=next(m for m in catalog(leaf)['species'].values() if m['national_id']==386);self.assertEqual(deoxys['base_stats']['defense'],160);self.assertEqual(deoxys['base_stats']['attack'],70)
 def test_leaf_exclusives_are_not_fire_encounters(self):
  leaf=self.leaf();target=dict(species_id=27)
  self.assertTrue(candidates(CaptureTarget.parse(target,leaf),leaf));self.assertFalse(candidates(CaptureTarget.parse(target,self.root),self.root))
  self.assertFalse(candidates(CaptureTarget.parse(dict(species_id=23),leaf),leaf));self.assertTrue(candidates(CaptureTarget.parse(dict(species_id=23),self.root),self.root))
 def test_native_leaf_checkpoint_reopens_and_fire_state_never_loads_into_it(self):
  leaf=self.leaf()
  with Game(leaf) as g:
   g.advance(160);frame=g.frame;snapshot=g.capture_save();g.save()
   with self.assertRaisesRegex(RuntimeError,'другой игры'):g.load_state(self.root/'Data/FireRed.state')
   self.assertEqual(g.frame,frame)
   with Game(self.root) as other:
    with self.assertRaisesRegex(RuntimeError,'другой игры'):other.restore_checkpoint(snapshot.state)
  with Game(leaf) as restored:self.assertEqual(restored.frame,frame);self.assertEqual(restored.rom_sha1,LEAFGREEN.sha1)
 def test_leaf_slot_metadata_is_scoped_to_leaf_rom(self):
  leaf=self.leaf();slots=Slots(leaf)
  with Game(leaf) as g:g.advance(120);key=slots.save(g,'Leaf slot')
  row=slots.get(key);self.assertEqual(row['rom_sha1'],LEAFGREEN.sha1)
  target=self.root/'Data/slots'/key;target.parent.mkdir(exist_ok=True);shutil.copytree(row['directory'].parent,target)
  with self.assertRaisesRegex(ValueError,'другой версии'):Slots(self.root).get(key)
 def test_clone_carries_leaf_identity_and_never_uses_fire_symbols(self):
  from pokemon_red.operations import clone_session
  leaf=self.leaf()
  with Game(leaf) as g:g.advance(10);snap=g.capture_save()
  folder=clone_session(leaf,self.root/'copy',snap)
  with Game(folder) as restored:self.assertEqual(restored.rom_sha1,LEAFGREEN.sha1);self.assertEqual(restored.frame,snap.frame)
 def test_dex_edition_labels_match_current_game(self):
  from pokemon_red.dex_reference import origin_label
  leaf=self.leaf();self.assertTrue(origin_label(27,leaf).startswith('LeafGreen'));self.assertTrue(origin_label(23,leaf).startswith('FireRed'))
 def test_new_game_dialog_selects_edition_before_creation(self):
  import tkinter as tk
  from pokemon_red.game_selection import NewGameDialog
  from unittest.mock import Mock
  window=tk.Tk();window.withdraw();home=SimpleNamespace(root=window,folder=self.root,store=self.store,choose=Mock())
  try:
   dialog=NewGameDialog(home);dialog.game.set('leafgreen');dialog.refresh();dialog.create();row=home.choose.call_args.args[0];self.assertEqual(row['game'],'leafgreen');self.assertEqual(edition(self.store.folder(row)),LEAFGREEN)
  finally:window.destroy()
 def test_leaf_hunting_never_reuses_fire_template(self):
  from pokemon_red.acquisition import verify_template,TEMPLATE,template_for,prepare_job
  leaf=self.leaf();self.assertIn('/LeafGreen/',template_for(leaf,TEMPLATE))
  fire=leaf/TEMPLATE;fire.mkdir(parents=True)
  (fire/'manifest.json').write_text(json.dumps(dict(algorithm='sha256',files={})))
  with self.assertRaisesRegex(ValueError,'LeafGreen'):prepare_job(leaf,dict(species_id=1))
 def test_leaf_preview_worker_inherits_rom_identity(self):
  from pokemon_red.travel_service import TravelService
  from unittest.mock import Mock
  leaf=self.leaf();service=TravelService();checked=[]
  def spawn(args,**kwargs):
   folder=Path(args[4]);checked.append(edition(folder))
   self.assertEqual(edition(folder),LEAFGREEN)
   process=Mock(returncode=0);process.communicate.return_value=('[]','');return process
  try:
   with patch('pokemon_red.travel_service.subprocess.Popen',side_effect=spawn):
    self.assertEqual(service.compute(leaf,b'checkpoint',False,0),[])
   self.assertEqual(checked,[LEAFGREEN])
  finally:service.close()

if __name__=='__main__':unittest.main()
