"""Build an ALEX prologue fixture through ordinary input on a fresh private core."""
from pathlib import Path
import sys,json
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.engine import Game
from pokemon_red.journey import Journey
from pokemon_red.acquisition_play import AcquisitionAttention
from pokemon_red.telemetry import read_controls
from pokemon_red.save_metadata import png

class Worker:
 def heartbeat(self):pass
 def safe_point(self):pass
 def event(self,*a,**k):pass
 def update(self,**k):pass

root=Path(sys.argv[1]).resolve();game=sys.argv[2]
if root.exists() or root==ROOT or game not in ('ruby','sapphire'):raise SystemExit('Fresh private root required')
(root/'Data').mkdir(parents=True);(root/'fixture-only').touch()
(root/'Data/game.json').write_text(json.dumps(dict(game=game)))
(root/'Data/FireRed.gba').symlink_to(ROOT/'ROMs'/('Ruby-Rev2.gba' if game=='ruby' else 'Sapphire-Rev2.gba'))
for n in ('src','native','vendor','assets','runtime','Bots'):(root/n).symlink_to(ROOT/n)
with Game(root) as g:
 p=Journey(g,Worker())
 try:
  g.advance(600);g.press('START',frames=2,release_frames=600);g.press('START',frames=2,release_frames=600)
  for _ in range(100):
   if 'Task_NamingScreenMain' in p.tasks():g.advance(120);break
   g.press('A',frames=8,release_frames=180)
  else:raise RuntimeError('Naming screen not reached')
  keys=['A','DOWN',*['RIGHT']*5,'A','UP','LEFT','A',*['DOWN']*3,'A','START','A']
  for key in keys:p.tap(key,frames=8,wait=30)
  for _ in range(120):
   s=p.state()
   if s.get('map',{}).get('name')=='InsideOfTruck' and s.get('controls',{}).get('callback')=='CB2_Overworld' and not s['controls']['field_locked']:break
   g.press('A',frames=8,release_frames=180)
  if p.state()['player']!='ALEX':raise RuntimeError('Wrong trainer name')
  p.transition('RIGHT','LittlerootTown');p.settle(button='A')
  p.go((8,3));p.transition('UP','LittlerootTown_BrendansHouse_2F');p.settle(button='A')
  p.go((5,2));p.tap('UP',frames=16);p.tap('A',wait=180)
  for _ in range(20):
   if read_controls(g)['callback']=='WallClockMainCallback':break
   p.tap('A',wait=120)
  p.advance(120);p.tap('A',wait=180);p.tap('UP',frames=8,wait=30);p.tap('A',wait=180);p.settle(button='A')
  p.go((7,2));p.transition('UP','LittlerootTown_BrendansHouse_1F');p.settle(button='A')
  p.go((8,7));p.transition('DOWN','LittlerootTown')
  p.go((14,10));p.transition('UP','LittlerootTown_MaysHouse_1F');p.settle(button='A')
  p.go((2,3));p.transition('UP','LittlerootTown_MaysHouse_2F');p.go((8,2));p.tap('LEFT',frames=16);p.tap('A');p.settle(button='A')
  p.go((1,2));p.transition('UP','LittlerootTown_MaysHouse_1F');p.go((2,7));p.transition('DOWN','LittlerootTown')
  p.go((11,1),allow_trigger=True);p.settle(button='A');p.transition('UP','Route101');p.settle(button='A');p.go((7,15))
  assert p.state()['player']=='ALEX' and not p.state()['party'] and not p.state()['controls']['field_locked']
  print('ALEX before starter',p.state()['map'],p.state()['position'],flush=True)
 finally:
  g.save();(root/'screen.png').write_bytes(png(g.rgb()))
  (root/'state.json').write_text(json.dumps(p.state(),ensure_ascii=False,indent=2))
