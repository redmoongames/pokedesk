#!/usr/bin/env python3
"""Reproduce native item delivery on disposable Data, never the supplied save."""
import argparse,hashlib,json,sys,time,shutil
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from pokemon_red.acquisition import read_json,write_json
from pokemon_red.persistence import SaveSnapshot
from pokemon_red.operations import clone_session
from pokemon_red.engine_runtime import EngineRuntime
from pokemon_red.item_delivery import eligible_couriers,quantity,verify_template

def run(source,output,item,requested,mode,timeout,pause_after=None):
    source=Path(source).resolve();output=Path(output).resolve()
    if output.exists():raise FileExistsError('Choose a new output directory')
    output.mkdir(parents=True)
    paths=[source/'Data'/n for n in ('FireRed.state','FireRed.sav')]
    hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    snapshot=SaveSnapshot(paths[0].read_bytes(),paths[1].read_bytes(),0,time.time())
    # A private library keeps both prepared donors and test source code local.
    # Its base cartridge stays FireRed; an LG recipient has its own ROM below.
    from pokemon_red.item_sources import library_root
    implementation=Path(__file__).resolve().parents[1];original_library=library_root(implementation)
    library=output/'library';library.mkdir();(library/'Data').mkdir();shutil.copytree(implementation/'src',library/'src')
    for name in ('native','vendor','assets','runtime','Bots','templates','ROMs'):
        (library/name).symlink_to(original_library/name)
    (library/'Data/FireRed.gba').symlink_to(original_library/'Data/FireRed.gba')
    root=clone_session(library,output/'session',snapshot)
    (root/'Data/FireRed.gba').unlink();(root/'Data/FireRed.gba').symlink_to((source/'Data/FireRed.gba').resolve())
    if (source/'Data/game.json').exists():shutil.copy2(source/'Data/game.json',root/'Data/game.json')
    write_json(root/'Data/settings.json',dict(speed=16,sound_enabled=False,autosave_enabled=False,panel_on_start=False))
    runtime=EngineRuntime(root,paused=True);runtime.ready.result(15);started=time.monotonic();paused=False
    try:
        before=runtime.submit('bag').result(15);inventory=runtime.submit('inventory').result(15);couriers=eligible_couriers(inventory['party'],root)
        if not couriers:raise RuntimeError('No eligible courier')
        job=runtime.submit('delivery_enqueue',requested,mode,couriers[0]['uid'],item).result(15)
        runtime.submit('delivery_start',job).result(15);last=None
        while time.monotonic()-started<timeout:
            row=runtime.submit('delivery_get',job).result(15)
            signature=(row['delivered'],row['status'])
            if signature!=last:
                last=signature;write_json(output/'progress.json',dict(row,seconds=time.monotonic()-started));print(row['delivered'],row['status'],row['stage'],flush=True)
            if row['status']=='done' and not runtime.latest.operation['active']:break
            if pause_after is not None and not paused and row['delivered']>=pause_after:
                runtime.submit('delivery_pause',job).result(15);paused=True
            if row['status']=='paused' and paused:runtime.submit('delivery_start',job).result(15)
            elif row['status'] in ('attention','paused','cancelled'):raise RuntimeError(row['stage'])
            time.sleep(.2)
        else:raise TimeoutError('Delivery did not finish')
        after=runtime.submit('bag').result(15);after_inventory=runtime.submit('inventory').result(15)
        expected=quantity(before,item)+requested if mode=='add' else requested
        assert quantity(after,item)==expected
        assert [m['uid'] for m in inventory['party']]==[m['uid'] for m in after_inventory['party']]
        receipt_paths=sorted((root/'Sessions/item-delivery'/job/'receipts').glob('*.json'));receipts=[read_json(p) for p in receipt_paths]
        assert len(receipts)==row['amount']==row['delivered']
        assert all(r['item_id']==item and r['quantity_after']==r['quantity_before']+1 for r in receipts)
        assert hashes=={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},'Supplied source changed during benchmark'
        report=dict(passed=True,item_id=item,before=quantity(before,item),after=expected,seconds=time.monotonic()-started,job=row,receipts=len(receipts),pause_resume=paused,source_hashes=hashes,party_uids=[m['uid'] for m in after_inventory['party']])
        write_json(output/'report.json',report);return report
    finally:
        runtime.take_control(close=True);runtime.finished.result(20);runtime.thread.join(3)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--source',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--item',type=int,default=4);parser.add_argument('--quantity',type=int,default=20);parser.add_argument('--mode',choices=['add','target'],default='add');parser.add_argument('--timeout',type=float,default=7200);parser.add_argument('--pause-after',type=int)
    args=parser.parse_args();print(json.dumps(run(args.source,args.output,args.item,args.quantity,args.mode,args.timeout,args.pause_after),ensure_ascii=False,indent=2))
