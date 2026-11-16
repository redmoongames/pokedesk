"""Exercise real owner, bot transport and training on a fresh private fixture."""
from pathlib import Path
import sys,json,time,shutil
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.engine_runtime import EngineRuntime
from pokemon_red.telemetry import read_state
from verify_hoenn_link import clone

class ProbeRuntime(EngineRuntime):
 def _dispatch(self,c,method,args):
  if method=='probe':return args[0](c)
  return super()._dispatch(c,method,args)

root=Path(sys.argv[1]).resolve()
clone(Path(sys.argv[2]).resolve() if len(sys.argv)>2 else ROOT/'tests/fixtures/hoenn/ruby-ready-v1',root,'ruby')
(root/'Data/settings.json').write_text(json.dumps(dict(speed=16,sound_enabled=False,autosave_enabled=False,panel_on_start=False)))
runtime=ProbeRuntime(root,paused=True)
try:
 runtime.ready.result(10);before=runtime.submit('probe',lambda c:read_state(c.game)).result(5);mon=before['party'][0]
 config=dict(auto_team=True,trainee=mon['uid'],target=mon['level']+1,route='Route101',strategy='adaptive',fighters=[],heal_percent=40,allow_two_hits=True,auto_speed=True,max_auto_speed=16)
 (root/'Data/training.json').write_text(json.dumps(config));runtime.submit('start_bot',root/'Bots/train_xp.py').result(5);deadline=time.monotonic()+100
 while time.monotonic()<deadline:
  state=runtime.latest;info=state.status['automation']
  if info.get('status') in ('attention','error','finished'):
   after=runtime.submit('probe',lambda c:read_state(c.game)).result(5);print(info,flush=True)
   if next(m for m in after['party'] if m['uid']==mon['uid'])['level']<config['target']:raise RuntimeError(info)
   (root/'proof.json').write_text(json.dumps(dict(before=before,after=after,automation=info),ensure_ascii=False,indent=2));print('PASS',flush=True);break
  time.sleep(.03)
 else:raise TimeoutError(runtime.latest.status['automation'])
finally:
 runtime.take_control(close=True);runtime.finished.result(15);runtime.thread.join(2)
