"""Slot lifecycle, cancellation and exclusive main-operation safeguards."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,Mock
from concurrent.futures import Future
import sys,tempfile,unittest,json,time,hashlib
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.acquisition import write_json,read_json,AcquisitionManager,job_active
from pokemon_red.hunt_board import HuntBoard
from pokemon_red.operations import MainOperation

class SlotsTests(unittest.TestCase):
    def test_four_slots_migrate_ready_donor_and_allow_other_assignments(self):
        with tempfile.TemporaryDirectory() as td:
            project=Path(td);folder=project/'Sessions/acquisition'/('a'*32);folder.mkdir(parents=True)
            config=dict(species_id=1,shiny=True,train=False,target_level=10)
            write_json(folder/'job.json',dict(id='a'*32,config=config,created_at=1));write_json(folder/'status.json',dict(status='ready',pokemon=dict(uid='shiny'),transfer_ready=True))
            board=HuntBoard(project);self.assertEqual(len(board.data['slots']),4);self.assertEqual(board.row(0)['status'],'ready')
            board.assign(1,dict(species_id=7));self.assertEqual(HuntBoard(project).slot(1)['config']['species_id'],7)
            with self.assertRaises(ValueError):board.start(0)
            with self.assertRaises(ValueError):board.slot(4)
    def test_cancel_preserves_files_and_transferred_cannot_resume(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);folder=root/'Sessions/acquisition'/('b'*32);folder.mkdir(parents=True)
            write_json(folder/'job.json',{});write_json(folder/'status.json',dict(status='paused'));(folder/'important.state').write_bytes(b'found')
            manager=AcquisitionManager(root);manager.cancel('b'*32)
            self.assertEqual(read_json(folder/'status.json')['status'],'cancelled');self.assertEqual((folder/'important.state').read_bytes(),b'found')
            write_json(folder/'status.json',dict(status='transferred'))
            with self.assertRaises(ValueError):manager.resume('b'*32)
            with self.assertRaises(ValueError):manager.job('../escape')
    def test_active_assignment_cannot_be_replaced(self):
        with tempfile.TemporaryDirectory() as td:
            board=HuntBoard(Path(td));board.assign(0,dict(species_id=1))
            with patch.object(board,'row',return_value=dict(status='searching',pid=123)),patch('pokemon_red.acquisition.os.kill'):
                with self.assertRaises(ValueError):board.assign(0,dict(species_id=4))
            self.assertEqual(board.slot(0)['config']['species_id'],1)

class OperationTests(unittest.TestCase):
    def test_concurrent_begin_does_not_cancel_current_operation(self):
        monitor=SimpleNamespace(folder=ROOT);operation=MainOperation(monitor);operation.job=Path('/active')
        with self.assertRaises(ValueError):operation.begin('local',{})
        self.assertEqual(operation.job,Path('/active'))
    def test_changed_main_frame_rejects_worker_result_before_load(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);job=root/'Sessions/operations'/('c'*32);job.mkdir(parents=True)
            write_json(job/'operation.json',dict(kind='local'));write_json(job/'status.json',dict(status='ready'));write_json(job/'result.json',{})
            game=SimpleNamespace(frame=20,load_state=Mock());monitor=SimpleNamespace(folder=root,game=game,paused=True,keys=set(),update_panel=Mock())
            operation=MainOperation(monitor);operation.job=job;operation.game=game;operation.frame=10;operation.process=SimpleNamespace(poll=lambda:0)
            operation.poll();game.load_state.assert_not_called();self.assertFalse(operation.result['applied']);self.assertIn('изменилась',operation.result['stage'])
    def test_invalid_result_hash_does_not_replace_main_game(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);job=root/'Sessions/operations'/('d'*32);(job/'main/Data').mkdir(parents=True)
            write_json(job/'operation.json',dict(kind='local'));write_json(job/'status.json',dict(status='ready'));write_json(job/'result.json',dict(main_hashes={'FireRed.state':'wrong','FireRed.sav':'wrong'}));(job/'main/Data/FireRed.state').write_bytes(b'bad')
            game=SimpleNamespace(frame=10,load_state=Mock());monitor=SimpleNamespace(folder=root,game=game,paused=True,keys=set(),update_panel=Mock())
            operation=MainOperation(monitor);operation.job=job;operation.game=game;operation.frame=10;operation.process=SimpleNamespace(poll=lambda:0)
            operation.poll();game.load_state.assert_not_called();self.assertFalse(operation.result['applied'])
if __name__=='__main__':unittest.main()
