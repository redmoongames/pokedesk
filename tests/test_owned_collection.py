from pathlib import Path
import sys,unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.collection import owned_pokemon,filter_pokemon,location_label
from pokemon_red.player_inventory import read_player_inventory

class OwnedCollectionTests(unittest.TestCase):
    def test_party_pc_duplicates_and_shiny_search(self):
        a=dict(uid='a',species='BULBASAUR',nickname='Leaf',slot=1,shiny=True)
        b=dict(uid='b',species='BULBASAUR',nickname='Bud',box=13,box_slot=29,box_name='Last')
        inv=dict(ready=True,party=[a],boxes=[a,b,dict(b,uid='bad',checksum_valid=False)])
        rows=owned_pokemon(inv)
        self.assertEqual([m['uid'] for m in rows],['a','b'])
        self.assertEqual([m['uid'] for m in filter_pokemon(rows,'bulbasaur')],['a','b'])
        self.assertEqual([m['uid'] for m in filter_pokemon(rows,scope='shiny')],['a'])
        self.assertEqual([m['uid'] for m in filter_pokemon(rows,'last',scope='box')],['b'])
        self.assertEqual(location_label(rows[0]),'Отряд · место 1')
        self.assertEqual(location_label(rows[1]),'PC · Last · 30')
        self.assertEqual(filter_pokemon(rows,'Leaf',scope='box'),[])
        self.assertEqual(owned_pokemon(dict(ready=False,party=[a])),[])
        daycare=dict(b,uid='day',location='daycare',daycare_name='Route 5',slot=1)
        rows=owned_pokemon(dict(inv,daycare=[daycare]))
        self.assertEqual(len(rows),3);self.assertEqual(filter_pokemon(rows,'day care')[0]['uid'],'day')
        self.assertEqual(len(filter_pokemon(rows,scope='box')),1)

class BagTests(unittest.TestCase):
    def test_bag_decryption_and_pc_plain_quantity(self):
        sb,sb2,key=0x02001000,0x02006000,0xa17e
        mem={1:sb,2:sb2,sb2+0xf20:key,sb+0x310:13,sb+0x312:7^key,sb+0x430:4,sb+0x432:18^key,sb+0x298:13,sb+0x29a:3}
        class Game:
            root=ROOT;frame=123
            def read32(self,a):return mem.get(a,0)
            def read16(self,a):return mem.get(a,0)
        with patch('pokemon_red.player_inventory.symbols',return_value={'gSaveBlock1Ptr':1,'gSaveBlock2Ptr':2}),patch('pokemon_red.player_inventory.catalog',return_value={'items':{'13':'Potion','4':'Poke Ball'}}):
            result=read_player_inventory(Game())
        self.assertTrue(result['ready'])
        self.assertEqual([(r['pocket'],r['quantity']) for r in result['items']],[('items',7),('balls',18),('pc',3)])
    def test_invalid_save_pointers_do_not_read_bag(self):
        class Game:
            root=ROOT
            def read32(self,a):return 0
            def read16(self,a):raise AssertionError('invalid pointer dereference')
        with patch('pokemon_red.player_inventory.symbols',return_value={'gSaveBlock1Ptr':1,'gSaveBlock2Ptr':2}):
            self.assertEqual(read_player_inventory(Game()),dict(ready=False,items=[]))
if __name__=='__main__':unittest.main()
