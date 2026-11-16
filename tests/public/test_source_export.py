"""Adversarial source/package distribution contracts, all on synthetic files."""
import importlib.util
import io
import json
from pathlib import Path
import stat
import struct
import tarfile
import tempfile
import unittest
import zipfile
import zlib

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('public_source_export', ROOT / 'tools/export_source.py')
exporter = importlib.util.module_from_spec(spec);spec.loader.exec_module(exporter)


class SourceExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name);self.project = self.base / 'project';self.output = self.base / 'export'
        (self.project / 'tools').mkdir(parents=True)
        self.policy = dict(schema=1, files=['tools/source_export_manifest.json', 'README.github.md', 'src/pokemon_red/healing.py'], trees=[], rename={'README.github.md':'README.md'})
        self.write('README.github.md', b'Public source preview\n')
        self.write('src/pokemon_red/healing.py', b'def recovered():\n    return True\n')
        self.save_policy()

    def write(self, name, data):
        path = self.project / name;path.parent.mkdir(parents=True, exist_ok=True);path.write_bytes(data);return path

    def save_policy(self):
        self.write('tools/source_export_manifest.json', json.dumps(self.policy).encode())

    def export(self):return exporter.export_source(self.project, self.output)

    def test_roundtrip_records_hashes_without_private_paths_and_leaves_user_data(self):
        private = self.write('Data/FireRed.state', b'private save');self.write('ROMs/game.gba', b'local game')
        self.export();self.assertTrue(exporter.verify_export(self.output)['verified'])
        self.assertEqual(private.read_bytes(), b'private save')
        self.assertFalse((self.output / 'Data').exists());self.assertFalse((self.output / 'ROMs').exists())
        text = (self.output / exporter.MANIFEST).read_text();self.assertNotIn(str(self.project), text)
        self.assertEqual((self.output / 'README.md').read_bytes(), (self.output / 'README.github.md').read_bytes())

    def test_existing_output_is_never_overwritten(self):
        self.output.mkdir();sentinel = self.output / 'keep';sentinel.write_text('keep')
        with self.assertRaises(exporter.ExportError):self.export()
        self.assertEqual(sentinel.read_text(), 'keep')

    def test_export_cannot_write_inside_working_installation(self):
        with self.assertRaises(exporter.ExportError):exporter.export_source(self.project, self.project / 'Data/export')

    def test_policy_cannot_opt_private_data_back_in(self):
        for name in ('Data/x.py', 'Profiles/x.py', 'Sessions/x.py', 'tests/fixtures/x.py', 'vendor/x.py', 'safe/game.gba', 'safe/game.state.gz'):
            with self.subTest(name=name):
                self.policy['files'].append(name);self.save_policy()
                with self.assertRaises(exporter.ExportError):self.export()
                self.assertFalse(self.output.exists());self.policy['files'].pop()

    def test_source_symlink_and_symlink_parent_are_rejected(self):
        code = self.project / 'src/pokemon_red/healing.py';code.unlink();code.symlink_to(self.project / 'README.github.md')
        with self.assertRaises(exporter.ExportError):self.export()
        code.unlink();parent = code.parent;parent.rmdir();parent.symlink_to(self.base, target_is_directory=True)
        with self.assertRaises(exporter.ExportError):self.export()

    def test_content_scan_rejects_personal_paths_credentials_and_binary_disguises(self):
        samples = [('personal', ('/Us'+'ers/alice/private/').encode()), ('key', ('gh'+'p_'+'a'*32).encode()), ('binary', b'\0state')]
        for label, data in samples:
            with self.subTest(label=label):
                self.write('src/pokemon_red/healing.py', data)
                with self.assertRaises(exporter.ExportError):self.export()
                self.assertFalse(self.output.exists())

    def test_folder_verification_detects_modified_and_missing_payload(self):
        self.export();code = self.output / 'src/pokemon_red/healing.py';code.write_text('changed')
        with self.assertRaises(exporter.ExportError):exporter.verify_export(self.output)
        code.unlink()
        with self.assertRaises(exporter.ExportError):exporter.verify_export(self.output)

    def test_folder_verification_rejects_unlisted_files_and_symlinks(self):
        self.export();extra = self.output / 'extra.py';extra.write_text('extra')
        with self.assertRaises(exporter.ExportError):exporter.verify_export(self.output)
        extra.unlink();extra.symlink_to(self.project / 'README.github.md')
        with self.assertRaises(exporter.ExportError):exporter.verify_export(self.output)

    def test_manifest_duplicate_is_rejected(self):
        self.export();path = self.output / exporter.MANIFEST;data = json.loads(path.read_text());data['files'].append(data['files'][0]);path.write_text(json.dumps(data))
        with self.assertRaises(exporter.ExportError):exporter.verify_export(self.output)

    def wheel(self, extras=()):
        path = self.base / 'test.whl'
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('pokemon_red/healing.py', (self.output / 'src/pokemon_red/healing.py').read_bytes())
            archive.writestr('pokedesk-0.dist-info/METADATA', 'Name: pokedesk\n')
            for name, data in extras:archive.writestr(name, data)
        return path

    def test_wheel_checks_payload_without_extracting(self):
        self.export();self.assertTrue(exporter.verify_artifact(self.wheel(), self.output)['verified'])
        for name, data in [('pokemon_red/stolen.py', 'extra'), ('Data/save.state', 'data'), ('../escape.py', 'bad')]:
            with self.subTest(name=name), self.assertRaises(exporter.ExportError):exporter.verify_artifact(self.wheel([(name,data)]), self.output)

    def test_wheel_symlink_is_rejected(self):
        self.export();path = self.wheel();entry = zipfile.ZipInfo('pokemon_red/link.py');entry.external_attr = (stat.S_IFLNK | 0o777) << 16
        with zipfile.ZipFile(path, 'a') as archive:archive.writestr(entry, 'target')
        with self.assertRaises(exporter.ExportError):exporter.verify_artifact(path, self.output)

    def test_tar_links_and_traversal_are_rejected_without_extraction(self):
        self.export()
        for name, kind in [('pkg/../outside.py', tarfile.REGTYPE), ('pkg/link.py', tarfile.SYMTYPE)]:
            path = self.base / 'bad.tar.gz'
            with tarfile.open(path, 'w:gz') as archive:
                entry = tarfile.TarInfo(name);entry.type = kind;entry.size = 1 if kind == tarfile.REGTYPE else 0
                archive.addfile(entry, io.BytesIO(b'x'))
            with self.subTest(name=name), self.assertRaises(exporter.ExportError):exporter.verify_artifact(path, self.output)
        self.assertFalse((self.base / 'outside.py').exists())

    def test_manifest_cannot_escape_source_root(self):
        for name in ('../outside.py', '/outside.py', 'a/../outside.py', 'a\\outside.py'):
            with self.subTest(name=name), self.assertRaises(exporter.ExportError):exporter.safe_name(name)

    def png(self,extra=b''):
        def chunk(tag,body):return struct.pack('>I',len(body))+tag+body+struct.pack('>I',zlib.crc32(tag+body)&0xffffffff)
        return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',1,1,8,2,0,0,0))+extra+chunk(b'IDAT',zlib.compress(b'\0\0\0\0'))+chunk(b'IEND',b'')

    def test_reviewed_screenshot_roundtrip_preserves_hashes(self):
        name='docs/screenshots/party.png';data=self.png();self.write(name,data)
        self.policy['files'].append(name);self.save_policy();self.export()
        self.assertEqual((self.output/name).read_bytes(),data);self.assertTrue(exporter.verify_export(self.output)['verified'])
        self.assertTrue(exporter.verify_artifact(self.wheel(),self.output)['verified'])
        changed=bytearray(data);changed[-1]^=1
        with self.assertRaises(exporter.ExportError):exporter.check_payload(name,bytes(changed))

    def test_binary_exception_cannot_admit_unreviewed_images_metadata_or_roms(self):
        data=self.png()
        for name,payload in [('docs/other.png',data),('Data/save.png',data),('docs/screenshots/party.png',b'ROM'),('docs/screenshots/party.png',data+b'private')]:
            with self.subTest(name=name),self.assertRaises(exporter.ExportError):exporter.check_payload(name,payload)
        tag=b'tEXt';body=b'private path';chunk=struct.pack('>I',len(body))+tag+body+struct.pack('>I',zlib.crc32(tag+body)&0xffffffff)
        with self.assertRaises(exporter.ExportError):exporter.check_payload('docs/screenshots/party.png',self.png(chunk))

    def test_sdist_supports_generated_metadata_in_src_layout(self):
        self.export();path = self.base / 'source.tar.gz'
        rows = [('pkg/'+name, data) for name, data in exporter.selection(self.output).items()]
        rows += [('pkg/src/pokedesk.egg-info/PKG-INFO', b'Name: pokedesk\n')]
        with tarfile.open(path, 'w:gz') as archive:
            for name, data in rows:
                entry = tarfile.TarInfo(name);entry.size = len(data);archive.addfile(entry, io.BytesIO(data))
        self.assertTrue(exporter.verify_artifact(path, self.output)['verified'])
