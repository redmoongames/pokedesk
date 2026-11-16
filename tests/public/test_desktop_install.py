"""First-run publication and rollback contracts, without proprietary resources."""
from pathlib import Path
import hashlib
import json
import tempfile
import threading
import runpy
import sys
import struct
from types import ModuleType
import unittest
from unittest.mock import patch

from pokemon_red import desktop_install as install
from pokemon_red.paths import session_paths
from pokemon_red.rom_resources import populations, sprite_png, Cartridge, SEED


class DesktopInstallTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bundle = self.root / 'Application with spaces'
        self.library = self.root / 'My portable saves'
        self.rom = self.root / 'user-cartridge'
        self.rom.write_bytes(b'\0' * (16*1024*1024))
        for tree in install.COPY_TREES:
            (self.bundle / tree).mkdir(parents=True)
            (self.bundle / tree / 'payload.txt').write_text(tree)
        (self.bundle / 'main.py').write_text('print("application")\n')
        (self.bundle / 'desktop-build.json').write_text(json.dumps(dict(schema=1, build_id='b'*64)))
        self.validation = patch.object(install, 'validate_rom')
        self.validation.start()
        self.addCleanup(self.validation.stop)
        resources = patch('pokemon_red.rom_resources.prepare_resources', side_effect=self.compile)
        self.resources = resources.start()
        self.addCleanup(resources.stop)

    @staticmethod
    def compile(staging, payload, progress):
        (staging / 'vendor').mkdir()
        (staging / 'vendor/local.json').write_text('{"generated":true}')
        return dict(schema=1, species=386)

    def prepare(self, **kwargs):
        return install.prepare_desktop(self.bundle, self.library, self.rom, **kwargs)

    def test_first_setup_publishes_private_rom_and_complete_pinned_installation(self):
        version = self.prepare()
        self.assertEqual((self.library / 'Data/FireRed.gba').read_bytes(), self.rom.read_bytes())
        self.assertFalse((version.root / 'Data').exists())
        self.assertTrue((version.root / 'vendor/local.json').is_file())
        self.assertEqual(session_paths(self.library).installation.root, version.root)
        self.assertEqual(install.installed_version(self.library, self.bundle), version)

    def test_setup_never_loads_or_rewrites_existing_saves(self):
        (self.library / 'Data').mkdir(parents=True)
        before = {'FireRed.state':b'private state', 'FireRed.sav':b'private save',
                  'profiles.json':b'private profiles', 'settings.json':b'private preferences'}
        for name, payload in before.items():
            (self.library / 'Data' / name).write_bytes(payload)
        with patch('pokemon_red.engine.Game', side_effect=AssertionError('Live core must not be opened')):
            self.prepare()
        for name, payload in before.items():
            self.assertEqual((self.library / 'Data' / name).read_bytes(), payload)

    def test_failed_update_preserves_binding_receipt_rom_and_save(self):
        first = self.prepare()
        saved = self.library / 'Data/FireRed.sav'
        saved.write_bytes(b'progress')
        binding = (self.library / '.pokedesk-paths.json').read_bytes()
        receipt = (self.library / install.RECEIPT).read_bytes()
        with patch('pokemon_red.rom_resources.prepare_resources', side_effect=OSError('disk full')):
            with self.assertRaisesRegex(OSError, 'disk full'):
                self.prepare()
        self.assertEqual((self.library / '.pokedesk-paths.json').read_bytes(), binding)
        self.assertEqual((self.library / install.RECEIPT).read_bytes(), receipt)
        self.assertEqual(saved.read_bytes(), b'progress')
        self.assertEqual(install.installed_version(self.library, self.bundle), first)
        self.assertFalse(list(self.library.glob('.setup-*')))

    def test_cancel_before_preparation_does_not_publish_or_write_rom(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(install.SetupCancelled):
            self.prepare(cancelled=cancel)
        self.resources.assert_not_called()
        self.assertFalse((self.library / 'Data/FireRed.gba').exists())
        self.assertFalse((self.library / install.RECEIPT).exists())

    def test_cancel_between_resource_stages_preserves_old_installation(self):
        self.prepare()
        receipt = (self.library / install.RECEIPT).read_bytes()
        cancelled = threading.Event()
        def compile_and_cancel(staging, payload, progress):
            cancelled.set()
            progress('setup.routes')
        with patch('pokemon_red.rom_resources.prepare_resources', side_effect=compile_and_cancel):
            with self.assertRaises(install.SetupCancelled):
                self.prepare(cancelled=cancelled)
        self.assertEqual((self.library / install.RECEIPT).read_bytes(), receipt)

    def test_app_update_during_preparation_cannot_adopt_a_mixed_installation(self):
        self.prepare()
        receipt = (self.library / install.RECEIPT).read_bytes()
        marker = (self.library / '.pokedesk-paths.json').read_bytes()
        def update_while_compiling(staging, payload, progress):
            result = self.compile(staging, payload, progress)
            (self.bundle / 'desktop-build.json').write_text(json.dumps(dict(schema=1, build_id='c'*64)))
            return result
        with patch('pokemon_red.rom_resources.prepare_resources', side_effect=update_while_compiling):
            with self.assertRaises(install.SetupUpdatedError):
                self.prepare()
        self.assertEqual((self.library / install.RECEIPT).read_bytes(), receipt)
        self.assertEqual((self.library / '.pokedesk-paths.json').read_bytes(), marker)

    def test_changed_or_corrupt_installation_is_not_reused(self):
        version = self.prepare()
        target = version.root / 'vendor/local.json'
        target.chmod(0o644)
        target.write_text('corrupt')
        self.assertIsNone(install.installed_version(self.library, self.bundle))
        repaired = self.prepare()
        self.assertNotEqual(repaired.root, version.root)
        self.assertEqual(target.read_text(), 'corrupt')
        self.assertEqual(install.installed_version(self.library, self.bundle), repaired)

    def test_failed_receipt_publication_restores_the_previous_installation_link(self):
        self.prepare()
        marker = self.library / '.pokedesk-paths.json'
        previous = marker.read_bytes()
        receipt = (self.library / install.RECEIPT).read_bytes()
        real_write = install.atomic_bytes
        def fail_receipt(path, *args, **kwargs):
            if Path(path).name == install.RECEIPT:
                raise OSError('disk full at publication')
            return real_write(path, *args, **kwargs)
        with patch.object(install, 'atomic_bytes', side_effect=fail_receipt):
            with self.assertRaisesRegex(OSError, 'disk full'):
                self.prepare()
        self.assertEqual(marker.read_bytes(), previous)
        self.assertEqual((self.library / install.RECEIPT).read_bytes(), receipt)

    def test_conflicting_rom_and_oversized_file_are_rejected_without_save_changes(self):
        (self.library / 'Data').mkdir(parents=True)
        target = self.library / 'Data/FireRed.gba'
        target.write_bytes(b'other cartridge')
        with self.assertRaisesRegex(ValueError, 'rom_conflict'):
            self.prepare()
        self.assertEqual(target.read_bytes(), b'other cartridge')
        self.rom.write_bytes(b'not a cartridge')
        with self.assertRaisesRegex(ValueError, 'bad_rom'):
            self.prepare()

    def test_setup_refuses_a_library_used_by_another_application(self):
        with install.setup_lock(self.library):
            with self.assertRaises(install.LibraryBusyError):
                self.prepare()

    def test_launch_uses_pinned_python_and_drops_host_python_configuration(self):
        version = self.prepare()
        with patch.dict('os.environ', dict(PYTHONHOME='foreign', PYTHONPATH='foreign', TCL_LIBRARY='foreign')):
            command, environment = install.launch_command(version, self.library)
        self.assertEqual(command[-2:], ['--root', str(self.library.resolve())])
        self.assertEqual(environment['POKEDESK_RELEASE_ID'], version.id)
        for key in ('PYTHONHOME', 'PYTHONPATH', 'TCL_LIBRARY'):
            self.assertNotIn(key, environment)

    def test_malformed_or_escaping_receipt_is_not_loaded(self):
        self.library.mkdir()
        for value in ([], None, dict(build_id='b'*64, rom_sha1=install.FIRERED.sha1,
                    release_id='../outside', slot='a'*32)):
            (self.library / install.RECEIPT).write_text(json.dumps(value))
            self.assertIsNone(install.installed_version(self.library, self.bundle))


class CartridgeCompilerTests(unittest.TestCase):
    def duplicate_map_cartridge(self):
        data = bytearray(1024)
        for offset, table, mons, species in ((0,0x100,0x200,41),(20,0x120,0x240,179)):
            struct.pack_into('<I', data, offset+4, 0x08000000+table)
            data[table] = 20
            struct.pack_into('<I', data, table+4, 0x08000000+mons)
            for slot in range(12):
                struct.pack_into('<BBH', data, mons+slot*4, 5,5,species)
        data[40] = 255
        cartridge = object.__new__(Cartridge)
        cartridge.data = bytes(data)
        cartridge.symbols = dict(gWildMonHeaders=0x08000000)
        return cartridge

    def test_unreleased_altering_cave_populations_are_not_catch_candidates(self):
        cartridge = self.duplicate_map_cartridge()
        metadata = json.loads((SEED / 'location_reference.json').read_text())
        name = next(name for name in metadata['maps'] if name.endswith('_AlteringCave'))
        self.assertEqual(name, 'SixIsland_AlteringCave')
        wild = cartridge.encounters(dict(group_order=['group'], group=[name]), metadata)
        rows = wild['wild_encounter_groups'][0]['encounters']
        self.assertEqual(len(rows), 1)
        self.assertEqual({m['species'] for m in rows[0]['land_mons']['mons']}, {'SPECIES_41'})

    def test_unrecognized_duplicate_map_tables_fail_closed(self):
        with self.assertRaisesRegex(ValueError, 'Ambiguous ordinary'):
            self.duplicate_map_cartridge().encounters(dict(group_order=['group'], group=['Route1']),
                                                       dict(maps=dict(Route1=dict(id='MAP_ROUTE1'))))

    def test_rom_hash_check_cannot_be_bypassed_by_filename(self):
        with self.assertRaises(ValueError):
            Cartridge(b'not a cartridge')

    def test_probabilities_include_every_level_and_keep_the_correct_weights(self):
        result = populations(dict(mons=[dict(species='SPECIES_19', min_level=3, max_level=4),
                                       dict(species='SPECIES_16', min_level=5, max_level=5)]), [70,30])
        self.assertEqual(result[0]['levels'], {'3':35, '4':35})
        self.assertEqual(result[0]['probability'], 70)
        self.assertEqual(sum(r['probability'] for r in result), 100)

    def test_pngs_are_built_from_supplied_pixels_not_external_artwork(self):
        palette = bytes(32)
        normal = sprite_png(bytes(32), palette, 8, 8)
        self.assertTrue(normal.startswith(b'\x89PNG\r\n\x1a\n'))
        self.assertIn(b'IHDR', normal)
        self.assertTrue(normal.endswith(b'IEND\xaeB`\x82'))


class DesktopBootstrapTests(unittest.TestCase):
    def test_spawn_entry_point_and_arguments_belong_to_the_pinned_installation(self):
        with tempfile.TemporaryDirectory() as temporary:
            library = Path(temporary) / 'Library'
            (library / 'Data').mkdir(parents=True)
            (library / 'Data/FireRed.gba').write_bytes(b'local fixture')
            version = Path(temporary) / 'pinned'
            cli = ModuleType('pokemon_red.cli')
            observed = {}
            def main():
                observed.update(entry=sys.modules['__main__'].__file__, argv=list(sys.argv))
            cli.main = main
            entry = Path(__file__).resolve().parents[2] / 'desktop_main.py'
            with patch.dict('os.environ', dict(POKEDESK_PINNED_ROOT=str(version), POKEDESK_LIBRARY=str(library))), \
                    patch.dict(sys.modules, {'pokemon_red.cli':cli}), \
                    patch.object(sys, 'path', list(sys.path)), patch.object(sys, 'argv', ['bootstrap']), \
                    patch('pokemon_red.installation_versions.read_version'), \
                    patch('pokemon_red.installation_versions.verify_installation'), \
                    patch('pokemon_red.editions.validate_rom'):
                runpy.run_path(str(entry), run_name='__main__')
            expected = str(version / 'main.py')
            self.assertEqual(observed, dict(entry=expected, argv=[expected, '--root', str(library)]))


if __name__ == '__main__':
    unittest.main()
