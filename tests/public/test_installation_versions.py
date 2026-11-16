"""Immutable payloads, lazy imports and version contracts without game assets."""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from pokemon_red import installation_versions as versions
from pokemon_red.paths import session_paths,bind_installation,_resolve,InstallationPaths


class InstallationVersionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve();self.source=self.root/'app';self.store=self.root/'versions'
        for name in ('src','native','vendor','assets','runtime','Bots'):(self.source/name).mkdir(parents=True)
        (self.source/'src/helper.py').write_text('VALUE = 1\n')
        (self.source/'native/core.dylib').write_bytes(b'core-one')
        (self.source/'vendor/rules.json').write_text('{"version":1}')
        (self.source/'main.py').write_text('print("app")\n')

    def prepare(self):return versions.prepare_installation(self.source,self.store)

    def test_source_updates_do_not_change_code_core_reference_or_runtime(self):
        (self.source/'runtime/lib.txt').write_text('old-runtime')
        (self.source/'Data').mkdir();(self.source/'Data/FireRed.state').write_bytes(b'private')
        first=self.prepare()
        for relative in ('src/helper.py','native/core.dylib','vendor/rules.json','runtime/lib.txt'):
            original=(first.root/relative).read_bytes();(self.source/relative).write_bytes(b'updated')
            self.assertEqual((first.root/relative).read_bytes(),original)
            self.assertNotEqual((first.root/relative).stat().st_ino,(self.source/relative).stat().st_ino)
        self.assertFalse((first.root/'Data').exists());versions.verify_installation(first)
        second=self.prepare();self.assertNotEqual(first.id,second.id)
        self.assertEqual((first.root/'src/helper.py').read_text(),'VALUE = 1\n')

    def test_worker_lazy_imports_still_use_the_original_version(self):
        script='from pathlib import Path\nimport sys,time\nsys.path.insert(0,str(Path(__file__).parent/"src"))\nwhile not Path(sys.argv[1]).exists(): time.sleep(.01)\nimport helper\nprint(helper.VALUE,flush=True)\n'
        (self.source/'main.py').write_text(script);version=self.prepare();go=self.root/'go'
        child=subprocess.Popen([sys.executable,'-I','-B',str(version.root/'main.py'),str(go)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            (self.source/'src/helper.py').write_text('VALUE = 2\n');go.touch()
            out,error=child.communicate(timeout=5)
            self.assertEqual(child.returncode,0,error);self.assertEqual(out.strip(),'1')
        finally:
            if child.poll() is None:child.kill();child.communicate()

    def test_internal_runtime_links_are_preserved_and_external_links_rejected(self):
        (self.source/'runtime/lib.txt').write_text('runtime')
        (self.source/'runtime/current').symlink_to('lib.txt')
        version=self.prepare();self.assertEqual((version.root/'runtime/current').read_text(),'runtime')
        (self.source/'runtime/escape').symlink_to(self.root/'outside')
        with self.assertRaises(ValueError):self.prepare()

    def test_mutation_during_copy_never_publishes_a_mixed_version(self):
        first=self.prepare();(self.source/'src/helper.py').write_text('VALUE = 2\n')
        real=versions._copy;changed=False
        def mutate(source,target):
            nonlocal changed
            real(source,target)
            if not changed:
                changed=True;(self.source/'src/helper.py').write_text('VALUE = 3\n')
        with patch.object(versions,'_copy',side_effect=mutate),self.assertRaises(ValueError):self.prepare()
        versions.verify_installation(first)
        self.assertEqual([p.name for p in self.store.iterdir()],[first.id])

    def test_corrupt_reused_payload_is_rejected(self):
        version=self.prepare();path=version.root/'native/core.dylib';path.chmod(0o644);path.write_bytes(b'bad')
        with self.assertRaises(ValueError):self.prepare()

    def test_whole_portable_tree_can_move(self):
        self.store=self.source/'Sessions/installations';version=self.prepare()
        job=self.source/'Sessions/operations/one'
        with patch.object(versions,'version_for_job',return_value=version):identity=versions.pin_job(job,self.source,'test')
        moved=self.root/'moved';self.source.rename(moved);job=moved/'Sessions/operations/one'
        self.assertEqual(session_paths(job).installation.root,moved/'Sessions/installations'/version.id)
        self.assertEqual(versions.job_identity(job),identity)

    def test_version_and_run_mismatch_are_rejected(self):
        expected={'release_id':'a'*64,'run_id':'one'}
        versions.require_result(expected,{'_execution':expected})
        for value in ({},{'_execution':dict(expected,release_id='b'*64)},{'_execution':dict(expected,run_id='other')}):
            with self.assertRaises(ValueError):versions.require_result(expected,value)

    def test_snapshot_inherits_into_children_and_checks_actual_worker_version(self):
        version=self.prepare();job=self.root/'profile/Sessions/one'
        self.assertIsNone(versions.job_identity(job))
        with patch.object(versions,'version_for_job',return_value=version):identity=versions.pin_job(job,self.root/'profile','test')
        child=job/'main';bind_installation(child,job)
        self.assertEqual(session_paths(child).installation.release_id,version.id)
        with patch.object(versions,'loaded_id',return_value=version.id):self.assertEqual(versions.validate_worker(child),identity)
        with patch.object(versions,'loaded_id',return_value='b'*64),self.assertRaises(ValueError):versions.validate_worker(child)

    def test_custom_script_and_late_imported_helpers_are_detached(self):
        version=self.prepare();profile=self.root/'profile';profile.mkdir()
        script=profile/'bot.py';script.write_text('import helper\ndef run(bot): pass\n')
        (profile/'helper.py').write_text('VALUE=1\n')
        with patch.object(versions,'version_for_job',return_value=version):prepared=versions.prepare_bot(profile,script)
        (profile/'helper.py').write_text('VALUE=2\n');script.write_text('raise RuntimeError()\n')
        self.assertEqual((prepared.script.parent/'helper.py').read_text(),'VALUE=1\n')
        self.assertIn('def run',prepared.script.read_text())
        with patch.object(versions,'loaded_id',return_value=version.id):versions.validate_bot(prepared.job)

    def test_active_process_uses_pinned_resources_and_rejects_foreign_workspace(self):
        version=self.prepare();profile=self.root/'profile';bind_installation(profile,self.source,kind='profile',library=profile)
        job=profile/'Sessions/one'
        with patch.object(versions,'version_for_job',return_value=version):versions.pin_job(job,profile,'test')
        from pokemon_red import paths
        try:
            with patch.object(paths,'_process_installation',InstallationPaths(version.root,version.id,self.source)):
                _resolve.cache_clear();self.assertEqual(session_paths(profile).installation.root,version.root)
                record=json.loads((job/paths.LAYOUT_FILE).read_text());record['release_id']='f'*64;(job/paths.LAYOUT_FILE).write_text(json.dumps(record));_resolve.cache_clear()
                with self.assertRaises(ValueError):session_paths(job)
        finally:_resolve.cache_clear()

    def test_bounded_preparation_queue_and_completion_notification(self):
        gate=threading.Event();notified=threading.Event();futures=[]
        try:
            for _ in range(8):futures.append(versions.submit_preparation(lambda:gate.wait(5),notify=notified.set))
            with self.assertRaises(RuntimeError):versions.submit_preparation(lambda:None)
        finally:
            gate.set()
            for future in futures:future.result(5)
        self.assertTrue(notified.wait(1))

    def test_old_job_launch_version_does_not_activate_in_the_new_host(self):
        first=self.prepare();job=self.root/'profile/Sessions/one'
        with patch.object(versions,'version_for_job',return_value=first):versions.pin_job(job,self.root/'profile','test')
        (self.source/'src/helper.py').write_text('VALUE=2\n');second=self.prepare()
        from pokemon_red import paths
        try:
            with patch.object(paths,'_process_installation',InstallationPaths(second.root,second.id,self.source)):
                _resolve.cache_clear();self.assertEqual(versions.bound_version(job),first)
                self.assertEqual(versions.bound_version(job).environment()['POKEDESK_RELEASE_ID'],first.id)
                with self.assertRaises(ValueError):session_paths(job)
        finally:_resolve.cache_clear()

    def test_readonly_response_checks_the_actual_process_version(self):
        with patch.object(versions,'loaded_id',return_value='a'*64):
            packet=versions.versioned_response({'plan':1});versions.require_response(packet)
            self.assertEqual(versions.unwrap_response(versions.wrap_response([1,2])),[1,2])
            with self.assertRaises(ValueError):versions.require_response({'_installation':'b'*64})
            with self.assertRaises(ValueError):versions.unwrap_response([1,2])

    def test_bootstrap_keeps_legacy_profile_data_and_uses_its_actual_launcher_code(self):
        profile=self.root/'legacy';profile.mkdir();version=self.prepare()
        with patch.object(versions,'loaded_version',return_value=None),patch.object(versions,'prepare_installation',return_value=version) as prepare,patch.object(versions.os,'execve',side_effect=RuntimeError('exec')) as execute:
            with self.assertRaisesRegex(RuntimeError,'exec'):versions.bootstrap_process(profile,['--watch'])
        self.assertEqual(prepare.call_args.args[0],Path(versions.__file__).resolve().parents[2])
        executable,arguments,environment=execute.call_args.args
        self.assertEqual(arguments[-2:],['--root',str(profile)])
        self.assertEqual(environment['POKEDESK_RELEASE_ID'],version.id)
        self.assertEqual(Path(arguments[3]),version.root/'main.py')
