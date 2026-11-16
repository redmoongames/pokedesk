"""Version provenance must not confuse ROM presence, progress or national IDs."""
from pathlib import Path
import importlib.util,json,sys,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.catalog import catalog
from pokemon_red.dex_reference import availability,dex_rows,filter_dex,origin,origin_label,origin_description

class DexReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows=dex_rows(ROOT);cls.numbers={s['national_id']:s['id'] for s in cls.rows}
    def test_all_transferable_generation_three_species_in_national_order(self):
        self.assertEqual([s['national_id'] for s in self.rows],list(range(1,387)))
        self.assertEqual(set(availability(ROOT)),set(catalog(ROOT)['species']))
    def test_exclusives_descendants_and_babies(self):
        for national in (27,37,79,199,240,298):self.assertEqual(origin(self.numbers[national],ROOT)['category'],'leafgreen')
        for national in (58,125,172,212,239,246,360):self.assertEqual(origin(self.numbers[national],ROOT)['category'],'firered')
        self.assertIn('Lax Incense',origin_description(self.numbers[360],ROOT))
    def test_trade_evolution_is_distinct_from_imported_species(self):
        self.assertEqual(origin_label(self.numbers[65],ROOT),'FireRed · обмен')
        self.assertIn('другим сохранением',origin_description(self.numbers[65],ROOT))
        self.assertFalse(origin(self.numbers[64],ROOT).get('trade'))
    def test_unreleased_altering_cave_is_not_normal_wild_availability(self):
        for national in (179,190,204,216,228,234,235):self.assertEqual(origin(self.numbers[national],ROOT)['category'],'other')
    def test_events_and_time_evolutions_are_not_marked_as_ordinary_catches(self):
        for national in (151,249,250,251,385,386):self.assertEqual(origin(self.numbers[national],ROOT)['category'],'event')
        for national in (196,197):
            self.assertEqual(origin(self.numbers[national],ROOT)['category'],'other');self.assertIn('день или ночь',origin_description(self.numbers[national],ROOT))
    def test_choices_not_claimed_simultaneously_available(self):
        for national in (1,4,7,138,140,243,244,245):self.assertTrue(origin(self.numbers[national],ROOT).get('choice'))
    def test_search_uses_national_number_and_full_russian_type_names(self):
        self.assertEqual([r['national_id'] for r in filter_dex(self.rows,'#386',root=ROOT)],[386])
        self.assertIn(self.numbers[65],{r['id'] for r in filter_dex(self.rows,'психический',root=ROOT)})
        self.assertFalse(filter_dex(self.rows,'Vulpix',category='firered',root=ROOT))
        self.assertEqual([r['national_id'] for r in filter_dex(self.rows,'Vulpix',category='leafgreen',root=ROOT)],[37])
    def test_build_matches_offline_reference(self):
        spec=importlib.util.spec_from_file_location('build_dex',ROOT/'tools/build_dex_reference.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
        self.assertEqual(mod.build(ROOT),json.loads((ROOT/'vendor/reference/dex_availability.json').read_text()))

class PokemonHubUITests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from types import SimpleNamespace
        from unittest.mock import Mock
        from pokemon_red.ui import BG,theme
        from pokemon_red.collection_view import CollectionView
        self.window=tk.Tk();self.window.geometry('540x650');theme(self.window)
        footer=tk.Frame(self.window,bg=BG);footer.pack(side='bottom',fill='x')
        container=tk.Frame(self.window,bg=BG);container.pack(fill='both',expand=True,padx=14)
        canvas=tk.Canvas(container,bg=BG);canvas.pack(fill='both',expand=True);body=tk.Frame(canvas,bg=BG);item=canvas.create_window(0,0,anchor='nw',window=body)
        canvas.bind('<Configure>',lambda e:canvas.itemconfigure(item,width=e.width));body.bind('<Configure>',lambda _:canvas.configure(scrollregion=canvas.bbox('all')))
        monitor=SimpleNamespace(folder=ROOT,take_control=Mock(),toggle_pause=Mock())
        self.panel=SimpleNamespace(monitor=monitor,footer=footer,page_containers={'collection':container},page_canvases={str(container):canvas},open_pokemon=Mock(),show=Mock())
        self.hub=CollectionView(self.panel,body);self.window.update()
    def tearDown(self):self.window.destroy()
    def test_scoped_search_and_full_navigation_labels_at_minimum_width(self):
        h=self.hub
        for key,q in [('party','Pikachu'),('owned','Shiny'),('dex','Vulpix')]:h.select(key);h.query.set(q);self.window.update()
        for key,q in [('party','Pikachu'),('owned','Shiny'),('dex','Vulpix')]:h.select(key);self.assertEqual(h.query.get(),q)
        for _,button in h.navigation.buttons:self.assertLessEqual(button.font.measure(button.text),button.winfo_width()-24)
        self.assertLess(h.navigation.winfo_rooty(),h.search.winfo_rooty())
    def test_dex_opens_by_internal_id_and_has_no_global_count_heading(self):
        h=self.hub;h.select('dex');h.dex_category.set('Все источники');h.query.set('#386');self.window.update();tree=h.dex.view
        self.assertEqual(len(tree.get_children()),1);number=tree.get_children()[0];tree.selection_set(number);h.dex.open_selected()
        self.panel.open_pokemon.assert_called_once_with(species_id=int(number));self.assertNotEqual(int(number),386)
        self.assertLessEqual(sum(tree.column(c,'width') for c in tree['columns']),tree.winfo_width()+2)
        self.assertEqual(tree.cget('height'),1)
    def test_default_dex_is_scoped_to_current_game_but_other_editions_are_explicit(self):
        h=self.hub;h.select('dex');self.assertEqual(h.dex_category.get(),'FireRed')
        h.query.set('Vulpix');self.window.update();self.assertEqual(h.dex.view.get_children(),())
        h.dex_category.set('Из LeafGreen');h.render();self.window.update();self.assertEqual(len(h.dex.view.get_children()),1)

    def test_acquisition_is_created_once_and_reuses_existing_view(self):
        import tkinter as tk
        from types import SimpleNamespace
        from unittest.mock import Mock,patch
        def create(panel,parent,dock,**_):return SimpleNamespace(actions=tk.Frame(dock),refresh=Mock(),close=Mock())
        with patch('pokemon_red.acquisition_view.AcquisitionView',side_effect=create) as factory:
            view=self.hub.open_acquisition();self.hub.select('party');self.assertIs(self.hub.open_acquisition(),view);factory.assert_called_once()
            self.assertEqual(self.hub.section.get(),'acquisition');self.assertFalse(self.hub.search.winfo_manager())

if __name__=='__main__':unittest.main()
