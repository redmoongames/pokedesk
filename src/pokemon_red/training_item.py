"""Owner-thread held-item menu action. No memory edits and no blocking waits."""
from .engine import BUTTONS
from .telemetry import read_state,symbols,read_controls,read_walk_state,read_learning_mon
from .player_inventory import read_player_inventory
from .field_actions import FieldMismatch
from .i18n import t

class TrainingItemRuntime:
    action='training_item'
    def __init__(self,game,args):
        self.provider=args.get('uid');self.item=args.get('item',197);self.take=bool(args.get('take'));self.phase='open';self.mask=0;self.last=-1;self.pulse_at=-100;self.started=game.frame;self.result={};self.cancelled=False
        state=read_state(game);mon=next((m for m in state.get('party',[]) if m['uid']==self.provider),None)
        if self.item!=197 or not mon or state.get('in_battle') or state['controls']['callback']!='CB2_Overworld' or state['controls']['field_locked']:raise ValueError(t('training.item_requires_field'))
        self.original=mon.get('held_item',0);self.before=self.quantity(game)
        if self.take and (not self.original or 121<=self.original<=132):raise ValueError(t('training.item_cannot_take'))
        if not self.take and (self.original or self.before<1):raise ValueError(t('training.item_cannot_give'))
    def quantity(self,game):return sum(r['quantity'] for r in read_player_inventory(game)['items'] if r['id']==self.item and r['pocket']!='pc')
    def cancel(self):self.mask=0;self.cancelled=True
    def press(self,key,game,delay=15):
        if game.frame-self.pulse_at>=delay:self.mask=BUTTONS[key];self.pulse_at=game.frame
    def poll(self,game):
        if self.cancelled:self.mask=0;return False
        if game.frame==self.last:return False
        self.last=game.frame;self.mask=0
        if game.frame-self.started>5400:raise FieldMismatch(t('training.item_timeout'))
        c=read_controls(game);walk=read_walk_state(game);tasks={v['name'] for v in c.get('tasks',[])};mon=read_learning_mon(game,self.provider)
        if walk.get('in_battle') or not mon:raise FieldMismatch(t('training.item_changed'))
        if game.read8(symbols(game.root)['gPaletteFade']+7)&0x80:return False
        expected=0 if self.take else self.item
        if mon.get('held_item')==expected and self.phase not in ('open','party','item'):
            if self.take and self.original==self.item and self.quantity(game)!=self.before+1:raise FieldMismatch(t('training.item_quantity'))
            if not self.take and self.quantity(game)!=self.before-1:raise FieldMismatch(t('training.item_quantity'))
            self.phase='close'
        if self.phase=='close':
            if c.get('callback')=='CB2_Overworld' and not c.get('field_locked') and not c.get('moving'):
                self.result=dict(equipped=not self.take,taken=self.take,uid=self.provider,item=self.original if self.take else self.item);return True
            self.press('B',game);return False
        if self.phase=='open':
            if 'Task_HandleChooseMonInput' in tasks:self.phase='party'
            elif 'Task_StartMenuHandleInput' in tasks:
                options=c.get('start_order',[])
                if 1 not in options:raise FieldMismatch(t('training.item_no_party_menu'))
                index=options.index(1);cursor=c.get('start_cursor',0);self.press('A' if cursor==index else 'DOWN' if cursor<index else 'UP',game)
            elif c.get('callback')=='CB2_Overworld' and not c.get('field_locked'):self.press('START',game,30)
        if self.phase=='party':
            actions=c.get('party_actions',[])
            if 'Task_HandleSelectionMenuInput' in tasks and 3 in actions:
                if c.get('party_cursor')!=mon['slot']-1 or c.get('party_action',0)!=0:raise FieldMismatch(t('training.item_changed'))
                index=actions.index(3);cursor=c.get('menu_cursor',0);self.press('A' if cursor==index else 'DOWN' if cursor<index else 'UP',game)
                if cursor==index and self.mask:self.phase='item'
            elif 'Task_HandleChooseMonInput' in tasks:
                target=mon['slot']-1;cursor=c.get('party_cursor',0);key='A' if cursor==target else 'RIGHT' if cursor==0 else 'LEFT' if target==0 else 'DOWN' if cursor<target else 'UP';self.press(key,game)
        elif self.phase=='item':
            actions=c.get('party_actions',[]);wanted=5 if self.take else 4
            if actions==[4,5,9]:
                if c.get('party_cursor')!=mon['slot']-1:raise FieldMismatch(t('training.item_changed'))
                index=actions.index(wanted);cursor=c.get('menu_cursor',0);self.press('A' if cursor==index else 'DOWN' if cursor<index else 'UP',game)
                if cursor==index and self.mask:self.phase='confirm' if self.take else 'bag'
        elif self.phase=='bag':
            if 'Task_BagMenu_HandleInput' in tasks:
                sy=symbols(game.root);bag=sy['gBagMenuState'];pocket=game.read16(bag+6)
                if pocket:self.press('LEFT',game,30)
                else:
                    row=next((r for r in read_player_inventory(game)['items'] if r['pocket']=='items' and r['id']==self.item),None)
                    if row is None:raise FieldMismatch(t('training.item_cannot_give'))
                    cursor=game.read16(bag+8)+game.read16(bag+14);self.press('A' if cursor==row['slot'] else 'DOWN' if cursor<row['slot'] else 'UP',game)
                    if cursor==row['slot'] and self.mask:self.phase='confirm'
        elif self.phase=='confirm':self.press('A',game,30)
        return False
