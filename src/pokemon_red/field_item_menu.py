"""Guarded key-item menu, shared by rods and the search bicycle."""
from .acquisition_play import AcquisitionAttention
from .telemetry import symbols
from .i18n import t

def use_field_item(p,item,*,started):
    """Use a key item through its live slot; preserve the registered item."""
    p.tap('START',wait=60)
    for _ in range(40):
        s=p.state();c=s['controls']
        if 'Task_StartMenuHandleInput' not in p.tasks(s):p.advance(6);continue
        if 2 not in c['start_order']:raise AcquisitionAttention(t('field_item.no_bag'))
        target=c['start_order'].index(2)
        if c['start_cursor']==target:p.tap('A',wait=90);break
        p.tap('DOWN' if c['start_cursor']<target else 'UP',wait=18)
    else:raise AcquisitionAttention(t('field_item.bag_timeout'))
    from .player_inventory import read_player_inventory
    sy=symbols(p.g.root);bag=sy['gBagMenuState'];pocket=1
    for _ in range(150):
        if 'Task_BagMenu_HandleInput' not in p.tasks():p.advance(6);continue
        current=p.g.read16(bag+6)
        if current!=pocket:p.tap('RIGHT' if current<pocket else 'LEFT',wait=35);continue
        row=next((r for r in read_player_inventory(p.g)['items'] if r['id']==item and r['pocket']=='key'),None)
        if row is None:raise AcquisitionAttention(t('field_item.missing'))
        cursor=p.g.read16(bag+8+2*pocket)+p.g.read16(bag+14+2*pocket)
        if cursor==row['slot']:p.tap('A',wait=30);break
        p.tap('DOWN' if cursor<row['slot'] else 'UP',wait=18)
    else:raise AcquisitionAttention(t('field_item.selection_timeout'))
    for _ in range(60):
        s=p.state();tasks=p.tasks(s)
        if started():return
        if 'Task_ItemContext_SingleRow' in tasks or 'Task_ItemContext_MultipleRows' in tasks or 'Task_FieldItemContextMenuHandleInput' in tasks:
            p.tap('UP' if s['controls']['menu_cursor'] else 'A',wait=18)
        else:p.advance(6)
    raise AcquisitionAttention(t('field_item.use_timeout',text=p.text()))
