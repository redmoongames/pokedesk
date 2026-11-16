"""Reference accuracy, Gen III exceptions, exact XP and the actual native widgets."""
from pathlib import Path
from types import SimpleNamespace
from copy import deepcopy
from unittest.mock import Mock
import importlib.util,json,re,sys,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.catalog import catalog,move,species
from pokemon_red.move_reference import enrich_reference,offensive_profile,power_text,accuracy_text,category_text
from pokemon_red.experience_ui import level_budget

class MoveReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.data=catalog(ROOT)
    def profile(self,n):return offensive_profile(move(n,ROOT),self.data['effectiveness'])
    def test_every_move_has_russian_copy_and_offline_provenance(self):
        self.assertEqual(len(self.data['moves']),354)
        for key,m in self.data['moves'].items():
            self.assertRegex(m['description'],r'[А-Яа-я]');self.assertNotIn('{chance}',json.dumps(m['reference']))
            self.assertTrue(m['reference']['details']);self.assertEqual(m['reference']['id'],int(key));self.assertTrue(m['description_en'])
            self.assertIn('pret',m['reference']['sources'])
    def test_numeric_facts_and_battle_rules_stay_the_same(self):
        original=json.loads((ROOT/'vendor/catalog/firered.json').read_text())
        for key,m in original['moves'].items():
            for field,value in m.items():
                if field!='description':self.assertEqual(self.data['moves'][key][field],value,(key,field))
        self.assertEqual(self.data['effectiveness'],original['effectiveness'])
    def test_psychic_attack_shows_offensive_not_defensive_matchups(self):
        p=self.profile(60);self.assertEqual(p['strong'],[1,3]);self.assertEqual(p['resisted'],[8,14]);self.assertEqual(p['immune'],[17])
    def test_steel_resists_ghost_and_dark_in_generation_three(self):
        self.assertIn(8,self.profile(247)['resisted']);self.assertIn(8,self.profile(242)['resisted'])
        self.assertEqual(move(247,ROOT)['category'],'Physical');self.assertEqual(move(242,ROOT)['category'],'Special')
    def test_status_and_fixed_damage_do_not_promise_double_damage(self):
        self.assertEqual(self.profile(105)['mode'],'status')
        for n,immune in [(69,[7]),(101,[0]),(243,[17]),(82,[])]:
            p=self.profile(n);self.assertEqual(p['mode'],'fixed');self.assertEqual(p['immune'],immune);self.assertFalse(p['strong']);self.assertFalse(p['resisted'])
    def test_delayed_and_variable_moves_do_not_reuse_nominal_type_chart(self):
        for n in (248,353):self.assertEqual(self.profile(n)['mode'],'typeless');self.assertFalse(self.profile(n)['immune'])
        for n in (237,311,267):self.assertEqual(self.profile(n)['mode'],'variable')
        for n in (118,119,214,274):self.assertEqual(self.profile(n)['mode'],'special')
        self.assertEqual(power_text(move(237,ROOT)),'30–70');self.assertEqual(category_text(move(311,ROOT)),'Зависит от типа')
    def test_generation_changes_are_not_copied_from_modern_dex(self):
        self.assertEqual(move(282,ROOT)['power'],20);self.assertEqual(move(229,ROOT)['power'],20);self.assertEqual(move(344,ROOT)['effect_chance'],0)
        self.assertIn('не повышает', ' '.join(move(268,ROOT)['reference']['details']))
        self.assertIn('не повышает', ' '.join(move(254,ROOT)['reference']['details']))
        self.assertEqual(move(294,ROOT)['stat_changes'][0]['stages'],2)
        self.assertEqual(accuracy_text(move(12,ROOT)),'30% + ур.');self.assertEqual(accuracy_text(move(129,ROOT)),'Без проверки')
    def test_reference_rebuild_is_reproducible(self):
        spec=importlib.util.spec_from_file_location('move_reference_builder',ROOT/'tools/build_move_reference.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
        self.assertEqual(mod.build(ROOT),json.loads((ROOT/'vendor/catalog/moves_ru.json').read_text()))
    def test_wrong_generation_or_missing_rows_cannot_be_loaded(self):
        original=json.loads((ROOT/'vendor/catalog/firered.json').read_text());ref=json.loads((ROOT/'vendor/catalog/moves_ru.json').read_text())
        with self.assertRaises(ValueError):enrich_reference(deepcopy(original),dict(ref,generation=4))
        ref['moves'].pop('60')
        with self.assertRaises(ValueError):enrich_reference(deepcopy(original),ref)
    def test_partial_xp_and_level_100_are_accounted_for(self):
        for curve in self.data['growth']:
            b=level_budget(curve,30,40,curve[30]+10);self.assertEqual(b['remaining'],curve[40]-curve[30]-10);self.assertEqual(b['next_level'],curve[31]-curve[30]-10)
            self.assertEqual(level_budget(curve,100,100)['remaining'],0);self.assertEqual(level_budget(curve,100,100)['next_level'],0)
            self.assertEqual(sum(b['costs'][29:39]),curve[40]-curve[30])
    def test_invalid_xp_range_does_not_produce_a_misleading_plot(self):
        curve=self.data['growth'][0]
        for args in [(40,30,None),(0,30,None),(30,101,None),(30,40,0),(30,40,curve[31])]:
            with self.assertRaises(ValueError):level_budget(curve,*args)

class ReferenceWidgetTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        self.tk=tk;self.root=tk.Tk();self.root.withdraw();self.panel=SimpleNamespace(window=self.root,monitor=SimpleNamespace(folder=ROOT))
    def tearDown(self):self.root.destroy()
    def test_table_selection_is_preview_only_and_search_works_in_russian(self):
        from pokemon_red.learnset_ui import LearnsetView
        frame=self.tk.Frame(self.root);frame.pack();opened=Mock();v=LearnsetView(frame,ROOT,species(64,ROOT),None,opened)
        v.query.set('замешательства');self.root.update();self.assertTrue(v.mapping);self.assertIn(60,v.mapping.values());opened.assert_not_called()
        v.open_selected();opened.assert_called_once_with(v.selected)
        v.query.set('неттакогоприёма');self.root.update();self.assertEqual(v.mapping,{});self.assertEqual(v.open.cget('state'),'disabled')
    def test_chart_hover_and_target_recompute_exact_numbers(self):
        from pokemon_red.experience_ui import ExperienceView,number
        frame=self.tk.Frame(self.root);frame.pack();sp=species(64,ROOT);curve=catalog(ROOT)['growth'][sp['growth']];mon=dict(level=30,experience=curve[30]+10)
        v=ExperienceView(frame,self.panel,sp,lambda:mon);v.target.set(45);self.root.update()
        self.assertIn(number(curve[45]-mon['experience']),v.amount.cget('text'))
        x,y=v.chart.coords_for(30);v.chart.motion(SimpleNamespace(x=x,y=y));self.assertIn('Lv 30 → 31',v.readout.cget('text'))
        v.start.set(100);v.target.set(100);self.assertIn('0 XP',v.amount.cget('text'))
    def test_articles_fit_narrow_window_and_keep_source_links_scrollable(self):
        from pokemon_red.move_details_ui import show_move
        for n in (60,14,105,68,237,248,311):
            a=show_move(self.panel,n);w=a.winfo_toplevel();w.geometry('540x520');self.root.update()
            self.assertLessEqual(a.body.winfo_width(),a.canvas.winfo_width())
            self.assertGreater(a.canvas.bbox('all')[3],0)
            a.canvas.yview_moveto(1);self.root.update();self.assertGreater(a.canvas.yview()[1],.99)

if __name__=='__main__':unittest.main()
