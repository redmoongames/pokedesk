"""Immutable publication reuses unchanged boxes without leaking owner data."""
from copy import deepcopy
import json
import unittest
from pokemon_red.runtime_data import InventoryPublisher, freeze


class InventoryPublicationTests(unittest.TestCase):
    def inventory(self):
        return dict(ready=True,game='firered',storage_revision='one',party=[dict(uid='party',hp=10)],
                    boxes=[dict(uid='box',moves=[dict(id=33,current_pp=10)],stats={'speed':20})])

    def test_party_changes_reuse_the_exact_box_objects(self):
        publisher=InventoryPublisher();source=self.inventory();first=publisher.publish(source,1)
        source['party'][0]['hp']=3;second=publisher.publish(source,1)
        self.assertIs(first['boxes'],second['boxes']);self.assertEqual(publisher.rebuilds,1)
        self.assertEqual(first['party'][0]['hp'],10);self.assertEqual(second['party'][0]['hp'],3)

    def test_storage_edits_and_same_frame_generation_changes_invalidate(self):
        publisher=InventoryPublisher();source=self.inventory();first=publisher.publish(source,1)
        source['storage_revision']='two';source['boxes'][0]['moves'][0]['current_pp']=4
        second=publisher.publish(source,1);third=publisher.publish(source,2)
        self.assertIsNot(first['boxes'],second['boxes']);self.assertIsNot(second['boxes'],third['boxes'])
        self.assertEqual(first['boxes'][0]['moves'][0]['current_pp'],10)

    def test_nested_mutations_cannot_poison_other_views_or_owner(self):
        source=self.inventory();snapshot=InventoryPublisher().publish(source,1)
        actions=[lambda:snapshot.update(ready=False),lambda:snapshot['boxes'].append({}),
                 lambda:snapshot['boxes'][0].update(uid='wrong'),
                 lambda:snapshot['boxes'][0]['moves'][0].update(current_pp=0),
                 lambda:snapshot['boxes'][0]['stats'].clear()]
        for action in actions:
            with self.assertRaises(TypeError):action()
        self.assertEqual(source['boxes'][0]['uid'],'box')

    def test_explicit_deepcopy_is_mutable_and_json_protocol_remains_compatible(self):
        snapshot=InventoryPublisher().publish(self.inventory(),1);copy=deepcopy(snapshot)
        copy['boxes'][0]['moves'][0]['current_pp']=0
        self.assertEqual(snapshot['boxes'][0]['moves'][0]['current_pp'],10)
        self.assertEqual(json.loads(json.dumps(snapshot))['boxes'][0]['uid'],'box')
        self.assertIsInstance(snapshot,dict);self.assertIsInstance(snapshot['boxes'],list)

    def test_missing_revision_never_silently_reuses_old_records(self):
        source=self.inventory();source.pop('storage_revision');publisher=InventoryPublisher()
        first=publisher.publish(source,1);source['boxes'][0]['uid']='other'
        second=publisher.publish(source,1);self.assertEqual(second['boxes'][0]['uid'],'other')
        self.assertIsNot(first['boxes'],second['boxes'])

    def test_metadata_and_daycare_are_detached(self):
        source=self.inventory();source['field_badges']=[1];daycare=[dict(uid='child')]
        value=InventoryPublisher().publish(source,1,daycare);daycare[0]['uid']='changed';source['field_badges'].append(2)
        self.assertEqual(value['daycare'][0]['uid'],'child');self.assertEqual(value['field_badges'],[1])


class HistoryViewGenerationTests(unittest.TestCase):
    def test_cancelled_read_can_retry_in_the_same_generation(self):
        from concurrent.futures import Future, CancelledError
        from types import SimpleNamespace
        from pokemon_red.runtime_views import HistoryView
        requests=[]
        def submit(*_):
            future=Future();requests.append(future);return future
        monitor=SimpleNamespace(generation=1,ready=True,model=SimpleNamespace(history={}),runtime=SimpleNamespace(submit=submit),watch=lambda *a:None)
        view=HistoryView(monitor);view.comparisons();requests[0].set_exception(CancelledError('cancel'))
        view.comparisons();self.assertEqual(len(requests),2)

    def test_old_completion_cannot_replace_new_generation_cache_or_request(self):
        from concurrent.futures import Future
        from types import SimpleNamespace
        from pokemon_red.runtime_views import HistoryView
        requests=[];callbacks=[];errors=[]
        def submit(*_):
            future=Future();requests.append(future);return future
        monitor=SimpleNamespace(generation=1,ready=True,model=SimpleNamespace(history={'completed_revision':1}),
            runtime=SimpleNamespace(submit=submit),watch=lambda f,done,fail:callbacks.append((done,fail)),error=lambda *a,**k:errors.append(a))
        view=HistoryView(monitor);view.comparisons();monitor.generation=2;view.comparisons()
        callbacks[0][0](['old']);callbacks[0][1](RuntimeError('old failure'))
        self.assertFalse(view.cache);self.assertIs(view.inflight[('comparisons',())],requests[1]);self.assertFalse(errors)
        callbacks[1][0](['new']);self.assertEqual(view.comparisons(),['new'])


class StorageRevisionTests(unittest.TestCase):
    def test_revision_tracks_contents_and_trainer_but_not_selected_box(self):
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import patch
        import tempfile
        from pokemon_red.models import read_inventory
        storage=bytearray(0x83d0);trainer=bytearray(b'ABCD');pointer=0x02010000;sb2=0x02001000
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        game=SimpleNamespace(root=Path(temporary.name),frame=1,read_bytes=lambda address,count:bytes(storage) if address==pointer else bytes(trainer))
        with patch('pokemon_red.telemetry.read_state',return_value={'ready':True,'party':[]}),patch('pokemon_red.telemetry.symbols',return_value={}),patch('pokemon_red.game_layout.storage',return_value=pointer),patch('pokemon_red.game_layout.save_block',return_value=sb2):
            first=read_inventory(game);storage[0]=4;second=read_inventory(game)
            self.assertEqual(first['storage_revision'],second['storage_revision']);self.assertEqual(second['current_box'],4)
            storage[100]=1;third=read_inventory(game)
            self.assertNotEqual(second['storage_revision'],third['storage_revision'])
            trainer[0]=0;fourth=read_inventory(game)
            self.assertNotEqual(third['storage_revision'],fourth['storage_revision'])
