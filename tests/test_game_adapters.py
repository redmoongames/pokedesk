"""Cross-edition contracts and native RS input, exclusively on private Data."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import json,shutil,sys,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from test_runtime_performance import PrivateSessionTestCase
from pokemon_red.profiles import Profiles
from pokemon_red.engine import Game
from pokemon_red.telemetry import read_state
from pokemon_red.game_adapters import for_id
from pokemon_red.acquisition import starters_for,verify_template
from pokemon_red.hoenn_acquisition import prepare_choice
from pokemon_red.journey import Journey
from pokemon_red.storage import Storage
from pokemon_red.models import read_inventory
from pokemon_red.catalog import catalog
from pokemon_red.pokemon_sources import encounters,source_data
from pokemon_red.region_map import destination,atlas
from pokemon_red.field_tools import available,party_cut
from pokemon_red.trade import perform_trade
from pokemon_red.acquisition_play import AcquisitionAttention
from pokemon_red.capture import VenusaurPolicy,capture_kit

class Worker:
 def heartbeat(self):pass
 def safe_point(self):pass
 def event(self,*a,**kw):pass
 def update(self,**kw):pass

class AdapterTests(PrivateSessionTestCase):
 def setUp(self):
  super().setUp();(self.root/'ROMs').mkdir()
  for name in ('Ruby-Rev2.gba','Sapphire-Rev2.gba'):(self.root/'ROMs'/name).symlink_to(ROOT/'ROMs'/name)
  self.profiles=Profiles(self.root)
 def profile(self,game):return self.profiles.folder(self.profiles.create(game=game))
 def test_native_selection_of_all_three_starters_in_both_engines(self):
  for game in ('ruby','sapphire'):
   folder=self.profile(game);template=ROOT/'templates'/game.title()/'ALEX-before-starter-v1'
   for name in ('FireRed.state','FireRed.sav'):shutil.copyfile(template/name,folder/'Data'/name)
   with Game(folder) as g:
    baseline=g.capture_save(metadata=False).state
    for number in starters_for(folder):
     g.restore_checkpoint(baseline);p=Journey(g,Worker());w=SimpleNamespace(player=p,config=SimpleNamespace(species_id=number))
     self.assertEqual(p.state()['player'],'ALEX');self.assertEqual(p.state()['party'],[])
     prepare_choice(w);frontier=g.capture_save(metadata=False).state;seen=set()
     for delay in (17,34,51):
      g.restore_checkpoint(frontier);p.advance(delay);p.tap('A',frames=1,wait=3)
      for _ in range(180):
       mons=p.state()['party']
       if mons and mons[0]['checksum_valid']:break
       p.advance(1)
      else:self.fail('Native starter generation deadline')
      self.assertEqual(mons[0]['species_id'],number);seen.add(mons[0]['uid'])
     self.assertEqual(len(seen),3)
 def test_native_party_pc_roundtrip_and_durable_save(self):
  folder=self.profile('ruby')
  for name in ('FireRed.state','FireRed.sav'):shutil.copyfile(ROOT/'tests/fixtures/hoenn/ruby-ready-v1'/name,folder/'Data'/name)
  with Game(folder) as g:
   p=Journey(g,Worker());before={m['uid']:m for m in p.state()['party']};uids=list(before)
   p.lead(uids[1]);self.assertEqual(p.state()['party'][0]['uid'],uids[1]);p.lead(uids[0])
   pc=Storage(p);pc.deposit(uids[1]);inv=read_inventory(g);self.assertEqual({m['uid'] for m in inv['boxes']},{uids[1]});self.assertEqual(len(inv['party']),1)
   pc.withdraw(uids[1]);after={m['uid']:m for m in p.state()['party']};self.assertEqual(set(before),set(after))
   for uid in before:
    for key in ('species_id','ivs','evs','level','personality','shiny','moves'):self.assertEqual(before[uid][key],after[uid][key])
   p.save_game();g.save()
  with Game(folder) as restored:self.assertEqual(set(before),{m['uid'] for m in read_state(restored)['party']})
 def test_native_move_replacement_and_current_level_evolution_cancel(self):
  from pokemon_red.telemetry import read_decision
  from pokemon_red.learning import LearningRuntime
  from pokemon_red.move_plan import compile_plan
  folder=self.profile('sapphire')
  for name in ('FireRed.state','FireRed.sav'):shutil.copyfile(ROOT/'tests/fixtures/hoenn/sapphire-learning-v1'/name,folder/'Data'/name)
  with Game(folder) as g:
   p=Journey(g,Worker());mon=p.state()['party'][0];choice=dict(read_decision(g),uid=mon['uid'])
   plan=compile_plan(mon,16,[10,52,64,116],folder,mode='stay',pending=choice)
   self.assertTrue(any(d['action']=='cancel' and d['level']==16 for d in plan['decisions']))
   p.learning=LearningRuntime(plan,event=lambda *a:None,checkpoint=lambda _:None,suspend=lambda:None,pending=choice)
   p.battle('fight');after=p.state()['party'][0]
   self.assertEqual(after['species_id'],280);self.assertEqual({m['id'] for m in after['moves']},{10,52,64,116});self.assertEqual(after['uid'],mon['uid'])
 def test_game_specific_encounters_region_and_references(self):
  ruby=self.profile('ruby');sapphire=self.profile('sapphire')
  for root in (ruby,sapphire):
   data=catalog(root);self.assertEqual(len(data['species']),386)
   self.assertEqual(atlas(root)['width'],28);self.assertEqual(destination(root,'OldaleTown')['page'],'hoenn')
   self.assertIn((4,9),destination(root,'OldaleTown')['points'])
   species_id=next(int(n) for n,s in data['species'].items() if s['name']=='ZANGOOSE')
   result=source_data(species_id,root);self.assertFalse(result['needs_national_dex']);self.assertFalse(any('Селадон' in x for x in result['alternatives']))
   from pokemon_red.editions import reference_path
   reference=json.loads(reference_path(root,'location_reference.json').read_text())
   trainers=[t for m in reference['maps'].values() for o in m['objects'] for t in o.get('trainers',[])]
   self.assertGreater(len(trainers),300);self.assertTrue(all(t['party'] for t in trainers))
  zangoose=next(int(n) for n,s in catalog(ruby)['species'].items() if s['name']=='ZANGOOSE')
  self.assertTrue(encounters(zangoose,ruby));self.assertFalse(encounters(zangoose,sapphire))
 def test_shared_services_and_explicit_engine_boundaries(self):
  fr=for_id('firered');rs=for_id('ruby');self.assertEqual(fr.codec,rs.codec);self.assertNotEqual(fr.memory,rs.memory)
  self.assertEqual(fr.services,rs.services)
  with self.assertRaises(ValueError):for_id('diamond')
  with self.assertRaises(ValueError):rs.require('unimplemented')
 def test_shared_trainer_pages_use_the_hoenn_reference_pack(self):
  import tkinter as tk,time,gc
  from pokemon_red.gui import Monitor
  folder=self.profile('ruby')
  for name in ('FireRed.state','FireRed.sav'):shutil.copyfile(ROOT/'tests/fixtures/hoenn/ruby-ready-v1'/name,folder/'Data'/name)
  window=tk.Tk();window.withdraw();monitor=Monitor(window,folder,paused=True);errors=[];window.report_callback_exception=lambda *args:errors.append(str(args[1]))
  def drive(predicate):
   deadline=time.monotonic()+5
   while not predicate() and time.monotonic()<deadline:window.update();time.sleep(.005)
   self.assertTrue(predicate());self.assertEqual(errors,[])
  try:
   drive(lambda:monitor.ready);monitor.show_panel('collection');window.update();self.assertEqual(monitor.panel.active_section,'collection')
   monitor.panel.show('location');window.update();self.assertEqual(monitor.panel.active_section,'location')
   monitor.panel.open_pokemon(species_id=277);window.update();self.assertTrue(monitor.panel.details.active)
  finally:
   monitor.close();drive(lambda:monitor.closed)
   try:window.destroy()
   except tk.TclError:pass
   del monitor,window;gc.collect()
 def test_badges_and_cut_objects_are_region_specific(self):
  mon=dict(uid='tool',moves=[dict(id=15)],checksum_valid=True,is_egg=False)
  self.assertTrue(available([mon],[1],'ruby')['cut']['unlocked']);self.assertFalse(available([mon],[1],'firered')['cut']['unlocked'])
  grid=dict(cut_badge=1,cut_graphics=82,field_badges=[1],objects=[dict(x=2,y=2,graphics_id=82)],obstacles=[[2,2],[3,3]])
  self.assertEqual(party_cut(grid,[mon])['obstacles'],[[3,3]])
 def test_story_rejection_precedes_any_trade_input(self):
  a=SimpleNamespace();b=SimpleNamespace()
  with patch('pokemon_red.trade.preflight',return_value=['Сначала завершите задание Селио']):
   with self.assertRaisesRegex(AcquisitionAttention,'Селио'):perform_trade(a,b,'a','b',Worker())
 def test_capture_kit_is_defined_by_moves_instead_of_venusaur_species(self):
  hunter=dict(species_id=306,moves=[dict(id=147,current_pp=15),dict(id=73,current_pp=10)])
  self.assertTrue(capture_kit(hunter))
  enemy=dict(hp=100,max_hp=100,level=30,status_code=0,ability_id=0)
  choice=VenusaurPolicy().decide(enemy,hunter,{4:10},3)
  self.assertEqual(choice['move_id'],147)

if __name__=='__main__':unittest.main()
