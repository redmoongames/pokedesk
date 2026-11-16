from pathlib import Path
import sys,json
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.engine import Game
from pokemon_red.telemetry import read_state,read_controls,symbols,decode_text
from pokemon_red.save_metadata import png
folder=Path(sys.argv[1]);folder.mkdir(exist_ok=True);(folder/'Data').mkdir(exist_ok=True)
if not (folder/'Data/game.json').exists():
 (folder/'Data/game.json').write_text('{"game":"ruby"}');(folder/'Data/FireRed.gba').symlink_to(ROOT/'ROMs/Ruby-Rev2.gba')
 for key in ('native','vendor','assets','src','Bots','runtime'):(folder/key).symlink_to(ROOT/key,target_is_directory=True)
with Game(folder) as game:
 for arg in sys.argv[2:]:
  key,_,n=arg.partition(':');n=int(n or 1)
  if key=='wait':game.advance(n)
  else:game.press(key,frames=n);game.advance(20)
 game.save();(folder/'screen.png').write_bytes(png(game.rgb()));state=read_state(game);print(json.dumps(dict(frame=game.frame,state=state,controls=read_controls(game),text=decode_text(game.read_bytes(symbols(folder)['gStringVar4'],700))),ensure_ascii=False))
