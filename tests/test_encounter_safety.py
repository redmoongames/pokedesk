"""Shiny safety uses validated opponent identity and latches the game pause."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
import struct,sys,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.encounter_safety import shiny_opponents,read_shiny_opponent
from pokemon_red.models import ORDERS
from pokemon_red.session_controller import SessionController as Monitor

class EncounterSafetyTests(unittest.TestCase):
    def memory(self,*,shiny=False,own=False,corrupt=False,flags=0):
        syms=dict(gMain=10000,gBattleTypeFlags=200,gEnemyParty=1000,gPlayerParty=2000)
        data=bytearray(100);pid=1 if shiny else 1000;ot=1
        struct.pack_into('<II',data,0,pid,ot);data[19]=2;data[84]=3
        struct.pack_into('<HH',data,86,15,15)
        plain=bytearray(48);struct.pack_into('<H',plain,ORDERS[pid%24].index('G')*12,19)
        struct.pack_into('<H',data,28,(sum(struct.unpack('<24H',plain))+int(corrupt))&65535)
        data[32:80]=b''.join(struct.pack('<I',v^pid^ot) for v in struct.unpack('<12I',plain))
        memory=bytearray(14000);memory[10000+0x439]=2;struct.pack_into('<I',memory,200,flags);memory[1000:1100]=data
        if own:memory[2000:2100]=data
        g=SimpleNamespace(root=ROOT,revision=1,read8=lambda a:memory[a],read32=lambda a:struct.unpack_from('<I',memory,a)[0],read_bytes=lambda a,n:bytes(memory[a:a+n]))
        return g,syms,memory

    def test_enemy_party_is_authoritative_not_stale_battler_side(self):
        s=dict(in_battle=True,party=[dict(uid='own',shiny=True)],battle=dict(flags=0,enemies=[dict(uid='own',shiny=True)],enemy_party=[dict(uid='foe',shiny=False,checksum_valid=True,species_id=19)]))
        self.assertEqual(shiny_opponents(s),[])
        s['battle']['enemy_party'][0]['shiny']=True;self.assertEqual(len(shiny_opponents(s)),1)
        s['battle']['enemy_party'][0]['uid']='own';self.assertEqual(shiny_opponents(s),[])

    def test_raw_guard_rejects_owned_corrupt_nonshiny_and_trainer_records(self):
        for opts in (dict(shiny=False),dict(shiny=True,own=True),dict(shiny=True,corrupt=True),dict(shiny=True,flags=8),dict(shiny=True,flags=2)):
            g,s,_=self.memory(**opts)
            with patch('pokemon_red.encounter_safety.symbols',return_value=s):self.assertIsNone(read_shiny_opponent(g),opts)
        g,s,mem=self.memory(shiny=True)
        with patch('pokemon_red.encounter_safety.symbols',return_value=s):
            foe=read_shiny_opponent(g);self.assertEqual(foe['species'],'RATTATA');self.assertEqual(foe['slot'],1)
            mem[10000+0x439]=0;self.assertIsNone(read_shiny_opponent(g))

    def test_party_selection_can_finish_without_trusting_old_active_identity(self):
        from pokemon_red.telemetry import battle_control_ready
        b=dict(telemetry_valid=False,enemies=[dict(uid='verified-enemy')])
        c=dict(callback='CB2_UpdatePartyMenu',tasks=[dict(name='Task_HandleChooseMonInput')])
        self.assertTrue(battle_control_ready(b,c))
        self.assertFalse(battle_control_ready(b,dict(c,callback='BattleMainCB2')))
        self.assertFalse(battle_control_ready(b,dict(c,tasks=[])))
        self.assertFalse(battle_control_ready(dict(b,enemies=[]),c))

    def test_shiny_does_not_poll_memory_or_interrupt_gameplay(self):
        m=object.__new__(Monitor);m.game=SimpleNamespace(advance=Mock());m.automation=SimpleNamespace(stop=Mock());m.create_slot=Mock();m.keys={'A'}
        with patch('pokemon_red.encounter_safety.read_shiny_opponent') as reader:
            self.assertFalse(m.check_shiny_encounter());reader.assert_not_called()
        m.automation.stop.assert_not_called();m.create_slot.assert_not_called();m.game.advance.assert_not_called();self.assertEqual(m.keys,{'A'})

if __name__=='__main__':unittest.main()
