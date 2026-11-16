"""Local encounter tables and left-sidebar capture controls have no engine reads."""
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock,patch
import sys,tempfile,json,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.field_encounters import populations,land_tiles
import test_battle_sidebar as fixtures

class PopulationTests(unittest.TestCase):
    def test_location_methods_each_sum_to_100_and_keep_floor_specific_levels(self):
        for name,methods in populations(ROOT).items():
            for method,rows in methods.items():self.assertEqual(sum(r['probability'] for r in rows),100,(name,method))
        rows=populations(ROOT)['Route11']['land_mons'];self.assertEqual(next(r['probability'] for r in rows if r['species_id']==96),25)
        self.assertIn('cave',land_tiles(ROOT,'PokemonTower_5F').values());self.assertIn('grass',land_tiles(ROOT,'Route11').values())
        self.assertFalse(populations(ROOT).get('ViridianCity_PokemonCenter_1F'))
    def test_leafgreen_uses_its_own_species_table(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);(root/'Data').mkdir();(root/'vendor').symlink_to(ROOT/'vendor');(root/'Data/game.json').write_text(json.dumps({'game':'leafgreen'}))
            red={r['species_id'] for r in populations(ROOT)['Route11']['land_mons']};green={r['species_id'] for r in populations(root)['Route11']['land_mons']}
            self.assertIn(23,red);self.assertNotIn(23,green);self.assertIn(27,green)

class FieldSidebarTests(unittest.TestCase):
    setUp=fixtures.SidebarTests.setUp
    tearDown=fixtures.SidebarTests.tearDown
    def test_trainer_has_no_capture_control_even_if_stale_status_says_available(self):
        self.view.update(dict(ready=True,in_battle=False,map=dict(name='Route11'),position=dict(x=15,y=13)))
        self.monitor.status['battle_capture']=dict(active=False,available=True,reason='');self.view.update(self.s);self.root.update()
        self.assertFalse(self.view.capture.winfo_ismapped());self.view.toggle_capture();self.monitor.runtime.submit.assert_not_called()
        with patch('pokemon_red.catch_view.open_autocatch') as catch:self.view.field.open_capture();catch.assert_not_called()
        self.s['battle']['flags']=0;self.view.update(self.s);self.root.update();self.assertTrue(self.view.capture.winfo_ismapped())
    def test_field_selection_opens_capture_for_exact_location_and_method(self):
        s=dict(ready=True,in_battle=False,map=dict(name='Route11'),position=dict(x=15,y=13));self.view.update(s);self.root.update();field=self.view.field
        self.assertTrue(field.frame.winfo_ismapped());self.assertIn('grass',field.where.cget('text'));self.assertFalse(self.view.footer.winfo_ismapped())
        field.table.selection_set('96');self.root.update();self.monitor.panel=NS(open_pokemon=Mock())
        with patch('pokemon_red.catch_view.open_autocatch') as catch:
            field.open_capture();catch.assert_called_once_with(self.monitor.panel,96,route='Route11',method='land_mons')
        self.monitor.runtime.submit.assert_not_called()
    def test_each_encounter_has_an_icon_in_land_rod_and_surf_tables(self):
        self.view.update(dict(ready=True,in_battle=False,map=dict(name='Route6'),position=dict(x=10,y=10)));self.root.update();field=self.view.field
        for method in ('land_mons','old_rod','good_rod','super_rod','water_mons'):
            field.method.set(next(label for label,value in field.methods.items() if value==method));field.fill();self.root.update()
            self.assertTrue(field.rows,method)
            for key in field.rows:self.assertTrue(field.table.item(key,'image'),(method,key))
    def test_no_encounters_disables_capture_and_map_change_does_not_keep_old_species(self):
        self.view.update(dict(ready=True,in_battle=False,map=dict(name='Route11'),position=dict(x=15,y=13)));self.root.update()
        self.view.update(dict(ready=True,in_battle=False,map=dict(name='ViridianCity_PokemonCenter_1F'),position=dict(x=7,y=7)));self.root.update()
        self.assertFalse(self.view.field.rows);self.assertEqual(self.view.field.capture.cget('state'),'disabled')
        self.view.field.open_capture();self.monitor.runtime.submit.assert_not_called()
    def test_capture_footer_stays_visible_in_a_small_cave_panel(self):
        self.view.window.geometry('300x600');self.view.update(dict(ready=True,in_battle=False,map=dict(name='PokemonTower_5F'),position=dict(x=3,y=3)));self.root.update()
        button=self.view.field.capture;bottom=button.winfo_rooty()+button.winfo_height();self.assertLessEqual(bottom,self.view.window.winfo_rooty()+self.view.window.winfo_height())
        self.assertTrue(button.winfo_ismapped());self.assertGreater(self.view.field.table.winfo_height(),50)

if __name__=='__main__':unittest.main()
