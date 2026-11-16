"""Prepare verified donors by ordinary Give/Take and real link trades only."""
from pathlib import Path
import sys,time,json,hashlib,argparse
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--item',type=int,choices=(4,332),required=True)
parser.add_argument('--workdir',type=Path,required=True,help='New directory for private cores')
parser.add_argument('--output',type=Path,help='New directory for the verified template')
args=parser.parse_args()
ROOT=Path(__file__).resolve().parents[1];BASE=args.workdir.resolve();BASE.mkdir(parents=True,exist_ok=False)
sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.engine import Game
from pokemon_red.acquisition_play import Player
from pokemon_red.operations import clone_session
from pokemon_red.persistence import SaveSnapshot
from pokemon_red.item_delivery_worker import open_party,take_item
from pokemon_red.item_delivery import DONOR_UID,quantity,PRODUCTS
from pokemon_red.player_inventory import read_player_inventory
from pokemon_red.telemetry import symbols,read_state
from pokemon_red.trade import perform_trade
from pokemon_red.acquisition import write_json

class Observer:
    def heartbeat(self):pass
    def safe_point(self):pass
    def update(self,**kw):print(kw,flush=True)
    def event(self,code,details):pass

def clone(name,source):
    folder=BASE/name
    return clone_session(ROOT,folder,SaveSnapshot((source/'FireRed.state').read_bytes(),(source/'FireRed.sav').read_bytes(),0,time.time()))

def give(p,uid,item):
    before=quantity(read_player_inventory(p.g),item)
    assert before>0
    mon=next(m for m in p.state()['party'] if m['uid']==uid);assert not mon['held_item']
    open_party(p)
    target=mon['slot']-1
    for _ in range(40):
        c=p.state()['controls']
        if 'Task_HandleChooseMonInput' not in p.tasks():p.advance(12);continue
        here=c['party_cursor']
        if here==target:p.tap('A',wait=90);break
        p.tap('RIGHT' if here==0 else 'LEFT' if target==0 else 'DOWN' if here<target else 'UP',wait=30)
    else:raise RuntimeError('Party cursor failed')
    for _ in range(15):
        c=p.state()['controls'];target=c['party_actions'].index(3)
        if c['menu_cursor']==target:p.tap('A',wait=60);break
        p.tap('DOWN' if c['menu_cursor']<target else 'UP',wait=30)
    assert p.state()['controls']['party_actions']==[4,5,9]
    assert p.state()['controls']['menu_cursor']==0
    p.tap('A',wait=180)
    # In Give mode the TM Case is opened through the key-items pocket.
    desired=364 if item==332 else item
    pocket=1 if item==332 else 2 if item==4 else 0
    sy=symbols(p.g.root);bag=sy['gBagMenuState']
    for _ in range(100):
        tasks=p.tasks();c=p.state()['controls']
        if 'Task_BagMenu_HandleInput' not in tasks:p.advance(12);continue
        current=p.g.read16(bag+6)
        if current!=pocket:p.tap('RIGHT' if current<pocket else 'LEFT',wait=48);continue
        rows=[r for r in read_player_inventory(p.g)['items'] if r['pocket']==('key' if pocket==1 else 'balls' if pocket==2 else 'items')]
        target=next(r['slot'] for r in rows if r['id']==desired)
        cursor=p.g.read16(bag+8+2*pocket)+p.g.read16(bag+14+2*pocket)
        if cursor==target:p.tap('A',wait=200);break
        p.tap('DOWN' if cursor<target else 'UP',wait=30)
    else:raise RuntimeError('Bag cursor failed: '+repr(c))
    if item==332:
        static=sy['sTMCaseStaticResources']
        for _ in range(100):
            if 'Task_HandleListInput' not in p.tasks():p.advance(12);continue
            rows=[r for r in read_player_inventory(p.g)['items'] if r['pocket']=='tmhm']
            target=next(r['slot'] for r in rows if r['id']==item)
            cursor=p.g.read16(static+8)+p.g.read16(static+10)
            if cursor==target:p.tap('A',wait=200);break
            p.tap('DOWN' if cursor<target else 'UP',wait=30)
        else:raise RuntimeError('TM cursor failed')
    for _ in range(80):
        m=next(m for m in p.state()['party'] if m['uid']==uid)
        if m['held_item']==item:break
        p.tap('A',wait=30)
    else:raise RuntimeError('Give failed: '+p.text()+' '+repr(p.state()['controls']))
    p.settle(button='B')
    assert quantity(read_player_inventory(p.g),item)==before-1
    p.save_game()

def export(game,item,origin):
    out=args.output.resolve() if args.output else ROOT/PRODUCTS[item]['template'];out.mkdir(parents=True)
    game.save_to(out)
    meta=dict(schema_version=1,item_id=item,state=read_state(game),created_at=time.time(),
              origin=origin,method='ordinary Give/Take menus and native link trades; no memory writes')
    write_json(out/'metadata.json',meta)
    write_json(out/'manifest.json',{n:hashlib.sha256((out/n).read_bytes()).hexdigest() for n in ('FireRed.state','FireRed.sav','metadata.json')})
    print('EXPORTED',item,out,flush=True)

item=args.item
target=args.output.resolve() if args.output else ROOT/PRODUCTS[item]['template']
if target.exists():raise FileExistsError('Output already exists: '+str(target))
observer=Observer();origin=ROOT/'templates/items/antidote-v1/ready'
main_folder=clone('prepare-'+str(item),origin)
with Game(main_folder) as main:
    p=Player(main,observer);take_item(p,DONOR_UID)
    if item==332:
        progressed=ROOT/'templates/FireRed/Progressed-hunting-v1'
        donor_folder=clone('tm44-source',progressed)
        with Game(donor_folder) as donor:
            d=Player(donor,observer);carrier='ee83a314:728cbb7c';give(d,carrier,332)
            perform_trade(main,donor,DONOR_UID,carrier,observer)
            take_item(p,carrier,332)
            perform_trade(main,donor,carrier,DONOR_UID,observer)
    give(p,DONOR_UID,item)
    export(main,item,dict(template=str(origin.relative_to(ROOT)),origin_sha256=hashlib.sha256((origin/'FireRed.state').read_bytes()).hexdigest(),tm44_source='templates/FireRed/Progressed-hunting-v1' if item==332 else None))
