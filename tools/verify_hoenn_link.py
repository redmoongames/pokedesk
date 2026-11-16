"""Real SIO verification on marked, disposable fixtures, never live profiles.

The Kanto fixture alone receives the documented story-unlock flags. Pokémon
records are not edited. Production preflight still requires actual progression.
"""
from pathlib import Path
import sys,json,shutil,time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.engine import Game
from pokemon_red.telemetry import read_state,symbols
from pokemon_red.trade import perform_trade
from pokemon_red.game_layout import save_block,flags_offset
from pokemon_red.save_metadata import png

class Worker:
    def heartbeat(self):pass
    def safe_point(self):pass
    def update(self,**kw):print(kw,flush=True)
    def event(self,*args):pass

def clone(source,target,game,*,cold=False):
    (target/'Data').mkdir(parents=True)
    (target/'fixture-only').touch()
    for name in ('src','native','vendor','assets','runtime','Bots'):(target/name).symlink_to(ROOT/name)
    rom=ROOT/'Data/FireRed.gba' if game=='firered' else ROOT/'ROMs'/dict(leafgreen='LeafGreen-Rev1.gba',ruby='Ruby-Rev2.gba',sapphire='Sapphire-Rev2.gba')[game]
    (target/'Data/FireRed.gba').symlink_to(rom)
    (target/'Data/game.json').write_text(json.dumps(dict(game=game)))
    for name in ('FireRed.sav','FireRed.state'):
        if cold and name.endswith('.state'):continue
        shutil.copyfile(source/name,target/'Data'/name)

def fixture_story_flags(game):
    if not (game.root/'fixture-only').exists():raise RuntimeError('Fixture only')
    ram=game.read_bytes(0x02000000,0x40000);snapshot=game.capture_save(metadata=False).state
    offset=snapshot.find(ram)
    if offset<0 or snapshot.find(ram,offset+1)>=0:raise RuntimeError('Unknown serialized RAM layout')
    data=bytearray(snapshot);base=offset+save_block(game,1)-0x02000000+flags_offset(game)
    for flag in (0x840,0x844):data[base+flag//8]|=1<<(flag%8)
    data[offset+save_block(game,2)-0x02000000+0x1b]=0xb9
    varbase=offset+save_block(game,1)-0x02000000+0x1000
    data[varbase+0x4e*2:varbase+0x4e*2+2]=(0x6258).to_bytes(2,'little')
    game.restore_checkpoint(bytes(data))
    # National Dex also has a magic value/var; use only Kanto Pokémon for
    # fixture exchanges so no species/Dex restriction is bypassed here.

def boot(game):
    for _ in range(100):
        game.advance(300);s=read_state(game);cb=s.get('controls',{}).get('callback','')
        quest=game.read8(symbols(game.root)['gQuestLogState']) if 'gQuestLogState' in symbols(game.root) else 0
        if s['ready'] and cb=='CB2_Overworld' and not s['controls']['field_locked'] and not quest:return
        game.press('B' if quest else 'START' if 'Title' in cb or 'Intro' in cb else 'A',frames=2,release_frames=120)
    raise RuntimeError('Cold boot deadline')

if __name__=='__main__':
    target=Path(sys.argv[1]).resolve();hoenn=sys.argv[2];kanto=sys.argv[3]
    a=target/'a';b=target/'b'
    if not a.exists():
        clone(Path(sys.argv[4]).resolve(),a,kanto,cold=kanto=='leafgreen')
        clone(Path(sys.argv[5]).resolve(),b,hoenn,cold=hoenn=='sapphire')
    began=time.monotonic()
    with Game(a) as x,Game(b) as y:
        if kanto=='leafgreen':boot(x)
        if hoenn=='sapphire':boot(y)
        fixture_story_flags(x)
        initial=[read_state(g) for g in (x,y)]
        # Wurmple needs the National Dex in FRLG. The proof deliberately uses
        # a real starter and verifies the game's own permission responses.
        uids=[initial[0]['party'][0]['uid'],initial[1]['party'][1]['uid']]
        print('BEFORE',[(s['map'],[(m['uid'],m['species']) for m in s['party']]) for s in initial],flush=True)
        try:
            received=perform_trade(x,y,*uids,Worker())
            first=[read_state(g) for g in (x,y)]
            returned=perform_trade(x,y,uids[1],uids[0],Worker())
            after=[read_state(g) for g in (x,y)]
            assert all({m['uid'] for m in initial[i]['party']}=={m['uid'] for m in after[i]['party']} for i in range(2))
            (target/'proof.json').write_text(json.dumps(dict(games=[kanto,hoenn],seconds=time.monotonic()-began,fixture_story_flags=True,before=initial,first=first,after=after,received=received,returned=returned),ensure_ascii=False,indent=2))
            print('PASS',time.monotonic()-began,flush=True)
        finally:
            for i,g in enumerate((x,y)):
                g.save();(target/f'after-{i}.png').write_bytes(png(g.rgb()))
                (target/f'debug-{i}.json').write_text(json.dumps(dict(state=read_state(g),text=__import__('pokemon_red.acquisition_play',fromlist=['Player']).Player(g,Worker()).text()),ensure_ascii=False,indent=2))
