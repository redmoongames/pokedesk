"""Regressions found while reviewing complete native screens in both locales."""
from copy import deepcopy
from pathlib import Path
import pickle
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from pokemon_red import i18n
from pokemon_red.entity_names import ability_name,entities,move_name,species_name
from pokemon_red.locations import location_name


class PresentationReviewTests(unittest.TestCase):
    def tearDown(self):
        i18n.set_locale('en')

    def test_entity_name_does_not_skip_the_rest_of_a_mixed_caption(self):
        english=i18n.render('LIMBER · пассивная способность ↗',locale='en')
        russian=i18n.render('LIMBER · пассивная способность ↗',locale='ru')
        self.assertEqual(english,'Limber · passive ability ↗')
        self.assertIn('Гибкость',russian)
        self.assertIn('пассивная способность',russian)

    def test_blank_lines_and_empty_fields_never_resolve_to_an_entity(self):
        for language in ('en','ru'):
            for value in ('',' ','\n','\n\n',' · ','  ⌄','1','42'):
                self.assertEqual(i18n.render(value,locale=language),value)
            self.assertEqual(i18n.render('custom_script.py  ⌄',locale=language),'custom_script.py  ⌄')

    def test_localized_values_survive_owner_snapshot_copy_and_worker_pickling(self):
        value=dict(title=i18n.t('pokemon.ability_action',name=ability_name(7)),
                   route=location_name('Route14',locale='en'),move=move_name(19))
        for detached in (deepcopy(value),pickle.loads(pickle.dumps(value))):
            self.assertEqual(detached,value)
            self.assertEqual(i18n.render(detached['title'],locale='en'),'Limber · passive ability ↗')
            self.assertEqual(i18n.render(detached['route'],locale='ru'),'Маршрут 14')
            self.assertEqual(i18n.render(detached['move'],locale='en'),'Fly')

    def test_badges_prefixes_and_complete_interior_names_refresh_both_ways(self):
        self.assertEqual(i18n.render('✓ Венузавр',locale='en'),'✓ Venusaur')
        self.assertEqual(i18n.render('✓ Venusaur',locale='ru'),'✓ Венузавр')
        self.assertEqual(i18n.render('Fuchsia City · Gym',locale='ru'),'Фуксия · Стадион')
        self.assertEqual(i18n.render('Route14',locale='ru'),'Маршрут 14')

    def test_all_pinned_location_names_have_a_russian_version(self):
        import re
        for key,entry in entities()['locations'].items():
            self.assertIsNone(re.search('[A-Za-z]{3}',entry['ru']),(key,entry['ru']))

    def test_editing_russian_copy_does_not_unregister_the_source_literal(self):
        import hashlib
        key='legacy.'+hashlib.sha256('Отряд'.encode()).hexdigest()[:16]
        catalog=i18n.messages('ru')
        try:
            with patch.dict(catalog,{key:'Команда'}):
                i18n._legacy_index.cache_clear();i18n._render_cached.cache_clear()
                self.assertEqual(i18n.render('Отряд',locale='ru'),'Команда')
                self.assertEqual(i18n.render('Отряд',locale='en'),'Party')
        finally:
            i18n._legacy_index.cache_clear();i18n._render_cached.cache_clear()


class NativeScreenReviewTests(unittest.TestCase):
    def setUp(self):
        from pokemon_red import localized_tk as tk
        self.tk=tk;self.root=tk.Tk();self.root.withdraw();i18n.set_locale('en')

    def tearDown(self):
        self.root.destroy();i18n.set_locale('en')

    def test_readonly_articles_switch_language_without_reopening(self):
        text=self.tk.Text(self.root)
        text.insert('1.0','Отряд\n\nLIMBER · пассивная способность ↗')
        text.configure(state='disabled')
        self.assertIn('Party',text.get('1.0','end'))
        i18n.set_locale('ru')
        self.assertIn('Отряд',text.get('1.0','end'))
        self.assertIn('Гибкость',text.get('1.0','end'))
        i18n.set_locale('en')
        self.assertIn('passive ability',text.get('1.0','end'))
        text.configure(state='normal');text.delete('1.0','end');text.configure(state='disabled')
        i18n.set_locale('ru');self.assertEqual(text.get('1.0','end-1c'),'')

    def test_button_requested_width_follows_the_translated_caption(self):
        from pokemon_red.ui import Button
        button=Button(self.root,'Сохранить сейчас');button.pack();before=button.winfo_reqwidth()
        i18n.set_locale('ru');self.root.update_idletasks()
        self.assertGreater(button.winfo_reqwidth(),before)
        self.assertLessEqual(button.font.measure(i18n.render(button.text)),button.winfo_reqwidth()-24)

    def test_select_keeps_user_names_and_choice_identity_when_language_changes(self):
        from pokemon_red.ui import Select
        variable=self.tk.StringVar(value='Отряд')
        picker=Select(self.root,variable,[i18n.literal('Отряд'),'Сохранить сейчас'])
        self.assertEqual(str(picker.text),'Отряд  ⌄')
        variable.set('Сохранить сейчас')
        self.assertEqual(str(picker.text),'Save now  ⌄')
        i18n.set_locale('ru')
        self.assertEqual(str(picker.text),'Сохранить сейчас  ⌄')
        self.assertEqual(variable.get(),'Сохранить сейчас')
        variable.set('Отряд');i18n.set_locale('en')
        self.assertEqual(str(picker.text),'Отряд  ⌄')

    def test_secondary_windows_inherit_the_application_menu(self):
        menu=self.tk.Menu(self.root,tearoff=False);menu.add_command(label='Отряд');self.root.configure(menu=menu)
        child=self.tk.Toplevel(self.root)
        self.assertEqual(child.cget('menu'),self.root.cget('menu'))


if __name__=='__main__':unittest.main()
