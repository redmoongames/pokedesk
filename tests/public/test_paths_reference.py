"""Portable path and read-only reference contracts without ROM/Tk/native assets."""
from pathlib import Path
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from pokemon_red.paths import LAYOUT_FILE, session_paths, bind_installation, resource
from pokemon_red.reference_pack import load_reference, _read
from pokemon_red.database import connect


def synthetic_pack(installation, game='firered'):
    path=installation/'vendor/catalog/packs'/f'{game}.json';path.parent.mkdir(parents=True,exist_ok=True)
    data=dict(species={'25':{'name':'PIKACHU'}},moves={},abilities={},routes={})
    path.write_text(json.dumps(dict(schema=1,game=game,source_version='a'*64,data=data)))
    return path


class PortablePathsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name).resolve()

    def test_legacy_resolution_is_read_only_and_keeps_data_in_place(self):
        paths=session_paths(self.root)
        self.assertEqual(paths.installation.root,self.root)
        self.assertEqual(paths.profile.journal,self.root/'Data/history.sqlite3')
        self.assertEqual(paths.workspaces.root,self.root/'Sessions')
        self.assertEqual(list(self.root.iterdir()),[])

    def test_profile_and_nested_job_use_installation_but_separate_data(self):
        install=self.root/'app';install.mkdir();library=self.root/'playthroughs'
        bind_installation(library,install,kind='profile',library=library)
        # A library can live beside a read-only installation; explicitly making
        # it the source preserves its own profile data for descendants.
        profile=library/'Profiles/one';bind_installation(profile,library,kind='profile')
        job=profile/'Sessions/operations/one/main';paths=bind_installation(job,profile)
        self.assertEqual(paths.installation.root,install)
        self.assertEqual(paths.profile.data,job/'Data')
        self.assertEqual(paths.library,library)
        self.assertEqual(resource(job,'native/libpokemon.dylib'),install/'native/libpokemon.dylib')
        self.assertNotEqual(session_paths(profile).profile.data,paths.profile.data)
        self.assertFalse((profile/'src').exists());self.assertFalse((job/'vendor').exists())

    def test_relative_layout_survives_copy_and_original_removal(self):
        portable=self.root/'portable';install=portable/'app';install.mkdir(parents=True)
        synthetic_pack(install);profile=portable/'Profiles/one';bind_installation(profile,install,kind='profile')
        (profile/'Data').mkdir();(profile/'Data/FireRed.state').write_bytes(b'personal-save')
        job=profile/'Sessions/one/main';bind_installation(job,profile)
        moved=self.root/'moved';shutil.copytree(portable,moved);shutil.rmtree(portable)
        target=moved/'Profiles/one'
        self.assertEqual(session_paths(target).installation.root,moved/'app')
        self.assertEqual((target/'Data/FireRed.state').read_bytes(),b'personal-save')
        self.assertEqual(load_reference(target)['species']['25']['name'],'PIKACHU')
        self.assertEqual(session_paths(target/'Sessions/one/main').installation.root,moved/'app')
        marker=json.loads((target/LAYOUT_FILE).read_text())
        self.assertFalse(Path(marker['installation']).is_absolute())

    def test_invalid_layout_fails_instead_of_reading_another_installation(self):
        for record in (None, [], 'bad', {'schema':2}, {'schema':1,'kind':'profile','installation':str(self.root)}):
            (self.root/LAYOUT_FILE).write_text(json.dumps(record))
            with self.assertRaises(ValueError):session_paths(self.root)

    def test_resource_cannot_escape_its_installation(self):
        for name in ('../Data/save',str(self.root/'save')):
            with self.assertRaises(ValueError):resource(self.root,name)

    def test_old_uuid_profile_and_nested_job_inherit_library_without_migration(self):
        (self.root/'Data').mkdir();synthetic_pack(self.root)
        profile=self.root/'Profiles'/('a'*32);(profile/'Data').mkdir(parents=True)
        (profile/'Data/FireRed.state').write_bytes(b'keep')
        job=profile/'Sessions/operations/old/main';(job/'Data').mkdir(parents=True)
        for root in (profile,job):
            paths=session_paths(root)
            self.assertEqual(paths.installation.root,self.root)
            self.assertEqual(paths.library,self.root)
            self.assertEqual(paths.profile.data,root/'Data')
            self.assertFalse((root/LAYOUT_FILE).exists())
            self.assertTrue(load_reference(root)['species'])
        self.assertEqual((profile/'Data/FireRed.state').read_bytes(),b'keep')


class ReferenceIsolationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name).resolve();_read.cache_clear()
        self.pack=synthetic_pack(self.root)

    def test_read_never_creates_profile_data_or_opens_sqlite(self):
        with patch('sqlite3.connect',side_effect=AssertionError('reference must not open SQLite')):
            self.assertEqual(load_reference(self.root)['species']['25']['name'],'PIKACHU')
        self.assertFalse((self.root/'Data').exists())

    def test_exclusive_journal_writer_does_not_block_a_cold_reference_read(self):
        db=connect(self.root);db.execute('CREATE TABLE legacy_reference (value TEXT)')
        db.execute("INSERT INTO legacy_reference VALUES('keep')");db.commit()
        before=(self.root/'Data/history.sqlite3').read_bytes();db.execute('BEGIN EXCLUSIVE')
        try:
            _read.cache_clear();self.assertTrue(load_reference(self.root)['species'])
        finally:db.rollback();db.close()
        self.assertEqual(before,(self.root/'Data/history.sqlite3').read_bytes())
        with sqlite3.connect(self.root/'Data/history.sqlite3') as db:
            self.assertEqual(db.execute('SELECT value FROM legacy_reference').fetchone()[0],'keep')

    def test_missing_pack_does_not_build_or_touch_the_journal(self):
        self.pack.unlink()
        with self.assertRaises(FileNotFoundError):load_reference(self.root)
        self.assertFalse((self.root/'Data').exists())
        self.assertFalse(self.pack.exists())

    def test_pack_is_shared_readonly_between_profiles(self):
        a=self.root/'Profiles/a';b=self.root/'Profiles/b'
        bind_installation(a,self.root,kind='profile');bind_installation(b,self.root,kind='profile')
        first=load_reference(a);second=load_reference(b)
        self.assertIs(first,second)
        with self.assertRaises(TypeError):first['species']['25']['name']='bad'
        self.assertEqual(second['species']['25']['name'],'PIKACHU')

    def test_wrong_edition_or_schema_is_rejected(self):
        for field,value in (('game','leafgreen'),('schema',999)):
            record=json.loads(self.pack.read_text());record[field]=value;self.pack.write_text(json.dumps(record));_read.cache_clear()
            with self.assertRaises(ValueError):load_reference(self.root)

    def test_reference_works_with_readonly_installation(self):
        profile=self.root/'Profiles/one';bind_installation(profile,self.root,kind='profile')
        self.pack.chmod(0o444);self.pack.parent.chmod(0o555)
        try:
            _read.cache_clear();self.assertTrue(load_reference(profile)['species'])
            db=connect(profile);db.close()
            self.assertTrue(session_paths(profile).profile.journal.is_file())
        finally:self.pack.parent.chmod(0o755);self.pack.chmod(0o644)
