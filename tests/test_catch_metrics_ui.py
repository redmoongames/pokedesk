"""Live progress updates must not accumulate pointer/key event bindings."""
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import Mock,patch
import gc,sys,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
class MetricsBindings(unittest.TestCase):
 def test_repeated_search_metrics_reuse_the_existing_tooltip(self):
  import tkinter as tk
  from pokemon_red.catch_view import CatchSetup
  gc.collect();window=tk.Tk();window.geometry('350x800')
  m=N(folder=ROOT,generation=1,last_state=dict(ready=True,in_battle=False,controls=dict(callback='CB2_Overworld',field_locked=False,moving=False)),operation=N(active=True,kind='local',data=dict(progress=dict(search=dict(attempts=10,rate=3.,workers=6,transport='bike',lanes=[dict(lane=1,pid=123,attempts=10,cpu_seconds=.1)]))),result=None),automation=N(running=False),notice='',runtime=N(submit=Mock()),watch=Mock())
  p=N(window=window,monitor=m,content=window);view=None
  try:
   with patch('pokemon_red.catch_view.HuntService') as service:
    service.return_value.poll.return_value=None
    view=CatchSetup(p,43,parent=window);window.update();initial=view.metrics.bind('<Enter>');hint=view.metrics_hint
    for _ in range(100):view.update_actions()
    self.assertEqual(view.metrics.bind('<Enter>'),initial);self.assertIs(view.metrics_hint,hint);self.assertIn('123',hint.text)
  finally:
   if view:view.close()
   window.destroy();gc.collect()
