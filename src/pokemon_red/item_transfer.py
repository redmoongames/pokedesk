"""Give an ordinary transferable item using the game's party/bag menus."""
from .acquisition_play import AcquisitionAttention
from .item_delivery_worker import open_party
from .item_delivery import quantity,product
from .player_inventory import read_player_inventory
from .telemetry import symbols

def give_item(p,uid,item):
    before=quantity(read_player_inventory(p.g),item)
    mon=next((m for m in p.state()['party'] if m['uid']==uid),None)
    if before<1 or not mon or mon['held_item']:raise AcquisitionAttention('Для Give нужен предмет в сумке и пустые руки курьера')
    open_party(p);target=mon['slot']-1
    for _ in range(40):
        c=p.state()['controls']
        if 'Task_HandleChooseMonInput' not in p.tasks():p.advance(12);continue
        here=c['party_cursor']
        if here==target:p.tap('A',wait=90);break
        p.tap('RIGHT' if here==0 else 'LEFT' if target==0 else 'DOWN' if here<target else 'UP',wait=30)
    else:raise AcquisitionAttention('Не выбран курьер для Give')
    for _ in range(20):
        c=p.state()['controls'];actions=c.get('party_actions',[])
        if 3 not in actions:raise AcquisitionAttention('Недоступно меню Item')
        target=actions.index(3)
        if c['menu_cursor']==target:p.tap('A',wait=60);break
        p.tap('DOWN' if c['menu_cursor']<target else 'UP',wait=30)
    if p.state()['controls'].get('party_actions')!=[4,5,9]:raise AcquisitionAttention('Неожиданное меню предмета')
    for _ in range(10):
        c=p.state()['controls']
        if c['menu_cursor']==0:p.tap('A',wait=180);break
        p.tap('UP',wait=30)
    tm=289<=item<=338;desired=364 if tm else item
    pocket=1 if tm else 2 if product(item)['pocket']=='balls' else 0
    sy=symbols(p.g.root);bag=sy['gBagMenuState']
    for _ in range(160):
        if 'Task_BagMenu_HandleInput' not in p.tasks():p.advance(12);continue
        current=p.g.read16(bag+6)
        if current!=pocket:p.tap('RIGHT' if current<pocket else 'LEFT',wait=48);continue
        rows=[r for r in read_player_inventory(p.g)['items'] if r['pocket']==('key' if tm else 'balls' if pocket==2 else 'items')]
        row=next((r for r in rows if r['id']==desired),None)
        if not row:raise AcquisitionAttention('Предмет исчез из сумки')
        cursor=p.g.read16(bag+8+2*pocket)+p.g.read16(bag+14+2*pocket)
        if cursor==row['slot']:p.tap('A',wait=200);break
        p.tap('DOWN' if cursor<row['slot'] else 'UP',wait=30)
    else:raise AcquisitionAttention('Не выбран предмет в сумке')
    if tm:
        static=sy['sTMCaseStaticResources']
        for _ in range(160):
            if 'Task_HandleListInput' not in p.tasks():p.advance(12);continue
            rows=[r for r in read_player_inventory(p.g)['items'] if r['pocket']=='tmhm'];target=next(r['slot'] for r in rows if r['id']==item)
            cursor=p.g.read16(static+8)+p.g.read16(static+10)
            if cursor==target:p.tap('A',wait=200);break
            p.tap('DOWN' if cursor<target else 'UP',wait=30)
        else:raise AcquisitionAttention('Не выбран TM в футляре')
    for _ in range(80):
        if next(m for m in p.state()['party'] if m['uid']==uid)['held_item']==item:break
        p.tap('A',wait=30)
    else:raise AcquisitionAttention('Игра не подтвердила Give')
    p.settle(button='B')
    if quantity(read_player_inventory(p.g),item)!=before-1:raise AcquisitionAttention('Не совпало количество после Give')
    p.save_game()
