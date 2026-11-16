"""Regression: moving trainer origins and idempotent clinic preparation."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
import copy,sys,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.engine import Game
from pokemon_red.telemetry import read_map
from pokemon_red.training import trainer_zones,path_to,TrainingProblem
from pokemon_red.navigation import safe_grass_pair
from pokemon_red.movement import safe_segment,straight_path
from pokemon_red.grind import GrindTrainer,recovery_reasons
from pokemon_red.storage import Storage

def pokemon(uid='one'):
    return dict(uid=uid,nickname=uid,level=12,species_id=25,hp=30,max_hp=30,status='В норме',status_code=0,checksum_valid=True,is_egg=False,moves=[dict(id=33,current_pp=35,pp=35,max_pp=35)])

class PatrolRegressionTests(unittest.TestCase):
    def trainer(self,**kw):
        return dict(dict(local_id=4,x=31,y=14,anchor_x=28,anchor_y=10,movement=40,range_x=8,range_y=4,sight=1,trainer_type=1,defeated=True),**kw)
    def test_defeated_patrol_never_creates_a_shifted_rectangular_obstacle(self):
        blocked=trainer_zones(dict(trainers=[self.trainer()]))
        self.assertIn((31,14),blocked)
        self.assertTrue(all((x,16) not in blocked for x in range(18,35)))
    def test_unbeaten_patrol_sight_stays_anchored_at_every_live_corner(self):
        for x,y in ((28,10),(36,10),(28,14),(36,14)):
            blocked=trainer_zones(dict(trainers=[self.trainer(x=x,y=y,defeated=False)]))
            self.assertIn((28,15),blocked);self.assertNotIn((28,16),blocked)
    def test_actual_position_outside_origin_still_blocks_body_and_sight(self):
        t=self.trainer(x=45,y=20,defeated=False);blocked=trainer_zones(dict(trainers=[t]))
        self.assertIn((45,20),blocked);self.assertIn((45,21),blocked);self.assertNotIn((45,24),blocked)
    def test_real_rom_strip_is_walkable_both_ways_through_all_patrol_phases(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'Data').mkdir();(root/'Data/FireRed.gba').symlink_to(ROOT/'Data/FireRed.gba')
            for name in ('vendor','native'):(root/name).symlink_to(ROOT/name)
            with Game(root,resume=False) as game:
                baseline=read_map(game,'Route11');original=next(t for t in baseline['trainers'] if t['local_id']==4)
                self.assertEqual((original['anchor_x'],original['anchor_y']),(28,10))
                for x in range(28,37):
                    for y in range(10,15):
                        grid=copy.deepcopy(baseline)
                        for t in grid['trainers']:
                            t['defeated']=True
                            if t['local_id']==4:t.update(x=x,y=y)
                        for obj in grid['objects']:
                            if obj['local_id']==4:obj.update(x=x,y=y)
                        for a,b in (((18,16),(34,16)),((34,16),(18,16))):
                            path=path_to(grid,a,b,avoid_grass=False);self.assertEqual(len(path),16)
                            self.assertEqual(safe_segment(grid,a,path,search=True),path)
                        chosen=safe_grass_pair(grid,(18,16));self.assertGreaterEqual(chosen['length'],10)

class RecoveryTests(unittest.TestCase):
    def trainer(self,party=None):
        t=object.__new__(GrindTrainer);t.root=ROOT;t.preparing=True;t.want_heal=True;t.route='Route11';t.plan={'team_uids':['one']}
        state=dict(ready=True,telemetry_valid=True,position={'x':7,'y':4},map={'name':'VermilionCity_PokemonCenter_1F'},party=party or [pokemon()],controls=dict(callback='CB2_Overworld',field_locked=False,moving=False))
        t.state=lambda:state;t.go=Mock();t.expect_interaction=Mock();t.stage=Mock();events=[];t.bot=SimpleNamespace(event=lambda *a,**k:events.append((a,k)))
        nurse=[0];active=[False]
        def tap(key,**_):
            if key!='A':return
            if not active[0]:nurse[0]+=1;active[0]=True;state['controls']['field_locked']=True
            else:
                for m in state['party']:
                    m.update(hp=m['max_hp'],status='В норме',status_code=0)
                    for a in m['moves']:a['current_pp']=a['max_pp']
                active[0]=False;state['controls']['field_locked']=False
        t.tap=Mock(side_effect=tap)
        return t,state,nurse,events
    def test_full_party_repeat_recovery_has_no_input_or_nurse_walk(self):
        t,state,nurse,events=self.trainer()
        for _ in range(4):self.assertFalse(t.heal_here())
        self.assertEqual(nurse[0],0);t.tap.assert_not_called();t.go.assert_not_called();self.assertFalse(t.want_heal)
        self.assertEqual(sum(e[0][0]=='healing_skipped' for e in events),4)
    def test_hp_status_and_pp_each_trigger_one_heal_then_repeat_is_skipped(self):
        for mutation in ('hp','status','pp','fainted'):
            t,state,nurse,events=self.trainer();m=state['party'][0]
            if mutation=='hp':m['hp']=20
            elif mutation=='status':m.update(status='Паралич',status_code=64)
            elif mutation=='pp':m['moves'][0]['current_pp']=0
            else:m.update(hp=0,status='Без сознания')
            self.assertTrue(t.heal_here());self.assertFalse(t.heal_here());self.assertEqual(nurse[0],1)
            self.assertEqual(sum(e[0][0]=='healing_started' for e in events),1);self.assertEqual(sum(e[0][0]=='healing_completed' for e in events),1)
    def test_new_damage_or_new_party_member_allows_a_new_heal(self):
        t,state,nurse,_=self.trainer();state['party'][0]['hp']=10;t.heal_here()
        state['party'].append(dict(pokemon('boxed'),hp=1));self.assertTrue(t.heal_here());self.assertEqual(nurse[0],2)
        state['party'][0]['moves'][0]['current_pp']=34;self.assertTrue(t.heal_here());self.assertEqual(nurse[0],3)
    def test_incomplete_telemetry_never_becomes_a_skip_or_button_press(self):
        for key,value in (('party',[]),('telemetry_valid',False)):
            t,state,_,_=self.trainer();state[key]=value
            with self.assertRaises(TrainingProblem):t.heal_here()
            t.tap.assert_not_called()
        t,state,_,_=self.trainer();del state['party'][0]['moves'][0]['current_pp']
        with self.assertRaises(TrainingProblem):t.heal_here()
        t.tap.assert_not_called()
    def test_clinic_preparation_assembles_once_before_recovering_actual_roster(self):
        t,state,nurse,_=self.trainer();order=[]
        def assemble(_):order.append('assemble');state['party'][0]['moves'][0]['current_pp']=2
        with patch('pokemon_red.grind.Storage',return_value=SimpleNamespace(assemble=assemble)):
            t.prepare_at_clinic()
        self.assertEqual(order,['assemble']);self.assertEqual(nurse[0],1);self.assertEqual(recovery_reasons(state),[])
    def test_run_prepares_once_and_only_heals_again_after_a_resource_spending_trip(self):
        class Prepared(Exception):pass
        for different in (False,True):
            t,state,nurse,events=self.trainer();t.config=dict(auto_team=True,trainee='one',target=30,route='Route11',strategy='adaptive');t.trainee='one';t.target=30;t.strategy='adaptive';t.runner=None;t.fighters=set();t.cycle_number=0;t.training_session=None;t.run_id=None;t.requested_route='Route11'
            if different:state['map']['name']='CeruleanCity_PokemonCenter_1F'
            inventory=lambda:dict(ready=True,party=state['party'],boxes=[])
            t.bot.inventory=inventory;t.bot.map=Mock();t.bot.safety_profile=Mock();t.travel_lead=Mock();t.begin_cycle=Mock(side_effect=Prepared)
            plan=dict(trainee='one',target=30,runner=None,fighters=['one'],reserves=[],utility_uids=[],field_tools=[],team_uids=['one'],team_fingerprint='test',team=[dict(pokemon(),species_id=25,level=12,location='party')],route='Route11',strategy='adaptive',warnings=[],matchups=[],ohko_chance=1,assumptions='test')
            trips=[]
            def travel(name,goal):
                if state['map']['name']!=name:state['party'][0]['moves'][0]['current_pp']=20
                state['map']['name']=name;trips.append(name)
            farm=dict(hub='Vermilion',map='Route11',pair=[[18,16],[34,16]],cost=[1,152])
            t.navigator=SimpleNamespace(configure_tools=Mock(),choose_farm=lambda _:farm,nearest_clinic=lambda *a,**k:('Cerulean' if different else 'Vermilion',dict(cost=[0,0])),travel=travel,travel_prepared=lambda name,goal,**kwargs:travel(name,goal))
            assemblies=[]
            def assemble(_):assemblies.append(True);state['party'][0]['moves'][0]['current_pp']=5
            with patch('pokemon_red.optimizer.map_names',return_value=[]),patch('pokemon_red.optimizer.make_training_plan',return_value=plan),patch('pokemon_red.grind.Storage',return_value=SimpleNamespace(assemble=assemble)):
                with self.assertRaises(Prepared):t.run()
            self.assertEqual(len(assemblies),1);self.assertEqual(nurse[0],2 if different else 1);self.assertEqual(len(trips),2 if different else 1)
            self.assertEqual(sum(e[0][0]=='preparation_complete' for e in events),1)
    def test_matching_roster_has_no_pc_operations_or_new_checkpoint(self):
        checkpoints=[];events=[];party=[pokemon('one'),pokemon('two')]
        bot=SimpleNamespace(inventory=lambda:dict(ready=True,party=party,boxes=[]),checkpoint=lambda *a:checkpoints.append(a),event=lambda *a,**kw:events.append(a))
        storage=Storage(SimpleNamespace(bot=bot));storage.deposit=Mock();storage.withdraw=Mock()
        self.assertFalse(storage.assemble(['two','one']));self.assertFalse(checkpoints);storage.deposit.assert_not_called();storage.withdraw.assert_not_called();self.assertEqual(events[0][0],'team_unchanged')

if __name__=='__main__':unittest.main()
