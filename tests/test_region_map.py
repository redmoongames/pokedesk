"""Every acquisition location resolves to the pinned FireRed Town Map."""
from pathlib import Path
import sys,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.region_map import atlas,destination,positions
from pokemon_red.pokemon_sources import encounter_index

class RegionMapTests(unittest.TestCase):
    def test_every_encounter_map_has_a_position(self):
        names={r['map'] for rows in encounter_index(ROOT).values() for r in rows}
        self.assertEqual(len(names),124)
        for name in names:
            with self.subTest(name=name):
                place=destination(ROOT,name);self.assertIsNotNone(place);self.assertTrue(place['points']);self.assertTrue(place['nearby'])
                self.assertTrue(all(0<=x<22 and 0<=y<15 for x,y in place['points']))
    def test_exact_floor_is_kept_while_cave_uses_a_shared_marker(self):
        upper=destination(ROOT,'CeruleanCave_2F');lower=destination(ROOT,'CeruleanCave_B1F')
        self.assertEqual(upper['page'],'kanto');self.assertEqual(upper['points'],[(14,3)])
        self.assertEqual(upper['points'],lower['points']);self.assertNotEqual(upper['title'],lower['title'])
        self.assertIn('Cerulean',upper['nearby'][0])
    def test_routes_preserve_all_cells_and_diglett_has_two_access_points(self):
        self.assertEqual(destination(ROOT,'Route24')['points'],[(14,1),(14,2)])
        self.assertEqual(destination(ROOT,'DiglettsCave_B1F')['points'],[(4,5),(15,9)])
    def test_sevii_pages_and_tanoby_alias_are_explicit(self):
        for name,page in [('MtEmber_Summit','sevii_123'),('FourIsland_IcefallCave_1F','sevii_45'),('SixIsland_PatternBush','sevii_67')]:
            self.assertEqual(destination(ROOT,name)['page'],page)
        place=destination(ROOT,'SevenIsland_TanobyRuins_RixyChamber')
        self.assertEqual(place['target'],'MAPSEC_TANOBY_RUINS');self.assertTrue(place['note']);self.assertIn('Rixy',place['title'])
        ship=destination(ROOT,'SSAnne_Exterior');self.assertEqual(ship['target'],'MAPSEC_VERMILION_CITY');self.assertTrue(ship['note'])
    def test_unknown_location_does_not_silently_select_another_place(self):
        self.assertIsNone(destination(ROOT,'not-a-map'))

if __name__=='__main__':unittest.main()
