"""A compact setup uses semantic preferences, not two conflicting IV editors."""
import sys,gc,unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock,patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))

class TimedCatchUI(unittest.TestCase):
 def setUp(self):
  import tkinter as tk
  from pokemon_red.catch_view import CatchSetup
  gc.collect();self.window=tk.Tk();self.window.geometry('320x760');self.errors=[];self.window.report_callback_exception=lambda k,e,t:self.errors.append(e)
  self.op=NS(active=False,kind=None,result=None,data={},command=Mock(),begin=Mock())
  self.m=NS(folder=ROOT,generation=1,last_state=dict(ready=True,in_battle=False,controls={'callback':'CB2_Overworld'}),operation=self.op,automation=NS(running=False),status={},runtime=NS(submit=Mock()),watch=Mock(),notice='')
  self.patch=patch('pokemon_red.catch_view.HuntService');factory=self.patch.start();self.service=factory.return_value;self.service.poll.return_value=None
  self.view=CatchSetup(NS(monitor=self.m,window=self.window,content=self.window),19,parent=self.window);self.window.update()
 def tearDown(self):
  self.view.close();self.window.destroy();self.patch.stop();gc.collect();self.assertEqual(self.errors,[])
 def test_default_is_one_minute_with_no_hidden_iv_thresholds(self):
  target=self.view.target();self.assertEqual(target.search_seconds,60);self.assertFalse(target.exact_ivs);self.assertEqual(target.required_ivs,(0,)*6)
  self.assertEqual(len(target.natures),25);self.assertFalse(self.view.iv_host.winfo_manager())
 def test_role_controls_drive_both_weight_and_nature_without_replanning(self):
  calls=self.m.runtime.submit.call_count;self.view.stat_editor.controls['attack'].choose('positive');self.view.stat_editor.controls['hp'].choose('positive');self.view.stat_editor.controls['speed'].choose('negative')
  target=self.view.target();self.assertEqual(target.priority_ivs,('hp','attack'));self.assertEqual(target.natures,(2,));self.assertTrue(self.view.form_dirty);self.assertEqual(self.m.runtime.submit.call_count,calls)
 def test_minimums_are_a_separate_opt_in_and_stars_are_hidden(self):
  self.view.ivs['hp'].set(31);self.assertEqual(self.view.target().required_ivs,(0,)*6)
  self.view.exact_ivs.set(True);self.view.exact_iv_changed();self.window.update();self.assertTrue(self.view.iv_host.winfo_manager());self.assertEqual(self.view.target().required_ivs[0],31)
  self.assertTrue(all(not b.winfo_manager() for b in self.view.iv_editor.buttons.values()))
  self.view.exact_ivs.set(False);self.view.exact_iv_changed();self.assertEqual(self.view.target().required_ivs,(0,)*6)
 def test_time_presets_and_custom_seconds(self):
  control=self.view.time_control;value=next(v for v in control.picker.values if v.identifier==120);control.picker.choose(value);self.assertEqual(self.view.target().search_seconds,120)
  control.picker.choose(control.custom_option);self.window.update();self.assertTrue(control.custom.winfo_manager());self.view.search_seconds.set(11);self.assertEqual(self.view.target().search_seconds,11)
 def test_narrow_window_keeps_primary_action_visible_and_rows_inside(self):
  self.window.geometry('300x600');self.window.update()
  self.assertLessEqual(self.view.start.winfo_rooty()+self.view.start.winfo_height(),self.window.winfo_rooty()+600)
  for control in self.view.stat_editor.controls.values():
   self.assertLessEqual(control.winfo_rootx()+control.winfo_width(),self.window.winfo_rootx()+300)
