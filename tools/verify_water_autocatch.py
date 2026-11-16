#!/usr/bin/env python3
"""Real native catches on disposable copies; fixture must already have rods/Surf.

No progress, flags, inventory or Pokémon memory is fabricated. Every attempt uses
ordinary buttons. The supplied fixture and project Data are never overwritten.
"""
from pathlib import Path
import argparse,hashlib,json,sys,time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from pokemon_red.engine import Game
from pokemon_red.operations import clone_session
from pokemon_red.persistence import SaveSnapshot
from pokemon_red.journey import Journey
from pokemon_red.autocatch import run_autocatch
from pokemon_red.field_encounters import populations
from pokemon_red.models import STAT_KEYS,read_inventory

class Probe:
    def heartbeat(self):pass
    def safe_point(self):pass
    def event(self,code,details):
        if code in ('autocatch_caught','capture_retry'):print(code,flush=True)
    def update(self,**kw):
        if 'stage' in kw:print(kw['stage'],flush=True)

def run(project,fixture,output,locations,methods,local_fixture=None):
    tracked=[fixture/name for name in ('FireRed.state','FireRed.sav')]+[project/'Data'/name for name in ('FireRed.state','FireRed.sav')]
    if local_fixture:tracked.extend(local_fixture/name for name in ('FireRed.state','FireRed.sav'))
    digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    before={str(p):digest(p) for p in tracked};results=[]
    try:
        for name in locations:
            source=local_fixture if local_fixture and name=='Route12' else fixture
            for method in methods:
                root=clone_session(project,output/(name+'-'+method),SaveSnapshot((source/'FireRed.state').read_bytes(),(source/'FireRed.sav').read_bytes(),0,time.time()))
                species=populations(root)[name][method][0]['species_id'];config=dict(schema_version=2,species_id=species,method=method,route=name,gender='any',min_ivs=dict.fromkeys(STAT_KEYS,0));started=time.monotonic()
                with Game(root) as game:
                    p=Journey(game,Probe());owned=read_inventory(game);uids={m['uid'] for m in owned['party']+owned['boxes']};mon=run_autocatch(p,config);p.save_game();after=read_inventory(game)
                    assert uids<={m['uid'] for m in after['party']+after['boxes']};assert mon['uid'] not in uids and mon['species_id']==species
                    game.save_to(root/'Data')
                    row=dict(passed=True,map=name,method=method,species_id=species,uid=mon['uid'],seconds=time.monotonic()-started)
                    (root/'result.json').write_text(json.dumps(row,indent=2));results.append(row);print(row,flush=True)
    finally:
        assert before=={str(p):digest(p) for p in tracked},'Source saves changed outside disposable cases'
        output.mkdir(parents=True,exist_ok=True);(output/'results.json').write_text(json.dumps(results,indent=2))
    return results

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--project',type=Path,default=Path(__file__).resolve().parents[1]);parser.add_argument('--fixture',type=Path,required=True);parser.add_argument('--route12-fixture',type=Path);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--locations',nargs='+',default=['VermilionCity','Route6','ViridianCity']);parser.add_argument('--methods',nargs='+',choices=['old_rod','good_rod','super_rod','water_mons'],default=['old_rod','good_rod','super_rod','water_mons']);args=parser.parse_args()
    run(args.project.resolve(),args.fixture.resolve(),args.output.resolve(),args.locations,args.methods,args.route12_fixture.resolve() if args.route12_fixture else None)
