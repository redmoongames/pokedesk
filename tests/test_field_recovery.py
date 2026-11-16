"""Known poison notifications recover; unrelated stories still require the player."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,Mock
import struct,sys,unittest,tempfile
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.field_recovery import poison_notification,PoisonRecovery,RecoveryMismatch
from pokemon_red.engine import BUTTONS
from pokemon_red.automation import Automation,Session,Request

class FieldRecoveryTests(unittest.TestCase):
    def game(self):
        s=dict(gMain=100,sLockFieldControls=200,sGlobalScriptContext=300,gTasks=1000,gPlayerParty=2000,
               EventScript_FieldPoison=0x8001000,EventScript_FieldWhiteOut=0x8001020,Task_TryFieldPoisonWhiteOut=0x8002000,CB2_Overworld=0x8003000,sMessageBoxType=400)
        memory={s['gMain']+4:s['CB2_Overworld']|1,s['sLockFieldControls']:1,s['sGlobalScriptContext']+8:s['EventScript_FieldPoison']+7,s['sMessageBoxType']:2}
        tasks=bytearray(640);struct.pack_into('<I',tasks,0,s['Task_TryFieldPoisonWhiteOut']|1);tasks[4]=1;struct.pack_into('<hh',tasks,8,1,1)
        game=SimpleNamespace(root=ROOT,frame=100,read8=lambda a:memory.get(a,0),read32=lambda a:memory.get(a,0),read_bytes=lambda a,n:bytes(tasks[:n]))
        return game,s,memory,tasks

    def test_only_known_script_task_and_fainted_member_allow_acknowledgement(self):
        g,s,mem,tasks=self.game()
        with patch('pokemon_red.field_recovery.symbols',return_value=s),patch('pokemon_red.field_recovery.read_party_mon',return_value=dict(uid='t',hp=0,nickname='Pika',checksum_valid=True)) as read:
            self.assertEqual(poison_notification(g)['uid'],'t')
            read.assert_called_with(g,s['gPlayerParty']+100,1)
            mem[s['sGlobalScriptContext']+8]=s['EventScript_FieldWhiteOut']+1
            self.assertIsNone(poison_notification(g))
            mem[s['sGlobalScriptContext']+8]=s['EventScript_FieldPoison']+7
            tasks[4]=0;self.assertIsNone(poison_notification(g));tasks[4]=1
            read.return_value['hp']=10;self.assertIsNone(poison_notification(g))

    def test_pulses_are_bounded_and_unknown_locked_dialog_never_gets_a(self):
        g,s,mem,_=self.game();r=PoisonRecovery(g)
        info=dict(uid='t',pokemon='Pika',state=1,message=2)
        with patch('pokemon_red.field_recovery.poison_notification',return_value=info),patch('pokemon_red.field_recovery.symbols',return_value=s):
            self.assertFalse(r.poll(g));self.assertEqual(r.mask,BUTTONS['A'])
            g.frame+=1;r.poll(g);self.assertEqual(r.mask,0)
        g.frame+=1;mem[s['sGlobalScriptContext']+8]=s['EventScript_FieldWhiteOut']+100
        with patch('pokemon_red.field_recovery.poison_notification',return_value=None),patch('pokemon_red.field_recovery.symbols',return_value=s):
            with self.assertRaises(RecoveryMismatch):r.poll(g)
        self.assertEqual(r.mask,0)

    def test_normal_unlock_completes_and_cancellation_releases_managed_mask(self):
        g,s,mem,_=self.game();r=PoisonRecovery(g);mem[s['sLockFieldControls']]=0
        with patch('pokemon_red.field_recovery.symbols',return_value=s),patch('pokemon_red.field_recovery.poison_notification',return_value=None):self.assertTrue(r.poll(g))
        c=Automation(ROOT,snapshot=lambda:{},checkpoint=lambda _:None,set_speed=lambda _:None,release=Mock())
        c.session=Session(SimpleNamespace(close=lambda:None));c.recovery_runtime=r;r.mask=BUTTONS['A']
        self.assertEqual(c.next_mask(BUTTONS['RIGHT']),BUTTONS['A']);c.stop()
        self.assertEqual(r.mask,0);self.assertTrue(r.cancelled);self.assertEqual(c.next_mask(BUTTONS['RIGHT']),BUTTONS['RIGHT']);c.close()

if __name__=='__main__':unittest.main()
