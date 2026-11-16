"""Version-specific slot arithmetic, acquisition conditions and article identity."""
from pathlib import Path
from collections import defaultdict
import sys,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.catalog import catalog
from pokemon_red.pokemon_sources import source_data,encounters,encounter_index,location_title

class SourceDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.species=catalog(ROOT)['species'];cls.numbers={v['national_id']:int(k) for k,v in cls.species.items()}
    def test_abra_has_exact_firered_maps_rates_and_level_gaps(self):
        rows=encounters(63,ROOT)
        self.assertEqual([(r['map'],r['probability']) for r in rows],[('Route24',15),('Route25',15)])
        self.assertEqual(rows[0]['level_label'],'8, 10, 12');self.assertEqual(rows[1]['level_label'],'9, 11, 13')
        self.assertIn('180',source_data(63,ROOT)['alternatives'][0])
    def test_kadabra_cave_floors_are_separate(self):
        self.assertEqual({r['map']:r['probability'] for r in encounters(64,ROOT)},{'CeruleanCave_2F':11,'CeruleanCave_B1F':25})
        self.assertTrue(all(r['location'].endswith('F') for r in encounters(64,ROOT)))
    def test_alakazam_is_trade_evolution_without_a_fake_catch_chance(self):
        data=source_data(65,ROOT)
        self.assertEqual(data['encounters'],[]);self.assertEqual([p['species_id'] for p in data['parents']],[64])
        self.assertIn('Обменять',data['parents'][0]['condition']);self.assertFalse(data['needs_national_dex'])
        self.assertEqual({p['species_id'] for p in data['related']},{63,64})
    def test_diglett_chance_sums_all_duplicate_slots(self):
        rows=encounters(50,ROOT);self.assertEqual(len(rows),1);self.assertEqual(rows[0]['probability'],95)
        self.assertEqual(rows[0]['level_label'],'15–22')
    def test_each_rod_has_its_own_denominator(self):
        rows={r['method']:r for r in encounters(129,ROOT) if r['map']=='ViridianCity'}
        self.assertEqual(rows['old_rod']['probability'],100);self.assertEqual(rows['good_rod']['probability'],20)
        self.assertNotIn('super_rod',rows)
    def test_every_map_and_method_sums_to_one_hundred(self):
        sums=defaultdict(int)
        for rows in encounter_index(ROOT).values():
            for r in rows:sums[(r['map'],r['method'])]+=r['probability']
        self.assertGreater(len(sums),200);self.assertTrue(all(v==100 for v in sums.values()))
    def test_leafgreen_and_unreleased_altering_cave_tables_are_excluded(self):
        self.assertEqual(encounters(27,ROOT),[])
        at_cave={n for n,rows in encounter_index(ROOT).items() if any(r['map']=='SixIsland_AlteringCave' for r in rows)}
        self.assertEqual(at_cave,{41})
    def test_conditions_for_stones_items_friendship_and_unavailable_time(self):
        self.assertIn(catalog(ROOT)['items']['96'],source_data(26,ROOT)['parents'][0]['condition'])
        steelix=source_data(self.numbers[208],ROOT)
        self.assertIn('METAL COAT',steelix['parents'][0]['condition']);self.assertTrue(steelix['needs_national_dex'])
        self.assertIn('220',source_data(25,ROOT)['parents'][0]['condition'])
        self.assertIn('недоступна',source_data(self.numbers[196],ROOT)['parents'][0]['condition'])
    def test_all_species_use_internal_ids_and_family_links_are_symmetric(self):
        self.assertNotEqual(self.numbers[386],386)
        for key in self.species:
            n=int(key);data=source_data(n,ROOT);self.assertEqual(data['name'],self.species[key]['name'])
            self.assertNotIn(n,{r['species_id'] for r in data['related']})
            for row in data['related']:self.assertIn(n,{r['species_id'] for r in source_data(row['species_id'],ROOT)['related']})
    def test_location_names_keep_floor_and_subarea(self):
        self.assertEqual(location_title('RockTunnel_B1F'),'Rock Tunnel · B1F')
        self.assertNotEqual(location_title('SafariZone_East'),location_title('SafariZone_West'))

if __name__=='__main__':unittest.main()
