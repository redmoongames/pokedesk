import unittest,tempfile,json,hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from pokemon_red.engine import ROOT
from pokemon_red.item_catalog import items
from pokemon_red.inventory_library import holdings,library_rows,sort_rows
from pokemon_red.item_sources import availability,can_prepare,provider,register
from pokemon_red.acquisition import write_json

class LibraryTests(unittest.TestCase):
 def test_reference_complete_original_icons_and_no_placeholders(self):
  data=items(ROOT);raw=json.loads((ROOT/'vendor/catalog/item-catalog.json').read_text())['items']
  self.assertEqual(set(data),{r['id'] for r in raw if r['id'] and '?' not in r['name']})
  for i,row in data.items():
   self.assertTrue((ROOT/f'assets/items/{i}.png').is_file(),i);self.assertGreater(len(row['description']),80,i)
   self.assertTrue(any('а'<=c<='я' for c in row['title']) or 289<=i<=346,i)
 def test_machines_use_actual_move_and_russian_gen3_effect(self):
  row=items(ROOT)[332];self.assertEqual(row['move_id'],156);self.assertIn('два хода',row['description']);self.assertIn('Психический',row['description']);self.assertIn('расходуется',row['description'])
  self.assertIn('не расходуется',items(ROOT)[339]['description'])
 def test_legacy_mechanics_are_explicit(self):
  data=items(ROOT)
  for i,needle in [(142,'30 HP'),(202,'только специальную'),(153,'в FireRed не работает'),(185,'поздних поколениях'),(220,'5%')]:self.assertIn(needle,data[i]['description'])
 def test_all_owned_locations_count_without_double_counting_party_cache(self):
  rows=[dict(id=4,pocket='balls',quantity=5),dict(id=4,pocket='pc',quantity=3)]
  inv=dict(party=[dict(held_item=4)],boxes=[dict(held_item=4)],daycare=[dict(held_item=4)])
  state=dict(party=[dict(held_item=4),dict(held_item=4,checksum_valid=False)])
  self.assertEqual(holdings(rows,inv,state)[4],dict(bag=5,pc=3,party=1,boxes=1,daycare=1,total=11))
 def test_zero_stock_visible_and_nontransferable_hoenn_keys_hidden(self):
  rows=library_rows(items(ROOT),{})
  self.assertIn(4,{r['id'] for r in rows});self.assertEqual(next(r['quantity'] for r in rows if r['id']==4),0)
  self.assertNotIn(259,{r['id'] for r in rows});self.assertNotIn(346,{r['id'] for r in rows})
  self.assertIn(259,{r['id'] for r in library_rows(items(ROOT),{259:dict(total=1)})})
 def test_sort_count_and_name(self):
  data={1:dict(title='Б'),2:dict(title='А')};rows=[dict(id=1,quantity=1),dict(id=2,quantity=5)]
  self.assertEqual([r['id'] for r in sort_rows(rows,data)],[2,1]);self.assertEqual([r['id'] for r in sort_rows(rows,data,'count',True)],[2,1])
 def test_prepare_needs_one_bag_item_not_pc_or_held(self):
  self.assertIsNone(can_prepare(ROOT,3,dict(items=[dict(id=3,pocket='balls',quantity=1)])))
  self.assertIn('хотя бы один',can_prepare(ROOT,3,dict(items=[dict(id=3,pocket='pc',quantity=8)])))
  self.assertIsNotNone(can_prepare(ROOT,121,dict(items=[dict(id=121,pocket='items',quantity=1)])))
  self.assertIsNotNone(can_prepare(ROOT,5,dict(items=[])));self.assertIsNotNone(can_prepare(ROOT,350,dict(items=[])))
 def test_prepared_static_donor_needs_no_stock_but_berry_route_disabled(self):
  self.assertTrue(availability(ROOT,4,dict(items=[]))[0]);self.assertFalse(availability(ROOT,142,dict(items=[dict(id=142,pocket='berries',quantity=1)]))[0])
 def test_source_registry_rejects_traversal_and_requires_library_relative_path(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);write_json(root/'Sessions/item-sources/catalog.json',{'3':dict(template='../escape')})
   with self.assertRaises(ValueError):provider(root,3)
   with self.assertRaises(ValueError):register(root,3,root.parent/'escape','uid',8,'firered')
 def test_reused_donor_excludes_shared_pokemon_ids(self):
  from pokemon_red.item_delivery import eligible_couriers
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);(root/'vendor').symlink_to(ROOT/'vendor');folder=root/'Sessions/item-sources/source/ready';folder.mkdir(parents=True)
   write_json(folder/'metadata.json',dict(state=dict(party=[dict(uid='shared'),dict(uid='donor')])))
   write_json(root/'Sessions/item-sources/catalog.json',{'3':dict(template='Sessions/item-sources/source/ready')})
   mon=dict(uid='shared',species_id=19,slot=1,level=5,checksum_valid=True,is_egg=False,shiny=False,held_item=0)
   party=[mon,dict(mon,uid='separate',slot=2)]
   self.assertEqual([m['uid'] for m in eligible_couriers(party,root,3)],['separate'])
   self.assertEqual(len(eligible_couriers(party,root)),2)
 def test_concurrent_source_preparation_does_not_lose_other_item(self):
  from concurrent.futures import ThreadPoolExecutor
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);a=root/'Sessions/item-sources/a/ready';b=root/'Sessions/item-sources/b/ready';a.mkdir(parents=True);b.mkdir(parents=True)
   with ThreadPoolExecutor(2) as pool:
    futures=[pool.submit(register,root,item,folder,'donor',8,'firered') for item,folder in [(3,a),(13,b)]]
    for future in futures:future.result()
   self.assertEqual(set(json.loads((root/'Sessions/item-sources/catalog.json').read_text())),{'3','13'})
 def test_native_identical_clones_rejected_before_any_movement(self):
  import time
  from pokemon_red.engine import Game
  from pokemon_red.item_delivery import verify_template
  from pokemon_red.persistence import SaveSnapshot
  from pokemon_red.operations import clone_session
  from pokemon_red.telemetry import read_state
  from pokemon_red.trade import perform_trade
  template=verify_template(ROOT,14)
  snapshot=SaveSnapshot((template/'FireRed.state').read_bytes(),(template/'FireRed.sav').read_bytes(),0,time.time())
  with tempfile.TemporaryDirectory() as td:
   a=clone_session(ROOT,Path(td)/'a',snapshot);b=clone_session(ROOT,Path(td)/'b',snapshot)
   with Game(a) as first,Game(b) as second:
    party=read_state(first)['party'];frames=(first.frame,second.frame)
    with self.assertRaisesRegex(RuntimeError,'уникальным ID'):
     perform_trade(first,second,party[0]['uid'],party[1]['uid'],SimpleNamespace(update=Mock(),heartbeat=Mock(),event=Mock()))
    self.assertEqual((first.frame,second.frame),frames)
    self.assertEqual(read_state(first)['party'],read_state(second)['party'])
 def test_source_result_never_replaces_main(self):
  from pokemon_red.operations import MainOperation
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);job=root/'job';job.mkdir()
   write_json(job/'operation.json',dict(kind='delivery_source',config=dict(item_id=3)));write_json(job/'status.json',dict(status='ready'));write_json(job/'result.json',dict(verified=True))
   game=SimpleNamespace(frame=4,load_state=Mock(),capture_save=Mock());m=SimpleNamespace(game=game,folder=root,keys=set(),update_panel=Mock(),refresh_state=Mock())
   op=MainOperation(m);op.job=job;op.game=game;op.frame=4;op.kind='delivery_source';op.process=SimpleNamespace(poll=lambda:0)
   op.poll();self.assertFalse(op.result['applied']);self.assertEqual(op.result['status'],'ready');game.load_state.assert_not_called();game.capture_save.assert_not_called()

if __name__=='__main__':unittest.main()
