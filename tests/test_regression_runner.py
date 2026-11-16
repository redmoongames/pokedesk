"""The gate must reject invalid samples, stale lifecycle data and unsafe reports."""
from pathlib import Path
from unittest.mock import Mock,patch
import copy
import json
import os
import signal
import subprocess
import sys
import tempfile
import traceback
import unittest

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
from regression.model import compare,summarize,terminal_snapshot,user_revocation,sha,atomic_json
from regression.runner import gate,validate_manifest,MANDATORY,child,finish,freeze,extra_samples


class PerformanceGateTests(unittest.TestCase):
    def test_quality_extension_retains_originals_and_uses_a_fixed_maximum(self):
        rows=[dict(case='rpc',speed=16,status='passed',seconds=t) for t in (1,1,1.4)]
        original=copy.deepcopy(rows);cases={'rpc':dict(id='rpc',performance='seconds')}
        extra=extra_samples(rows,cases,3)
        self.assertEqual([repeat for _,_,repeat in extra],list(range(3,9)))
        self.assertEqual(rows,original)
        self.assertEqual(extra_samples(rows,cases,9),[])
        rows[0]['status']='error';self.assertEqual(extra_samples(rows,cases,3),[])
    def test_large_slowdown_fails_but_noise_does_not(self):
        base=summarize([1.,1.01,.99])
        self.assertEqual(compare(summarize([1.3,1.31,1.29]),base)['status'],'regression')
        self.assertEqual(compare(summarize([1.01,.99,1.02]),base)['status'],'passed')
        self.assertEqual(compare(summarize([.7,.71,.69]),base)['status'],'passed')
    def test_short_or_unstable_measurements_never_become_a_pass(self):
        base=summarize([1,1,1])
        self.assertEqual(compare(summarize([1]),base)['status'],'insufficient_samples')
        self.assertEqual(compare(summarize([.1,1,2]),base)['status'],'unstable_measurement')
    def test_device_fixture_and_suite_versions_must_match(self):
        summary=dict(environment={'machine':'M1','suite':'a'},performance={'walk@16':summarize([1,1,1])})
        baseline=copy.deepcopy(summary)
        self.assertEqual(gate(summary,baseline)['status'],'passed')
        changed_core=copy.deepcopy(baseline);changed_core['environment']['core']='new-binary'
        self.assertEqual(gate(summary,changed_core)['status'],'passed')
        for field in ('machine','suite'):
            changed=copy.deepcopy(baseline);changed['environment'][field]='other'
            self.assertEqual(gate(summary,changed)['status'],'incompatible_baseline')
        baseline['performance'].clear()
        self.assertEqual(gate(summary,baseline)['status'],'incomplete_baseline')
    def test_instability_is_review_and_regression_is_failure(self):
        base=dict(environment={},performance={'x':summarize([1,1,1])})
        current=copy.deepcopy(base);current['performance']['x']=summarize([.1,1,2])
        self.assertEqual(gate(current,base)['status'],'needs_review')
        current['performance']['x']=summarize([2,2,2])
        self.assertEqual(gate(current,base)['status'],'failed')


