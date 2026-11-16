"""Acknowledge only the verified Gen III overworld poison-faint notification.

This is not a general dialogue skipper. NPC/story scripts never acquire this
executor. All input is frame-owned, verified again before A and cancellable.
"""
from .game_layout import main_flags
from .engine import BUTTONS
from .telemetry import symbols, read_party_mon
import struct


class RecoveryMismatch(RuntimeError):
    pass


def poison_notification(game):
    s=symbols(game.root)
    if main_flags(game,s)&2:return None
    if (game.read32(s['gMain']+4)&~1)!=s['CB2_Overworld'] or not game.read8(s['sLockFieldControls']):return None
    if not all(k in s for k in ('EventScript_FieldPoison','EventScript_FieldWhiteOut','Task_TryFieldPoisonWhiteOut')):return None
    pointer=game.read32(s['sGlobalScriptContext']+8)
    if not s['EventScript_FieldPoison']<=pointer<s['EventScript_FieldWhiteOut']:return None
    tasks=game.read_bytes(s['gTasks'],16*40)
    for i in range(16):
        offset=i*40
        if tasks[offset+4] and (struct.unpack_from('<I',tasks,offset)[0]&~1)==s['Task_TryFieldPoisonWhiteOut']:
            state,index=struct.unpack_from('<hh',tasks,offset+8)
            if state not in (0,1,2) or not 0<=index<=6 or state==1 and index>=6:return None
            mon=None
            if state==1:
                mon=read_party_mon(game,s['gPlayerParty']+index*100,index)
                if not mon.get('checksum_valid') or mon['hp']!=0:return None
            return dict(kind='poison_faint',task=i,state=state,party_index=index,uid=mon['uid'] if mon else None,
                        pokemon=mon.get('nickname') if mon else None,message=game.read8(s['sMessageBoxType']),script=pointer)
    return None


class PoisonRecovery:
    def __init__(self,game):
        self.started=game.frame
        self.last_frame=-1
        self.last_press=-100
        self.mask=0
        self.cancelled=False
        self.fainted={}

    def info(self):
        return dict(kind='poison_faint',managed=True,fainted=list(self.fainted))

    def cancel(self):
        self.cancelled=True
        self.mask=0

    def poll(self,game):
        if self.cancelled:raise RecoveryMismatch('Управление возвращено игроку')
        if self.last_frame==game.frame:return False
        self.last_frame=game.frame
        self.mask=0
        if game.frame-self.started>900:raise RecoveryMismatch('Уведомление об обмороке не завершилось за отведённое время')
        c=poison_notification(game)
        if c:
            if c['uid']:self.fainted[c['uid']]=c['pokemon']
            if c['state']==1 and c['message'] and game.frame-self.last_press>=8:
                self.mask=BUTTONS['A'];self.last_press=game.frame
            return False
        s=symbols(game.root)
        if (game.read32(s['gMain']+4)&~1)==s['CB2_Overworld'] and not game.read8(s['sLockFieldControls']):return True
        pointer=game.read32(s['sGlobalScriptContext']+8)
        if s['EventScript_FieldPoison']<=pointer<s['EventScript_FieldWhiteOut']:return False
        raise RecoveryMismatch('После уведомления открылся другой сценарий; нужен игрок')
