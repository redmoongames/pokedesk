"""Public card labels and status reference must describe Gen III precisely."""
import sys
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.locations import location_name
from pokemon_red.statuses import status_key,STATUS_RULES
from pokemon_red.catalog import catalog
from pokemon_red.types_ui import defensive_profile,types_for

class TeamModelTests(unittest.TestCase):
    def test_human_location_names_have_no_unlabelled_coordinates(self):
        self.assertEqual(location_name('PewterCity'),'Pewter City');self.assertEqual(location_name('PewterCity_PokemonCenter_1F'),'Pewter City · Pokémon Center · 1F');self.assertEqual(location_name('Route22'),'Route 22');self.assertEqual(location_name('PewterCity',locale='ru'),'Пьютер')
    def test_status_icons_distinguish_toxic_and_fainting(self):
        for code,key in [(7,'sleep'),(8,'poison'),(0x80,'toxic'),(0x10,'burn'),(0x20,'freeze'),(0x40,'paralysis')]:self.assertEqual(status_key(dict(hp=20,status_code=code)),key)
        self.assertEqual(status_key(dict(hp=0,status_code=8)),'fainted');self.assertIsNone(status_key(dict(hp=20,status_code=0,status='В норме')))
    def test_electric_pokemon_weaknesses_and_dual_flying_immunities(self):
        p=defensive_profile(dict(species_id=25,ability_id=9),ROOT);self.assertEqual(p['weak'],[(4,2)]);self.assertIn((13,.5),p['resist'])
        bird=defensive_profile(dict(species_id=21,ability_id=51),ROOT);self.assertIn((4,0),bird['immune']);self.assertIn((7,0),bird['immune']);self.assertNotIn((1,2),bird['weak'])
    def test_actual_battle_types_and_ability_immunity_are_used(self):
        levitate=defensive_profile(dict(species_id=25,ability_id=26),ROOT);self.assertIn((4,0),levitate['immune']);self.assertNotIn((4,2),levitate['weak'])
        self.assertEqual(types_for(dict(species_id=25,types=[11,11]),ROOT),[11])
    def test_shared_sqlite_reference_contains_status_explanations(self):
        data=catalog();self.assertEqual(set(data['mechanics']['statuses']),set(STATUS_RULES));self.assertIn('25%',data['mechanics']['statuses']['paralysis']['description']);self.assertIn('¼',data['mechanics']['statuses']['paralysis']['description'])

if __name__=='__main__':unittest.main()
