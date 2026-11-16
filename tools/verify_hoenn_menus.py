"""Native button-only menu smoke test, restricted to an explicit private root."""
from pathlib import Path
import sys,json
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from pokemon_red.engine import Game
from pokemon_red.journey import Journey
from pokemon_red.storage import Storage
from pokemon_red.telemetry import read_state

class Worker:
    def heartbeat(self):pass
    def safe_point(self):pass
    def event(self,*args,**kw):print('event',args,kw,flush=True)
    def update(self,**kw):pass

root=Path(sys.argv[1]).resolve()
if not (root/'fixture-only').exists():raise SystemExit('Private fixture marker required')
with Game(root) as game:
    p=Journey(game,Worker())
    try:
        for _ in range(20):
            s=p.state()
            if s['controls']['callback']=='CB2_Overworld' and not s['controls']['field_locked']:break
            p.tap('B',wait=30)
        if len(p.state()['party'])<2:
            Storage(p).withdraw(p.bot.inventory()['boxes'][0]['uid'])
        original=[m['uid'] for m in p.state()['party']]
        p.lead(original[1]);assert p.state()['party'][0]['uid']==original[1]
        p.lead(original[0]);assert p.state()['party'][0]['uid']==original[0]
        print('LEAD ROUNDTRIP OK',flush=True)
        if 'storage' in sys.argv:
            storage=Storage(p);storage.deposit(original[1]);assert original[1] not in {m['uid'] for m in p.state()['party']}
            storage.withdraw(original[1]);assert [m['uid'] for m in p.state()['party']]==original
            print('PC ROUNDTRIP OK',flush=True)
        p.save_game()
    finally:
        game.save()
        (root/'menu-proof.json').write_text(json.dumps(read_state(game),ensure_ascii=False,indent=2))
