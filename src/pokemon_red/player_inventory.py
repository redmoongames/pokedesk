"""Read-only FireRed Rev 1 bag/PC quantities; bag counts use the security key."""
from .telemetry import symbols
from .catalog import catalog
POCKETS=(('items','Предметы',0x310,42),('key','Ключевые',0x3b8,30),('balls','Покеболы',0x430,13),('tmhm','TM / HM',0x464,58),('berries','Ягоды',0x54c,43),('pc','PC',0x298,30))
def read_player_inventory(game):
    from .game_layout import save_block,hoenn
    sy=symbols(game.root);sb=save_block(game,1,sy);sb2=save_block(game,2,sy)
    if not 0x02000000<=sb<0x02040000-0x3d68 or not 0x02000000<=sb2<0x02040000-0xf24:return dict(ready=False,items=[])
    key=0 if hoenn(game) else game.read32(sb2+0xf20)&65535;names=catalog(game.root)['items'];rows=[]
    from .game_adapters import adapter
    pockets=adapter(game.root).memory.bag
    for pocket,title,offset,count in pockets:
        for slot in range(count):
            item=game.read16(sb+offset+slot*4)
            if not item:continue
            quantity=game.read16(sb+offset+slot*4+2)^(0 if pocket=='pc' else key)
            if str(item) not in names or not 0<quantity<=999:continue
            rows.append(dict(id=item,name=names[str(item)],quantity=quantity,pocket=pocket,pocket_name=title,slot=slot))
    return dict(ready=True,items=rows,frame=game.frame)
