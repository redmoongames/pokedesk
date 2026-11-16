"""Persistent pure planner. It requests only maps needed by candidate journeys."""
from pathlib import Path
import sys,json,traceback
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from pokemon_red.optimizer import make_training_plan,read_evidence
from pokemon_red.planning_state import PlanningCache,PlanningSnapshotExpired
from pokemon_red.map_repository import MapRepository
cache=PlanningCache();generation=object();grids={}
class Superseded(Exception):pass

def output(packet):
    from pokemon_red.installation_versions import versioned_response
    print(json.dumps(versioned_response(packet),ensure_ascii=False),flush=True)

for line in sys.stdin:
    try:
        request=json.loads(line);inventory=request['inventory'];world=inventory.get('_planning');root=Path(request['root'])
        if world is not None:
            token=(str(root),world.get('map_revision'))
            if token!=generation:grids={};generation=token
            def load_map(name):
                output(dict(type='map_request',name=name,revision=world.get('map_revision')))
                reply=json.loads(sys.stdin.readline())
                if reply.get('cancelled'):raise Superseded()
                if reply.get('error'):raise PlanningSnapshotExpired(reply['error'])
                if reply.get('name')!=name:raise RuntimeError('Нарушен порядок снимков карт')
                value=reply.get('grid');grids[name]=value;return value
            world['grids']=MapRepository(load_map,grids)
            world['canonical_navigation']=True
        evidence_key=(str(root),(world or {}).get('revision'))
        if cache.evidence_key!=evidence_key:
            cache.evidence=read_evidence(root);cache.evidence_key=evidence_key
        result=make_training_plan(inventory,request['config'],root,cache=cache,evidence=cache.evidence)
        packet=dict(plan=result,error=None)
    except Superseded:packet=dict(type='cancelled')
    except Exception as error:
        traceback.print_exc(file=sys.stderr);packet=dict(plan=None,error=str(error),availability=getattr(error,'excluded',[]))
    output(packet)
