from pathlib import Path
import sys,json
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from pokemon_red.engine import Game
from pokemon_red.acquisition_play import Player
from pokemon_red.journey import Journey
from pokemon_red.telemetry import read_state,read_controls
from pokemon_red.save_metadata import png
class Worker:
 def heartbeat(self):pass
 def safe_point(self):pass
 def event(self,*args,**kwargs):pass
 def update(self,**kwargs):pass
f=Path(sys.argv[1])
with Game(f) as g:
 p=Player(g,Worker())
 try:
  for arg in sys.argv[2:]:
   if arg.startswith('nav:'):
    p=Journey(g,Worker());p.nav.travel(arg[4:])
   elif arg.startswith('go:'):p.go(tuple(map(int,arg[3:].split(','))),allow_trigger=True)
   elif arg.startswith('trans:'):
    key,dest=arg[6:].split(',',1);p.transition(key,dest)
   elif arg.startswith('battle:'):p.battle(arg[7:])
   elif arg=='heal':p.heal()
   elif arg=='save':p.save_game()
   elif arg=='settle':p.settle(button='A')
   else:
    key,_,n=arg.partition(':');g.press(key,int(n or 8));g.advance(30)
 finally:
  g.save();(f/'screen.png').write_bytes(png(g.rgb()));s=read_state(g);print(s['map'],s['position'],read_controls(g)['callback']);print(p.text())