class LifecycleTests(unittest.TestCase):
    def test_interrupted_diagnostic_publication_keeps_the_previous_complete_json(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'metrics.json';atomic_json(path,{'complete':1})
            with patch('pathlib.Path.replace',side_effect=OSError('interrupted')):
                with self.assertRaises(OSError):atomic_json(path,{'complete':2})
            self.assertEqual(json.loads(path.read_text()),{'complete':1})
    def test_quick_report_does_not_claim_a_variance_estimate(self):
        with tempfile.TemporaryDirectory() as folder:
            summary=dict(status='passed_partial',scope='partial',cases=[],performance={'walk':summarize([1.])})
            finish(summary,Path(folder))
            self.assertIn('CV=not estimated',(Path(folder)/'report.txt').read_text())
    def test_started_event_cannot_finish_a_case_using_an_old_idle_snapshot(self):
        self.assertFalse(terminal_snapshot(dict(status='idle',script=None,running=False),'case.py'))
        self.assertFalse(terminal_snapshot(dict(status='running',script='case.py',running=True),'case.py'))
        self.assertFalse(terminal_snapshot(dict(status='finished',script='other.py',running=False),'case.py'))
        self.assertTrue(terminal_snapshot(dict(status='finished',script='case.py',running=False),'case.py'))
    def test_window_shutdown_and_errors_are_not_user_takeover(self):
        frame=lambda name:traceback.FrameSummary('/test/gui.py',10,name,line='self.runtime.take_control(close=True)')
        for name in ('close','error'):self.assertFalse(user_revocation([frame(name)]))
        for name in ('take_control','emergency_stop','recover_input'):self.assertTrue(user_revocation([frame(name)]))


class ManifestTests(unittest.TestCase):
    def test_source_snapshot_contains_the_real_shutdown_test_launcher(self):
        with tempfile.TemporaryDirectory() as a,tempfile.TemporaryDirectory() as b:
            project=Path(a);target=Path(b)
            for name in ('src','tests','Bots','tools','native','vendor','assets','templates','runtime','Data','Pokemon.app/Contents/MacOS'):(project/name).mkdir(parents=True,exist_ok=True)
            (project/'Data/FireRed.gba').write_bytes(b'rom');(project/'src/example.py').write_text('original')
            (project/'Run.command').write_text('launcher');(project/'main.py').write_text('main')
            (project/'Pokemon.app/Contents/MacOS/Pokemon').write_bytes(b'binary')
            freeze(project,target)
            self.assertEqual((target/'Run.command').read_text(),'launcher')
            self.assertTrue((target/'Pokemon.app/Contents/MacOS/Pokemon').is_file())
            (project/'src/example.py').write_text('concurrent edit')
            self.assertEqual((target/'src/example.py').read_text(),'original')
    def fixture(self, root):
        for name in ('Data','native','tests/fixtures/fire_red'):(root/name).mkdir(parents=True,exist_ok=True)
        (root/'Data/FireRed.gba').write_bytes(b'rom');(root/'native/libpokemon.dylib').write_bytes(b'core')
        f=root/'tests/fixtures/fire_red/a.state';f.write_bytes(b'fixture')
        cases=[dict(id=i,kind=i.replace('-','_'),fixture='a',expected_status={'learning-attention':'attention','takeover':'stopped'}.get(i,'finished'),
                    performance='move_accept_seconds' if i=='battle' else 'seconds' if i in ('walk','menu','rpc','portals','complex-travel','heal','learning') else None) for i in MANDATORY]
        return dict(schema=2,rom_sha256=sha(root/'Data/FireRed.gba'),core_sha256=sha(root/'native/libpokemon.dylib'),
                    fixtures={'a':dict(file='a.state',sha256=sha(f),initial_fingerprint='f'*64)},cases=cases)
    def test_missing_corrupt_or_escaping_fixtures_are_errors(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);manifest=self.fixture(root);validate_manifest(root,manifest)
            for change in ('missing','corrupt','escape','duplicate','metric','kind','outcome'):
                m=copy.deepcopy(manifest)
                if change=='missing':m['cases'].pop()
                if change=='corrupt':m['fixtures']['a']['sha256']='wrong'
                if change=='escape':m['fixtures']['a']['file']='../../../Data/FireRed.gba'
                if change=='duplicate':m['cases'].append(m['cases'][0])
                if change=='metric':next(c for c in m['cases'] if c['id']=='walk')['performance']=None
                if change=='kind':next(c for c in m['cases'] if c['id']=='trap')['kind']='rpc'
                if change=='outcome':next(c for c in m['cases'] if c['id']=='learning-attention')['expected_status']='finished'
                with self.subTest(change=change),self.assertRaises(AssertionError):validate_manifest(root,m)


class ProcessCleanupTests(unittest.TestCase):
    def test_interrupt_terminates_the_owned_process_group(self):
        process=Mock(pid=123);process.wait.side_effect=[KeyboardInterrupt(),0]
        with tempfile.TemporaryDirectory() as folder,patch('regression.runner.subprocess.Popen',return_value=process),patch('regression.runner.os.killpg') as kill:
            with self.assertRaises(KeyboardInterrupt):child(['test'],Path(folder)/'log',1)
            kill.assert_called_once_with(123,signal.SIGKILL)
    def test_timeout_kills_a_real_worker_and_its_grandchild(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);pidfile=root/'pid';script=root/'worker.py'
            script.write_text("import subprocess,sys,time\nfrom pathlib import Path\np=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'])\nPath(sys.argv[1]).write_text(str(p.pid))\ntime.sleep(30)\n")
            with self.assertRaises(subprocess.TimeoutExpired):child([sys.executable,str(script),str(pidfile)],root/'log',.5)
            self.assertTrue(pidfile.exists());pid=int(pidfile.read_text())
            status=subprocess.run(['/bin/ps','-p',str(pid),'-o','stat='],capture_output=True,text=True).stdout.strip()
            self.assertTrue(not status or status.startswith('Z'),status)


if __name__=='__main__':unittest.main()
