"""Native RS boot, isolation, capability boundary and durable session lifecycle."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
import hashlib,json,sys,time,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.editions import RUBY,SAPPHIRE,LEAFGREEN,edition,validate_rom,available,install_rom
from pokemon_red.profiles import Profiles
from pokemon_red.engine import Game,BUTTONS
from pokemon_red.engine_runtime import EngineRuntime
from pokemon_red.telemetry import read_state
from pokemon_red.session_controller import SessionController
from pokemon_red.game_adapters import adapter
from pokemon_red.slots import Slots
from test_runtime_performance import PrivateSessionTestCase

class ProbeRuntime(EngineRuntime):
 def _dispatch(self,c,method,args):
  if method=='probe':return args[0](c)
  return super()._dispatch(c,method,args)

class HoennTests(PrivateSessionTestCase):
 def setUp(self):
  super().setUp();(self.root/'ROMs').mkdir()
  for name in ('Ruby-Rev2.gba','Sapphire-Rev2.gba'):(self.root/'ROMs'/name).symlink_to(ROOT/'ROMs'/name)
  self.store=Profiles(self.root)
 def profile(self,game):return self.store.folder(self.store.create(game=game))
 def wait(self,predicate,timeout=6):
  end=time.monotonic()+timeout
  while not predicate() and time.monotonic()<end:time.sleep(.003)
  self.assertTrue(predicate())
 def test_both_user_roms_have_expected_revision_and_hash(self):
  for game in (RUBY,SAPPHIRE):
   raw=(self.root/'ROMs'/f'{game.name}-Rev2.gba').read_bytes();self.assertEqual(validate_rom(raw,game.id),game);self.assertTrue(available(self.root,game.id))
   for other in (LEAFGREEN,RUBY if game==SAPPHIRE else SAPPHIRE):
    with self.assertRaises(ValueError):validate_rom(raw,other.id)
 def test_new_profiles_have_no_shared_progress_or_kanto_templates(self):
  before=(self.root/'Data/FireRed.state').read_bytes();folders=[self.profile(g) for g in ('ruby','sapphire')]
  for f in folders:
   self.assertFalse((f/'Data/FireRed.state').exists());self.assertFalse((f/'Data/FireRed.sav').exists());self.assertFalse((f/'templates/FireRed').exists())
  self.assertEqual((self.root/'Data/FireRed.state').read_bytes(),before);self.assertNotEqual(edition(folders[0]),edition(folders[1]))
 def test_local_import_needs_no_kanto_catalog_and_never_replaces_fire_rom(self):
  fire=(self.root/'Data/FireRed.gba').read_bytes();target=self.root/'ROMs/Ruby-Rev2.gba';target.unlink()
  install_rom(self.root,ROOT/'ROMs/Ruby-Rev2.gba','ruby');self.assertTrue(available(self.root,'ruby'));self.assertEqual((self.root/'Data/FireRed.gba').read_bytes(),fire)
 def test_native_boot_and_reopen_preserve_frame_ram_and_picture_for_both_games(self):
  for game in ('ruby','sapphire'):
   folder=self.profile(game)
   with Game(folder) as g:
    g.advance(420);g.press('A',frames=6);state=read_state(g);self.assertEqual(state['game'],edition(folder).label);self.assertTrue(adapter(folder).supports('collection'));self.assertEqual(state['party'],[])
    frame=g.frame;ram=g.read_bytes(0x02000000,0x40000);picture=g.rgb();g.save()
   with Game(folder) as g:
    self.assertEqual(g.frame,frame);self.assertEqual(g.read_bytes(0x02000000,0x40000),ram);self.assertEqual(g.rgb(),picture)
 def test_savestates_are_rejected_across_all_game_families_before_mutation(self):
  ruby=self.profile('ruby');sapphire=self.profile('sapphire')
  with Game(ruby) as a,Game(sapphire) as b,Game(self.root) as fire:
   a.advance(120);b.advance(120);frame=a.frame
   for data in (b.capture_save().state,fire.capture_save().state):
    with self.assertRaisesRegex(RuntimeError,'другой игры'):a.restore_checkpoint(data)
    self.assertEqual(a.frame,frame)
 def test_rs_named_slot_restores_through_launcher(self):
  from pokemon_red.profile_restore import restore_profile
  folder=self.profile('ruby');slots=Slots(folder)
  with Game(folder) as g:
   g.advance(180);frame=g.frame;key=slots.save(g,'RS point');g.advance(200);g.save()
  restored=restore_profile(folder,slots.get(key));self.assertEqual(restored['frame'],frame+1)
  with Game(folder) as g:self.assertEqual(g.frame,restored['frame'])
 def test_rs_uses_shared_owner_queries_and_durable_lifecycle(self):
  for game in ('ruby','sapphire'):
   folder=self.profile(game);runtime=ProbeRuntime(folder,paused=True)
   try:
    runtime.ready.result(8);self.assertIsInstance(runtime.controller,SessionController)
    self.assertEqual(adapter(folder).menus,'rs');self.assertFalse(adapter(folder).memory.save_blocks_are_pointers)
    self.assertIn('items',runtime.submit('bag').result(5))
    first=runtime.latest.frame;runtime.submit('set_speed',8).result(5);self.wait(lambda:runtime.latest.frame>first+80)
    epoch=runtime.take_control(pause=True);self.wait(lambda:runtime.latest.epoch>=epoch and runtime.latest.status['paused'])
    final=runtime.submit('probe',lambda c:(c.game.frame,hashlib.sha256(c.game.read_bytes(0x02000000,0x40000)).hexdigest())).result(5)
    runtime.take_control(close=True);runtime.finished.result(10);runtime.thread.join(1)
    self.assertFalse(runtime.thread.is_alive());self.assertFalse(runtime.latest.status['save_failed'])
   finally:
    if not runtime.finished.done():runtime.take_control(close=True);runtime.finished.result(10)
   with Game(folder) as restored:
    self.assertEqual(restored.frame,final[0]);self.assertEqual(hashlib.sha256(restored.read_bytes(0x02000000,0x40000)).hexdigest(),final[1])
 def test_new_game_dialog_can_create_ruby_and_sapphire(self):
  import tkinter as tk
  from pokemon_red.game_selection import NewGameDialog
  window=tk.Tk();window.withdraw();home=SimpleNamespace(root=window,folder=self.root,store=self.store,choose=Mock())
  try:
   for game in ('ruby','sapphire'):
    dialog=NewGameDialog(home);dialog.game.set(game);dialog.refresh();self.assertIn('Collection',dialog.support.cget('text'));dialog.create();row=home.choose.call_args.args[0];self.assertEqual(row['game'],game);self.assertEqual(edition(self.store.folder(row)).id,game)
  finally:
   window.destroy()
   del dialog,home,window
   import gc;gc.collect()

if __name__=='__main__':unittest.main()
