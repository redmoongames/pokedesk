"""Nature names match the ROM constants and modifiers match decoded stat maths."""
from pathlib import Path
import re,sys,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.natures import NATURE_NAMES,nature_effect
from pokemon_red.models import STAT_KEYS,calculate_stats

class NatureTests(unittest.TestCase):
    def test_names_match_all_25_pinned_rom_ids(self):
        constants={name:int(value) for name,value in re.findall(r'^#define\s+NATURE_(\w+)\s+(\d+)\b',(ROOT/'vendor/reference/pokemon_constants.h').read_text(),re.M)}
        self.assertEqual(len(NATURE_NAMES),25)
        for number,name in enumerate(NATURE_NAMES):self.assertEqual(constants[name],number)
    def test_familiar_effects_and_five_neutral_natures(self):
        for number,name,modifiers in [(2,'BRAVE',{'attack':10,'speed':-10}),(3,'ADAMANT',{'attack':10,'special_attack':-10}),(15,'MODEST',{'special_attack':10,'attack':-10}),(20,'CALM',{'special_defense':10,'attack':-10})]:
            self.assertEqual(nature_effect(number),dict(name=name,modifiers=modifiers))
        self.assertEqual([n for n in range(25) if not nature_effect(n)['modifiers']],[0,6,12,18,24])
    def test_every_effect_matches_existing_stat_calculation_and_hp_is_unchanged(self):
        info=dict(national_id=1,base_stats=dict.fromkeys(STAT_KEYS,100))
        neutral=calculate_stats(info,100,[0]*6,[0]*6,0)
        for number in range(25):
            actual=calculate_stats(info,100,[0]*6,[0]*6,number);effect=nature_effect(number)
            for key in STAT_KEYS:self.assertEqual(actual[key],neutral[key]*(100+effect['modifiers'].get(key,0))//100,(number,key))
            self.assertNotIn('hp',effect['modifiers'])
    def test_unknown_ids_never_become_a_neutral_nature(self):
        for value in (None,True,False,-1,25,100,'2',2.0):self.assertIsNone(nature_effect(value))

if __name__=='__main__':unittest.main()
