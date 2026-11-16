"""Queue ledger, publication failures and courier eligibility; no live saves."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,Mock
import tempfile,sys,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.acquisition import read_json,write_json
from pokemon_red.persistence import SaveSnapshot
from pokemon_red.item_delivery import (capacity_error,eligible_couriers,verify_template,
    apply_receipt,commit_delivery,recover_commits,file_hashes,DeliveryManager,change_job,quantity,PRODUCTS)

class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.id='a'*32;self.folder=self.root/'Sessions/item-delivery'/self.id;self.folder.mkdir(parents=True)
        self.row=dict(id=self.id,amount=3,requested=3,mode='add',delivered=0,status='running',created_at=1,stage='run',courier_uid='courier')
        write_json(self.folder/'job.json',self.row)
        self.op=self.root/'Sessions/operations'/('b'*32);self.op.mkdir(parents=True);write_json(self.op/'operation.json',dict(kind='delivery'))
        self.receipt=dict(delivery_job=self.id,sequence=1,quantity_before=2,quantity_after=3,courier_uid='courier',donor_uid='donor',seconds=20,operation_id=self.op.name)
    def test_capacity_is_items_pocket_and_999_limit(self):
        self.assertIsNone(capacity_error(dict(ready=True,items=[])))
        self.assertIsNotNone(capacity_error(dict(ready=False)))
        self.assertIsNotNone(capacity_error(dict(ready=True,items=[dict(id=14,pocket='items',quantity=999)])))
        rows=[dict(id=n+20,pocket='items',quantity=1) for n in range(42)]
        self.assertIsNotNone(capacity_error(dict(ready=True,items=rows)))
        rows[-1]=dict(id=14,pocket='items',quantity=998)
        self.assertIsNone(capacity_error(dict(ready=True,items=rows)))
    def test_courier_excludes_shiny_trade_evolution_egg_and_held_items(self):
        def mon(n,**kw):return dict(dict(uid=str(n),species_id=n,slot=1,level=5,checksum_valid=True,is_egg=False,shiny=False,held_item=0),**kw)
        party=[mon(19),mon(16,shiny=True),mon(21,held_item=14),mon(4,is_egg=True),mon(64),mon(95),mon(7,checksum_valid=False)]
        self.assertEqual([m['species_id'] for m in eligible_couriers(party,ROOT)],[19])
    def test_template_hashes_are_required(self):
        for item in PRODUCTS:self.assertTrue(verify_template(ROOT,item).is_dir())
        with self.assertRaises(ValueError):verify_template(self.root)
    def test_receipt_exactly_once_and_sequence_conflicts(self):
        self.assertEqual(apply_receipt(self.root,self.receipt)['delivered'],1)
        self.assertEqual(apply_receipt(self.root,self.receipt)['delivered'],1)
        with self.assertRaises(ValueError):apply_receipt(self.root,dict(self.receipt,operation_id='c'*32))
        with self.assertRaises(ValueError):apply_receipt(self.root,dict(self.receipt,sequence=3))
    def test_pause_requested_during_commit_survives_receipt(self):
        change_job(self.root,self.id,pause_requested=True)
        self.assertEqual(apply_receipt(self.root,self.receipt)['status'],'paused')
    def test_last_receipt_finishes_even_when_paused(self):
        change_job(self.root,self.id,amount=1,pause_requested=True)
        self.assertEqual(apply_receipt(self.root,self.receipt)['status'],'done')
    def test_recover_crash_after_main_publication_before_credit(self):
        snap=SaveSnapshot(b'new-state',b'new-sram',12,0)
        with patch('pokemon_red.item_delivery.apply_receipt',side_effect=OSError('power loss')):
            with self.assertRaises(OSError):commit_delivery(self.root,self.op,self.receipt,snap)
        self.assertEqual(read_json(self.folder/'job.json')['delivered'],0)
        recover_commits(self.root);recover_commits(self.root)
        self.assertEqual(read_json(self.folder/'job.json')['delivered'],1)
        self.assertEqual(len(list((self.folder/'receipts').glob('*.json'))),1)
    def test_failed_publish_is_not_credited(self):
        (self.root/'Data').mkdir();(self.root/'Data/FireRed.state').write_bytes(b'old-state');(self.root/'Data/FireRed.sav').write_bytes(b'old-sram')
        old=file_hashes(self.root/'Data')
        with patch('pokemon_red.item_delivery.publish_checkpoint',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):commit_delivery(self.root,self.op,self.receipt,SaveSnapshot(b'new',b'new',1,0))
        recover_commits(self.root)
        self.assertEqual(file_hashes(self.root/'Data'),old)
        self.assertEqual(read_json(self.folder/'job.json')['delivered'],0)
        self.assertEqual(read_json(self.op/'commit.json')['status'],'rolled_back')
    def test_unknown_save_blocks_replay(self):
        snap=SaveSnapshot(b'new',b'new',12,0)
        with patch('pokemon_red.item_delivery.apply_receipt',side_effect=OSError('crash')):
            with self.assertRaises(OSError):commit_delivery(self.root,self.op,self.receipt,snap)
        (self.root/'Data/FireRed.state').write_bytes(b'unrelated')
        recover_commits(self.root)
        row=read_json(self.folder/'job.json');self.assertTrue(row['recovery_pending']);self.assertEqual(row['delivered'],0)
        manager=DeliveryManager(SimpleNamespace(folder=self.root,operation=SimpleNamespace(active=False)))
        with self.assertRaises(ValueError):manager.start(self.id)
    def test_restart_does_not_start_or_discard_queue(self):
        manager=DeliveryManager(SimpleNamespace(folder=self.root))
        self.assertFalse(manager.enabled);self.assertEqual(manager.get(self.id)['status'],'paused')
        self.assertEqual(manager.get(self.id)['delivered'],0)

    def test_receipt_cannot_credit_a_different_item(self):
        before=(self.folder/'job.json').read_bytes()
        with self.assertRaises(ValueError):apply_receipt(self.root,dict(self.receipt,item_id=4))
        self.assertEqual((self.folder/'job.json').read_bytes(),before)

    def test_tm44_recovery_preserves_item_identity(self):
        change_job(self.root,self.id,item_id=332)
        receipt=dict(self.receipt,item_id=332)
        with patch('pokemon_red.item_delivery.apply_receipt',side_effect=OSError('crash')):
            with self.assertRaises(OSError):commit_delivery(self.root,self.op,receipt,SaveSnapshot(b'tm44',b'tm44',1,0))
        recover_commits(self.root);recover_commits(self.root)
        self.assertEqual(read_json(self.folder/'receipts/000001.json')['item_id'],332)
        self.assertEqual(read_json(self.folder/'job.json')['delivered'],1)

    def test_enqueued_items_and_targets_are_independent(self):
        (self.root/'templates').symlink_to(ROOT/'templates',target_is_directory=True)
        (self.root/'vendor').symlink_to(ROOT/'vendor',target_is_directory=True)
        mon=dict(uid='courier',species_id=19,slot=1,level=5,checksum_valid=True,is_egg=False,shiny=False,held_item=0)
        monitor=SimpleNamespace(folder=self.root,last_state=dict(party=[mon,dict(mon,uid='other',slot=2)]),game=object())
        manager=DeliveryManager(monitor)
        inv=dict(ready=True,items=[dict(id=332,quantity=3,pocket='tmhm'),dict(id=364,quantity=1,pocket='key'),dict(id=4,quantity=20,pocket='balls')])
        with patch('pokemon_red.player_inventory.read_player_inventory',return_value=inv):
            a=manager.enqueue(5,'add','courier',4);b=manager.enqueue(5,'target','courier',332)
            self.assertEqual((manager.get(a)['item_id'],manager.get(a)['amount']),(4,5))
            self.assertEqual((manager.get(b)['item_id'],manager.get(b)['amount']),(332,2))
            for requested,item in [(3,332),(980,4),(1,9999)]:
                with self.assertRaises(ValueError):manager.enqueue(requested,'target' if requested==3 else 'add','courier',item)

    def test_live_game_waits_for_durable_delivery_commit(self):
        from concurrent.futures import Future
        from pokemon_red.operations import MainOperation
        import hashlib
        data=self.op/'main/Data';data.mkdir(parents=True)
        for n in ('FireRed.state','FireRed.sav'):(data/n).write_bytes(n.encode())
        result=dict(self.receipt,verified=True,main_hashes=file_hashes(data))
        config=dict(delivery_job=self.id,sequence=1,courier_uid='courier')
        write_json(self.op/'operation.json',dict(kind='delivery',config=config))
        write_json(self.op/'result.json',result);write_json(self.op/'status.json',dict(status='ready'))
        future=Future();game=SimpleNamespace(frame=10,load_state=Mock(),capture_save=Mock())
        monitor=SimpleNamespace(folder=self.root,game=game,keys=set(),refresh_state=Mock(),update_panel=Mock(),submit_write=Mock(return_value=future))
        op=MainOperation(monitor);op.job=self.op;op.game=game;op.frame=10;op.kind='delivery';op.process=SimpleNamespace(poll=lambda:0)
        op.poll();game.load_state.assert_not_called();self.assertFalse(op.result['applied'])
        future.set_exception(OSError('disk full'));op.last_poll=0;op.poll()
        game.load_state.assert_not_called();self.assertFalse(op.result['applied']);self.assertFalse(op.active)

class InventoryUITests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from pokemon_red.engine import Game
        from pokemon_red.telemetry import read_state
        from pokemon_red.inventory_view import InventoryView
        self.root=tk.Tk();self.root.geometry('540x760')
        self.game=Game(ROOT);self.addCleanup(self.game.close);self.addCleanup(self.root.destroy)
        monitor=SimpleNamespace(folder=ROOT,game=self.game,last_state=read_state(self.game),operation=SimpleNamespace(active=False))
        from pokemon_red.player_inventory import read_player_inventory
        monitor.bag_snapshot=lambda:read_player_inventory(self.game)
        monitor.delivery=SimpleNamespace(current=None,jobs=lambda:[])
        self.view=InventoryView(SimpleNamespace(monitor=monitor),self.root);self.root.update()
    def test_all_item_icons_and_bilingual_search(self):
        from pokemon_red.item_catalog import item_icon
        for item in self.view.data:
            self.assertEqual(item_icon(self.root,ROOT,item).width(),48)
        self.view.rows=[dict(id=14,name='ANTIDOTE',quantity=4,pocket='items',pocket_name='Предметы',slot=0)]
        for q in ('анти','antidote'):
            self.view.query.set(q);self.assertEqual(len(self.view.table.get_children()),1)
            self.assertTrue(self.view.table.item(self.view.table.get_children()[0],'image'))
        self.view.query.set('пусто');self.assertEqual(self.view.table.get_children(),())
    def test_tabs_keep_search_and_amount_and_invalid_amount_disables_queue(self):
        self.view.query.set('анти');self.view.amount.set('100')
        for tab in ('pc','delivery','bag','delivery'):
            self.view.source.set(tab);self.view.select();self.root.update()
        self.assertEqual(self.view.query.get(),'');self.assertEqual(self.view.amount.get(),'100')
        self.view.source.set('bag');self.view.select();self.assertEqual(self.view.query.get(),'анти')
        self.view.source.set('delivery');self.view.select()
        for value in ('0','-1','1000','x'):
            self.view.amount.set(value);self.assertEqual(self.view.enqueue_button.cget('state'),'disabled')

    def test_item_selection_changes_count_icon_and_enqueued_item(self):
        manager=self.view.panel.monitor.delivery;manager.enqueue=Mock()
        self.view.courier_choices={'test':'courier'};self.view.courier.set('test')
        self.view.rows=[dict(id=4,quantity=20,pocket='balls'),dict(id=332,quantity=3,pocket='tmhm'),dict(id=364,quantity=1,pocket='key')]
        self.view.mode.set('target');self.view.amount.set('5')
        for item,current,exchanges in [(332,3,4),(4,20,0)]:
            self.view.delivery_item.set(PRODUCTS[item]['title']);self.view.calculate()
            self.assertEqual(self.view.selected_item(),item);self.assertIn(f'In bag: {current}',self.view.stock.cget('text'))
            self.assertIn(f'exchanges: {exchanges}',self.view.total.cget('text'))
            self.assertEqual(str(self.view.item_image.cget('image')),str(self.view.item_photo))
        self.view.delivery_item.set(PRODUCTS[332]['title'])
        self.view.enqueue();manager.enqueue.assert_called_once_with(5,'target','courier',332)

class PocketTests(unittest.TestCase):
    def test_counts_only_the_selected_items_bag_pocket(self):
        inv=dict(items=[dict(id=4,pocket='pc',quantity=99),dict(id=4,pocket='balls',quantity=7),dict(id=332,pocket='tmhm',quantity=2)])
        self.assertEqual(quantity(inv,4),7);self.assertEqual(quantity(inv,332),2);self.assertEqual(quantity(inv),0)
    def test_full_items_pocket_does_not_block_balls_or_tm44(self):
        inv=dict(ready=True,items=[dict(id=i+50,pocket='items',quantity=1) for i in range(42)])
        self.assertIsNotNone(capacity_error(inv,14));self.assertIsNone(capacity_error(inv,4));self.assertIsNone(capacity_error(inv,332))
    def test_each_provider_uses_its_own_pocket_and_limit(self):
        for item,info in PRODUCTS.items():
            rows=[dict(id=i+500,pocket=info['pocket'],quantity=1) for i in range(info['capacity'])]
            self.assertIsNotNone(capacity_error(dict(ready=True,items=rows),item))
            rows[-1]=dict(id=item,pocket=info['pocket'],quantity=998)
            self.assertIsNone(capacity_error(dict(ready=True,items=rows),item))
            rows[-1]['quantity']=999
            self.assertIsNotNone(capacity_error(dict(ready=True,items=rows),item))
    def test_first_tm_requires_key_item_space_for_case(self):
        rows=[dict(id=i+500,pocket='key',quantity=1) for i in range(30)]
        self.assertIsNotNone(capacity_error(dict(ready=True,items=rows),332))
        rows[-1]=dict(id=364,pocket='key',quantity=1)
        self.assertIsNone(capacity_error(dict(ready=True,items=rows),332))
    def test_first_tm_case_is_an_expected_native_change(self):
        from pokemon_red.item_delivery_worker import verify_round_trip
        state=dict(party=[],boxes=[],daycare=[]);before=dict(items=[])
        after=dict(items=[dict(id=332,pocket='tmhm',quantity=1),dict(id=364,pocket='key',quantity=1)])
        verify_round_trip(state,state,before,after,'unused',332)
        after['items'].append(dict(id=13,pocket='items',quantity=1))
        with self.assertRaises(RuntimeError):verify_round_trip(state,state,before,after,'unused',332)

if __name__=='__main__':unittest.main()
