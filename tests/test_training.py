"""Gen III reference arithmetic, stable identities and recorded battle outcomes."""
from pathlib import Path
import copy
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.catalog import catalog,species,move,experience_reward,effectiveness
from pokemon_red.history import History
from pokemon_red.training import path_to,validate,Route1Trainer,best_move,select_route,trainer_zones
from pokemon_red.bot import HandedOff

class ReferenceTests(unittest.TestCase):
    def test_catalog_is_gen_three_and_references_resolve(self):
        data=catalog()
        self.assertEqual(len(data['species']),386)
        self.assertEqual({s['national_id'] for s in data['species'].values()},set(range(1,387)))
        self.assertEqual(move(33)['power'],35) # Later games changed Tackle.
        self.assertEqual(move(22)['category'],'Special') # Gen III Grass is special.
        self.assertEqual(species(14)['evolutions'][0]['target'],15)
        for s in data['species'].values():
            self.assertTrue(all(str(m['move']) in data['moves'] for m in s['learnset']))
            xp=data['growth'][s['growth']]
            self.assertTrue(all(xp[i]<=xp[i+1] for i in range(1,100)))
            self.assertTrue(all(str(e['target']) in data['species'] for e in s['evolutions']))

    def test_xp_rounds_each_gen_three_stage_and_excludes_fainted(self):
        self.assertEqual(experience_reward(55,3),23)
        self.assertEqual(experience_reward(55,3,participants=2),11)
        self.assertEqual(experience_reward(55,3,participants=2,traded=True,trainer=True,lucky_egg=True),36)
        self.assertEqual(experience_reward(55,3,participants=2,share_holders=1,exp_share=True),16)
        self.assertEqual(experience_reward(55,3,participated=False,share_holders=1,exp_share=True),11)
        self.assertEqual(experience_reward(55,3,alive=False),0)
        self.assertEqual(experience_reward(55,3,recipient_level=100),0)
        self.assertEqual(effectiveness(12,[0,2]),0.5)

    def test_path_avoids_ledge_water_warps_and_live_objects(self):
        tiles=[[[0,0,3,0] for _ in range(5)] for _ in range(4)]
        tiles[0][1]=[0,0x3b,3,0];tiles[1][1]=[0,0x10,3,0];tiles[2][1]=[0,0x69,3,0]
        grid=dict(width=5,height=4,tiles=tiles,obstacles=[[2,3]])
        with self.assertRaises(RuntimeError):path_to(grid,(0,0),(4,0))
        grid['obstacles']=[]
        path=path_to(grid,(0,0),(4,0))
        self.assertIn((1,3),path)
        self.assertTrue(all(not(x==1 and y<3) for x,y in path))

    def test_history_records_actual_xp_and_survives_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'Data').mkdir();h=History(root)
            mon=dict(uid='stable',nickname='WEEDLE',experience=100,level=5)
            s=dict(ready=True,frame=100,map={'name':'Route1'},party=[mon],battle=dict(outcome=0,enemies=[dict(battler=1,species='PIDGEY',species_id=16,level=3)]))
            h.observe(s,'route1_xp.py')
            s=copy.deepcopy(s);s['frame']=500;s['party'][0].update(experience=111,level=6);s['battle']['outcome']=1;h.observe(s)
            s['frame']=550;s['battle']=None;h.observe(s);h.observe(s);h.close()
            h=History(root);rows=h.rows();self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]['xp'],11);self.assertEqual(rows[0]['outcome'],'Победа')
            self.assertEqual(rows[0]['detail']['gains'][0]['uid'],'stable');h.close()

    def test_reserve_and_hp_rules_follow_uid_after_party_reorder(self):
        class Bot:project_dir=ROOT
        config=dict(trainee='t',fighters=['a','b'],target=15,heal_percent=40)
        trainer=Route1Trainer(Bot(),config)
        def mon(uid,hp=20):return dict(uid=uid,slot=1,hp=hp,max_hp=20,status='В норме',moves=[dict(power=35,current_pp=10)])
        s={'party':[mon('b'),mon('t'),mon('a')]}
        self.assertFalse(trainer.need_heal(s))
        s['party'][2]['hp']=0
        self.assertTrue(trainer.need_heal(s))
        s['party'][2]['hp']=20;s['party'][1]['hp']=7
        self.assertTrue(trainer.need_heal(s))

    def test_move_decision_and_target_end_without_sending_buttons(self):
        class Bot:
            project_dir=ROOT
            def __init__(self):self.events=[]
            def checkpoint(self,name):
                if not 1<=len(name)<=64:raise ValueError('Invalid slot name')
            def event(self,*args,**kwargs):pass
            def handoff(self,code,message,**details):self.events.append((code,message,details));raise HandedOff()
            def press(self,*args,**kwargs):raise AssertionError('A choice must not press buttons')
        bot=Bot();trainer=Route1Trainer(bot,dict(trainee='t',fighters=['a','b'],target=15))
        mon=dict(uid='t',slot=1,nickname='BULBASAUR',species='BULBASAUR',species_id=1,level=14,experience=2000,moves=[{'name':n} for n in ('TACKLE','GROWL','LEECH SEED','VINE WHIP')])
        state=dict(party=[mon],battle=None,decision=dict(party_slot=1,move_id=77))
        with self.assertRaises(HandedOff):trainer.check_events(state)
        self.assertEqual(bot.events[-1][0],'move_choice_required')
        self.assertIn('POISONPOWDER',bot.events[-1][1])
        self.assertEqual(len(bot.events[-1][2]['current_moves']),4)
        state['decision']=None;mon['level']=15
        with self.assertRaises(HandedOff):trainer.check_events(state)
        self.assertEqual(bot.events[-1][0],'target_reached')

    def test_route_selection_is_fixed_by_start_location(self):
        for name in ('Route2','ViridianForest','Route2_ViridianForest_SouthEntrance'):
            self.assertEqual(select_route(name),'Route2')
        for name in ('Route1','ViridianCity','ViridianCity_PokemonCenter_1F'):
            self.assertEqual(select_route(name),'Route1')
        with self.assertRaises(ValueError):select_route('Route22')

    def test_transit_prefers_zero_grass_even_when_detour_is_longer(self):
        tiles=[[[0,0,3,0] for _ in range(6)] for _ in range(3)]
        tiles[1][2]=[0,2,3,1];grid=dict(width=6,height=3,tiles=tiles,obstacles=[])
        path=path_to(grid,(0,1),(5,1))
        self.assertNotIn((2,1),path)
        self.assertGreater(len(path),5)
        self.assertIn((2,1),path_to(grid,(0,1),(5,1),avoid_grass=False))

    def test_path_avoids_trainer_sight_including_possible_rotations(self):
        grid=dict(width=8,height=6,tiles=[[[0,0,3,0] for _ in range(8)] for _ in range(6)],obstacles=[],
                  trainers=[dict(x=4,y=2,movement=13,sight=2,trainer_type=1)])
        zone=trainer_zones(grid)
        self.assertIn((4,0),zone);self.assertIn((4,4),zone)
        path=path_to(grid,(0,2),(7,2))
        self.assertFalse(set(path)&zone)

    def test_transient_party_data_waits_without_pressing_buttons(self):
        class Bot:
            project_dir=ROOT
            def __init__(self):self.calls=0;self.waits=[]
            def state(self):self.calls+=1;return dict(telemetry_valid=self.calls>1)
            def wait_frames(self,n):self.waits.append(n)
            def press(self,*args,**kwargs):raise AssertionError('No buttons during invalid telemetry')
        bot=Bot();trainer=Route1Trainer(bot,dict(trainee='t',fighters=['a','b']))
        self.assertTrue(trainer.state()['telemetry_valid']);self.assertEqual(bot.waits,[2])

if __name__=='__main__':unittest.main()
