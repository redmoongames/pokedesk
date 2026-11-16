"""Publish a protected starter checkpoint from an independently played prologue."""
from pathlib import Path
import sys,time,hashlib,os,json
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.engine import Game
from pokemon_red.telemetry import read_state
from pokemon_red.acquisition import write_json,TEMPLATE,template_for
from pokemon_red.editions import edition
from pokemon_red.persistence import sync_directory

source=Path(sys.argv[1]).resolve()
if source==ROOT or (source/'Data').resolve()==(ROOT/'Data').resolve():raise SystemExit('Independent fixture required')
with Game(source) as g:
 s=read_state(g);c=s.get('controls',{})
 if s.get('player')!='ALEX' or s.get('party') or s.get('map',{}).get('name')!='Route101' or s.get('position',{}).get('x')!=7 or s['position']['y']!=15 or c.get('callback')!='CB2_Overworld' or c.get('field_locked'):raise RuntimeError('Unverified starter position')
 folder=ROOT/template_for(source,TEMPLATE)
 if folder.exists():raise RuntimeError('Template already exists')
 folder.parent.mkdir(parents=True,exist_ok=True);pending=folder.with_name('.'+folder.name+'-pending');g.save_to(pending)
 write_json(pending/'metadata.json',dict(template_id='alex-before-starter-v1',game=edition(source).id,rom_sha1=g.rom_sha1,created_at=time.time(),state=s,description='ALEX, Route 101, before selecting Treecko/Torchic/Mudkip. Built through game input; no Pokémon or RNG editing. Exact checkpoint is authoritative before the game permits SAVE.'))
 (pending/'README.txt').write_text('Защищённый шаблон ALEX перед выбором стартового Pokémon в Хоэнне.\nДля нового задания копировать оба файла в отдельный Data.\nТочный checkpoint важен: до получения первого Pokémon игра ещё не разрешает обычный SAVE.\n')
 write_json(pending/'manifest.json',dict(algorithm='sha256',files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in pending.iterdir()}))
 for p in pending.iterdir():p.chmod(0o444)
 pending.chmod(0o555);os.rename(pending,folder);sync_directory(folder.parent);print(folder)
