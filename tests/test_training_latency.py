"""Regressions for UI stalls, fractional forecasts and cancellable launch writes."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
import json,sys,threading,time,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.i18n import render,_fragment_pattern
from pokemon_red.training_view import TrainingSetup
from pokemon_red.optimizer import forecast_cycle
from pokemon_red.planning import make_plan
from test_grind import mon
from test_runtime_performance import PrivateSessionTestCase
from test_engine_runtime import ProbeRuntime

class ForecastInputTests(unittest.TestCase):
 def test_fractional_expectations_never_reach_live_battle_policy(self):
  from pokemon_red.training_tactics import choose
  team=[mon(19,10,'t',[33,98]),mon(25,20,'m',[84])];config=dict(route='Route1',trainee='t',target=12,training_approach='careful',training_policy='eta',heal_percent=40,strategy='adaptive')
  plan=make_plan(dict(ready=True,party=team,boxes=[]),config,ROOT);plan['tactic']='careful';samples=[]
  def checked(state,*args,**kw):
   samples.extend(a['current_pp'] for m in state['party'] for a in m['moves'])
   self.assertTrue(all(type(a['current_pp']) is int and a['current_pp']>=0 for m in state['party'] for a in m['moves']))
   return choose(state,*args,**kw)
  geometry=dict(farm=dict(hub='Viridian',pair=[[12,6],[13,6]],cost=[0,40]),travel_seconds=20,preparation_seconds=0,preparation_steps=0)
  with patch('pokemon_red.training_tactics.choose',side_effect=checked):result=forecast_cycle(plan,config,ROOT,geometry,dict(cycles=[],battles=[]))
  self.assertGreater(result['battles'],1);self.assertGreater(result['xp_game_minute'],0);self.assertTrue(samples)

class PreparedRevisionTests(unittest.TestCase):
 def test_bot_inventory_uses_the_same_revision_provider_as_preview_maps(self):
  from pokemon_red.session_controller import SessionController
  core=object.__new__(SessionController);core.game=SimpleNamespace(state_generation=3);core.automation=SimpleNamespace(running=True);core.transport=SimpleNamespace(navigation_version=Mock(return_value='7:flags-hash'));core.history=Mock()
  with patch('pokemon_red.models.read_inventory',return_value=dict(ready=True,party=[],boxes=[])),patch('pokemon_red.telemetry.read_field_badges',return_value=[1]),patch('pokemon_red.player_inventory.read_player_inventory',return_value=dict(items=[])):
   inventory=core.inventory_snapshot()
  self.assertEqual(inventory['navigation_revision'],'7:flags-hash');core.transport.navigation_version.assert_called_once_with(core)

class CaptionLatencyTests(unittest.TestCase):
 def test_long_route_exclusions_do_not_block_the_ui(self):
  text=(ROOT/'tests/fixtures/training-exclusions.txt').read_text()
  for language in ('en','ru'):
   render('Отряд',locale=language);start=time.perf_counter();value=render(text,locale=language)
   self.assertLess(time.perf_counter()-start,.5);self.assertEqual(value.count('\n'),text.count('\n'))
 def test_fragment_prefixes_keep_longest_match_and_word_boundaries(self):
  import re
  sources=['Отряд и PC','Отряд','XP/мин','XP',' · ','C++','HP','!'];old=re.compile('|'.join((r'(?<!\w)' if s[0].isalnum() else '')+re.escape(s)+(r'(?!\w)' if s[-1].isalnum() else '') for s in sorted(sources,key=len,reverse=True)));new=_fragment_pattern(sorted(sources,key=len,reverse=True))
  for text in ['Отряд и PC · XP/мин','HP HPP AHP XP/мин XP!','C++ C+++ · !','Отрядный Отряд\nОтряд и PC']:
   self.assertEqual([(m.span(),m.group()) for m in new.finditer(text)],[(m.span(),m.group()) for m in old.finditer(text)])

class TrainingEditTests(unittest.TestCase):
 def setUp(self):
  import tkinter as tk
  self.root=tk.Tk();self.root.withdraw();self.setup=object.__new__(TrainingSetup);s=self.setup;s.closed=False;s.header=self.root;s.start=Mock();s.refresh=Mock();s.monitor=SimpleNamespace(last_state={'ready':True});s.change_after=None;s.signature='old';s.preview_origin={}
 def tearDown(self):
  if self.setup.change_after:self.root.after_cancel(self.setup.change_after)
  self.root.destroy()
 def test_burst_updates_only_latest_target_and_immediately_revokes_start(self):
  for _ in range(30):self.setup.changed()
  self.assertIsNone(self.setup.signature);self.setup.start.configure.assert_called_with(state='disabled');self.setup.refresh.assert_not_called()
  deadline=time.monotonic()+1
  while not self.setup.refresh.called and time.monotonic()<deadline:self.root.update();time.sleep(.002)
  self.setup.refresh.assert_called_once_with(self.setup.monitor.last_state);self.assertIsNone(self.setup.change_after)
 def test_destroyed_setup_cannot_schedule_a_new_refresh(self):
  self.setup.closed=True;self.setup.changed();self.assertIsNone(self.setup.change_after)

class SupersededMapTests(unittest.TestCase):
 def test_old_map_request_is_cancelled_without_fetching_more_maps(self):
  from concurrent.futures import Future
  from pokemon_red.planning_service import PlanningService
  pending=Future();service=PlanningService(map_provider=Mock(return_value=pending));process=object();service.process=process;service.active=('old',None);service.desired='old';service._send=Mock();service._start=Mock()
  service.responses.put((process,json.dumps(dict(type='map_request',name='Route1'))));service.poll();self.assertIsNotNone(service.map_pending)
  service.desired='new';service.poll();self.assertTrue(pending.cancelled());service._send.assert_called_with(dict(name='Route1',cancelled=True))
  service.responses.put((process,json.dumps(dict(type='cancelled'))));service.poll();self.assertIsNone(service.active);self.assertNotIn('old',service.cache);service._start.assert_called_once()
 def test_stale_map_is_never_submitted_to_the_core(self):
  from pokemon_red.planning_service import PlanningService
  service=PlanningService(map_provider=Mock());process=object();service.process=process;service.active=('old',None);service.desired='new';service._send=Mock();service.responses.put((process,json.dumps(dict(type='map_request',name='Route1'))));service.poll()
  service.map_provider.assert_not_called();service._send.assert_called_with(dict(name='Route1',cancelled=True))

class TrainingLaunchTests(PrivateSessionTestCase):
 def setUp(self):
  super().setUp();self.runtime=ProbeRuntime(self.root,paused=True);self.runtime.ready.result(8)
 def tearDown(self):
  self.runtime.take_control(close=True);self.runtime.finished.result(10);super().tearDown()
 def wait(self,predicate):
  end=time.monotonic()+5
  while not predicate() and time.monotonic()<end:time.sleep(.002)
  self.assertTrue(predicate())
 def check_write_barrier(self,cancel):
  gate=threading.Event();entered=threading.Event();calls=[]
  self.runtime.submit('probe',lambda c:(setattr(c,'start_bot',lambda path:calls.append((threading.get_ident(),json.loads((self.root/'Data/training.json').read_text())))),c.writer.submit(lambda:(entered.set(),gate.wait(5))),None)[-1]).result(5)
  self.assertTrue(entered.wait(2));cfg=dict(trainee='test',target=12,route='Route1')
  try:
   with patch('pokemon_red.grind.validate_start'):
    started=time.perf_counter();self.runtime.submit('start_training',cfg).result(2);self.assertLess(time.perf_counter()-started,.2)
   self.assertFalse(calls);self.assertFalse((self.root/'Data/training.json').exists())
   if cancel:
    epoch=self.runtime.take_control(pause=True);self.wait(lambda:self.runtime.latest.epoch>=epoch)
   gate.set();self.wait(lambda:(self.root/'Data/training.json').exists());self.wait(lambda:not self.runtime.latest.status['saving'])
   if cancel:self.assertFalse(calls)
   else:self.assertEqual(calls,[(self.runtime.thread.ident,cfg)])
  finally:gate.set()
 def test_start_waits_for_durable_config_without_blocking_owner(self):self.check_write_barrier(False)
 def test_f9_during_write_prevents_late_start(self):self.check_write_barrier(True)

if __name__=='__main__':unittest.main()
