"""Localization must affect presentation and search, never game identity."""
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from pokemon_red import i18n
from pokemon_red.entity_names import entities, entity_name, entity_aliases, location_matches, pokemon_name
from pokemon_red.locations import location_name
from pokemon_red.settings import Settings
from pokemon_red.collection import filter_pokemon


class LocalizationTests(unittest.TestCase):
    def tearDown(self):
        i18n.set_locale('en')

    def test_first_launch_is_english_and_existing_preferences_survive(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            settings = Settings(root)
            self.assertEqual(settings['language'], 'en')
            settings.set('language', 'ru-RU')
            settings.set('volume', 42)
            self.assertEqual(Settings(root)['language'], 'ru')
            self.assertEqual(Settings(root)['volume'], 42)
            settings.set('language', 'unsupported')
            self.assertEqual(Settings(root)['language'], 'en')

    def test_language_preference_uses_the_existing_save_hook(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = Settings(Path(folder))
            saved = []
            settings.save_hook = lambda: saved.append(dict(settings.values))
            settings.set('language', 'ru')
            self.assertEqual(saved[0]['language'], 'ru')
            self.assertFalse(settings.path.exists())

    def test_missing_russian_translation_falls_back_to_english_and_deduplicates(self):
        english = dict(i18n.messages('en'), **{'test.fallback': 'Route {number}'})
        with patch.object(i18n, 'messages', side_effect=lambda language: english if language == 'en' else {}):
            for _ in range(3):
                self.assertEqual(i18n.t('test.fallback', locale='ru', number=14), 'Route 14')
        events = [row for row in i18n.missing_translations() if row['key'] == 'test.fallback']
        self.assertEqual(len(events), 1)
        self.assertNotIn('number', events[0])

    def test_unknown_key_and_invalid_interpolation_do_not_crash_the_ui(self):
        self.assertEqual(i18n.t('test.readable_fallback'), 'Readable fallback')
        self.assertIn('{number}', i18n.t('location.route'))
        with patch.object(i18n, 'messages', return_value={'test.bad': '{value.__class__}'}):
            self.assertEqual(i18n.t('test.bad', value='x'), '{value.__class__}')

    def test_malformed_plural_translation_uses_the_english_fallback(self):
        english = {'test.plural': {'one': '{count} result', 'other': '{count} results'}}
        russian = {'test.plural': {'one': '{count} результат'}}
        with patch.object(i18n, 'messages', side_effect=lambda language: english if language == 'en' else russian):
            self.assertEqual(i18n.t('test.plural', locale='ru', count=22), '22 results')

    def test_russian_and_english_plural_rules(self):
        for n, word in [(1, 'покемон'), (2, 'покемона'), (5, 'покемонов'), (11, 'покемонов'), (21, 'покемон'), (22, 'покемона'), (25, 'покемонов'), (1.5, 'покемона')]:
            self.assertEqual(i18n.t('collection.count', locale='ru', count=n), f'{n} {word}')
        self.assertEqual(i18n.t('collection.count', locale='en', count=22), '22 Pokémon')

    def test_semantic_messages_can_be_rerendered_after_language_change(self):
        message = i18n.t('settings.language')
        self.assertEqual(message, 'Language')
        i18n.set_locale('ru')
        self.assertEqual(i18n.render(message), 'Язык')

    def test_route_search_accepts_both_languages_in_both_interface_locales(self):
        for locale in ('en', 'ru'):
            i18n.set_locale(locale)
            for query in ('маршрут 14', 'Route 14', 'ROUTE14', '  Route   14  '):
                self.assertTrue(location_matches(query, 'Route14'), query)
            self.assertFalse(location_matches('Route 15', 'Route14'))

    def test_species_move_ability_aliases_and_unicode_normalization(self):
        self.assertTrue(i18n.search_matches('БУЛЬБАЗАВР', entity_aliases('species', 1)))
        self.assertTrue(i18n.search_matches('Bulbasaur', entity_aliases('species', 1)))
        self.assertTrue(i18n.search_matches('Толчок', entity_aliases('moves', 33)))
        self.assertTrue(i18n.search_matches('Tackle', entity_aliases('moves', 33)))
        self.assertTrue(i18n.search_matches('Сверхрост', entity_aliases('abilities', 65)))
        self.assertTrue(i18n.search_matches('Overgrow', entity_aliases('abilities', 65)))
        self.assertTrue(i18n.search_matches('огнемет', 'Огнемёт'))
        self.assertTrue(i18n.search_matches('Ｎｉｄｏｒａｎ♀', 'Nidoran♀'))

    def test_owned_search_keeps_instance_uid_and_nickname(self):
        mon = dict(uid='instance-123', species_id=1, species='BULBASAUR', nickname='Мой герой', location='party')
        for query in ('bulbasaur', 'Бульбазавр', 'мой герой'):
            result = filter_pokemon([mon], query)
            self.assertEqual(result, [mon])
            self.assertIs(result[0], mon)
        self.assertEqual(i18n.render(pokemon_name(mon), locale='en'), 'Мой герой')

    def test_entity_fallbacks_and_all_games_have_complete_names(self):
        for kind, entries in entities().items():
            for key, entry in entries.items():
                self.assertTrue(entry['en'], (kind, key))
                self.assertTrue(entry['ru'], (kind, key))
        self.assertEqual(entity_name('species', 1, locale='ru'), 'Бульбазавр')
        self.assertEqual(entity_name('species', 1, locale='en'), 'Bulbasaur')
        self.assertEqual(entity_name('species', 'not-registered', 'Original name', locale='ru'), 'Original name')

    def test_floor_and_subarea_are_preserved(self):
        self.assertEqual(location_name('PewterCity', locale='en'), 'Pewter City')
        self.assertEqual(location_name('PewterCity', locale='ru'), 'Пьютер')
        self.assertEqual(location_name('RockTunnel_B1F', locale='ru'), 'Скальный туннель · −1 этаж')
        self.assertIn('B1F', location_name('RockTunnel_B1F', locale='en'))
        self.assertNotEqual(location_name('SafariZone_East'), location_name('SafariZone_West'))

    def test_entity_identity_disambiguates_fly_from_the_flying_type(self):
        from pokemon_red.entity_names import move_name
        i18n.set_locale('ru')
        move = move_name(19)
        self.assertEqual(move, 'Полёт')
        i18n.set_locale('en')
        self.assertEqual(i18n.render(move), 'Fly')
        self.assertEqual(i18n.render('Летающий'), 'Flying')

    def test_numbers_and_dates_use_locale_formatting(self):
        self.assertEqual(i18n.format_number(1234.5, locale='en', decimals=1), '1,234.5')
        self.assertEqual(i18n.format_number(1234.5, locale='ru', decimals=1), '1\u00a0234,5')
        from datetime import datetime
        date = datetime(2026, 11, 15, 12)
        self.assertTrue(i18n.format_datetime(date, locale='en').startswith('2026-11-15'))
        self.assertTrue(i18n.format_datetime(date, locale='ru').startswith('15.11.2026'))

    def test_legacy_worker_messages_render_without_changing_the_source(self):
        text = 'Последнее сохранение · 18:20:00'
        self.assertIn('18:20:00', i18n.render(text, locale='en'))
        self.assertNotIn('Последнее', i18n.render(text, locale='en'))
        self.assertEqual(i18n.render(text, locale='ru'), text)
        self.assertEqual(i18n.render('Отряд', locale='en'), 'Party')


class LocalizedWidgetsTests(unittest.TestCase):
    def setUp(self):
        from pokemon_red import localized_tk as tk
        self.tk = tk
        self.window = tk.Tk()
        self.window.withdraw()
        i18n.set_locale('en')

    def tearDown(self):
        self.window.destroy()
        i18n.set_locale('en')

    def test_static_labels_and_semantic_keys_switch_live(self):
        label = self.tk.Label(self.window, text='Отряд')
        semantic = self.tk.Label(self.window, text=i18n.t('settings.language'))
        self.assertEqual(label.cget('text'), 'Party')
        i18n.set_locale('ru')
        self.assertEqual(label.cget('text'), 'Отряд')
        self.assertEqual(semantic.cget('text'), 'Язык')
        i18n.set_locale('en')
        self.assertEqual(label.cget('text'), 'Party')

    def test_variables_and_entries_retain_source_values(self):
        variable = self.tk.StringVar(self.window, value='Отряд')
        label = self.tk.Label(self.window, textvariable=variable)
        entry = self.tk.Entry(self.window, textvariable=variable)
        display = str(self.window.getvar(label.cget('textvariable')))
        self.assertEqual(display, 'Party')
        self.assertEqual(variable.get(), 'Отряд')
        self.assertEqual(entry.get(), 'Отряд')
        variable.set('Покемоны')
        self.assertEqual(str(self.window.getvar(label.cget('textvariable'))), 'Pokémon')
        self.assertEqual(variable.get(), 'Покемоны')

    def test_callbacks_and_canvas_items_keep_their_identity(self):
        clicked = []
        button = self.tk.Button(self.window, text='Отряд', command=lambda: clicked.append('party'))
        canvas = self.tk.Canvas(self.window)
        item = canvas.create_text(10, 10, text='Покемоны')
        i18n.set_locale('ru')
        button.invoke()
        self.assertEqual(clicked, ['party'])
        self.assertEqual(canvas.itemcget(item, 'text'), 'Покемоны')
        canvas.itemconfigure(item, text='Отряд')
        i18n.set_locale('en')
        self.assertEqual(canvas.itemcget(item, 'text'), 'Party')

    def test_menu_identity_survives_insertion_and_translation(self):
        menu = self.tk.Menu(self.window, tearoff=False)
        menu.add_command(label='Отряд')
        menu.insert_command(0, label='Покемоны')
        self.assertEqual(menu.entrycget(1, 'label'), 'Party')
        self.assertEqual(menu.source_label(1), 'Отряд')
        menu.entryconfigure(1, label='Звук')
        i18n.set_locale('ru')
        self.assertEqual(menu.entrycget(0, 'label'), 'Покемоны')
        self.assertEqual(menu.entrycget(1, 'label'), 'Звук')
        i18n.set_locale('en')
        self.assertEqual(menu.entrycget(1, 'label'), 'Sound')

    def test_destroyed_interpreter_cannot_break_a_new_language_switch(self):
        other = self.tk.Tk()
        retained_canvas = self.tk.Canvas(other)
        retained_canvas.create_text(10, 10, text='Отряд')
        other.destroy()
        i18n.set_locale('ru')
        self.assertEqual(i18n.get_locale(), 'ru')

    def test_wrapped_text_fits_a_narrow_window_in_both_languages(self):
        self.window.geometry('320x300')
        label = self.tk.Label(self.window, text='Поиск по видам', wraplength=490)
        label.pack(fill='x')
        self.window.deiconify()
        for language in ('en', 'ru'):
            i18n.set_locale(language)
            self.window.update()
            self.assertLessEqual(int(label.cget('wraplength')), label.winfo_width())


class LanguagePersistenceTests(unittest.TestCase):
    def test_application_language_uses_the_owner_writer_and_preserves_other_settings(self):
        from pokemon_red.engine_runtime import EngineRuntime
        from pokemon_red.engine import Game
        with tempfile.TemporaryDirectory() as folder:
            session = Path(folder) / 'Profile'
            application = Path(folder) / 'Application'
            (session / 'Data').mkdir(parents=True)
            for name in ('native', 'vendor', 'runtime', 'Bots', 'src', 'assets'):
                (session / name).symlink_to(ROOT / name, target_is_directory=True)
            (session / 'Data/FireRed.gba').symlink_to(ROOT / 'Data/FireRed.gba')
            (session / 'Data/settings.json').write_text(json.dumps(dict(panel_on_start=False, sound_enabled=False, autosave_enabled=False)))
            with Game(session, resume=False) as game:
                game.advance(1)
                game.save()
            settings = Settings(application)
            settings.set('volume', 42)
            runtime = EngineRuntime(session, paused=True)
            try:
                runtime.ready.result(5)
                runtime.submit('application_language', str(application), 'ru').result(5)
                self.assertEqual(Settings(application)['language'], 'ru')
                self.assertEqual(Settings(application)['volume'], 42)
                self.assertEqual(Settings(session)['language'], 'en')
            finally:
                runtime.take_control(close=True)
                runtime.finished.result(8)
                runtime.thread.join(1)


class CatalogAuditTests(unittest.TestCase):
    def test_all_catalogs_and_registered_source_messages_are_complete(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('check_localization', ROOT / 'tools/check_localization.py')
        checker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(checker)
        report = checker.audit()
        self.assertTrue(report['ok'], report['errors'])


if __name__ == '__main__':
    unittest.main()
