from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
import copy,sys,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.battle_conditions import switch_blockers,escape_blockers
from pokemon_red.training import RouteTrainer

class BattleRecoveryTests(unittest.TestCase):
    def state(self,**own):
        return dict(battle=dict(allies=[dict(dict(hp=10,party_slot=1,types=[0],ability_id=0,status2=0,status3=0),**own)],enemies=[dict(hp=10,ability_id=0)]))
    def test_binding_ingrain_and_look_are_distinct_from_primary_status_and_seed(self):
        self.assertEqual(switch_blockers(self.state(status2=0x6000)),['binding'])
        self.assertEqual(switch_blockers(self.state(status3=1<<10)),['ingrain'])
        self.assertEqual(switch_blockers(self.state(status2=1<<26)),['escape_prevention'])
        self.assertEqual(switch_blockers(self.state(status3=4,status_code=8)),[])
        for code in (1,8,16,32,64,128):self.assertEqual(switch_blockers(self.state(status_code=code)),[])
    def test_trapping_abilities_respect_flying_levitate_and_steel(self):
        s=self.state();s['battle']['enemies'][0]['ability_id']=71;self.assertEqual(switch_blockers(s),['arena_trap'])
        s['battle']['allies'][0]['types']=[0,2];self.assertEqual(switch_blockers(s),[])
        s['battle']['allies'][0].update(types=[0],ability_id=26);self.assertEqual(switch_blockers(s),[])
        s['battle']['enemies'][0]['ability_id']=42;self.assertEqual(switch_blockers(s),[])
        s['battle']['allies'][0]['types']=[8];self.assertEqual(switch_blockers(s),['magnet_pull'])
        s['battle']['enemies'][0]['ability_id']=23;self.assertEqual(switch_blockers(s),['shadow_tag'])
        s['battle']['allies'][0]['hp']=0;self.assertEqual(switch_blockers(s),[])
    def test_run_away_and_smoke_ball_do_not_grant_switch_permission(self):
        s=self.state(status2=0x2000)
        for own in (dict(ability_id=50),dict(held_item=194)):
            self.assertEqual(escape_blockers(s,own),[]);self.assertEqual(switch_blockers(s),['binding'])
        self.assertTrue(escape_blockers(s,dict(ability_id=28)))
    def test_trapped_learner_attacks_instead_of_reopening_party_while_retreating(self):
        for retreat in (False,True):
            s=self.state(status2=0x6000);s.update(frame=100,in_battle=True,party=[dict(uid='t',slot=1,hp=10,moves=[dict(id=33,name='TACKLE',current_pp=10)],nickname='TARGET')],controls=dict(callback='BattleMainCB2',field_locked=False,tasks=[],controllers=['HandleInputChooseAction'],action_cursor=[0],move_cursor=[0]))
            s['battle']['flags']=0;t=object.__new__(RouteTrainer);t.config={'auto_team':True};t.trainee='t';t.state=lambda:s;t.stage=Mock();t.learn_dialog=lambda s:False;t.need_heal=lambda s:retreat;t.bot=SimpleNamespace(event=Mock(),log=Mock());t.party_select=Mock();t.attack_choice=lambda *a:0;t.battles=0
            choices=[]
            def choose(cursor,index):
                choices.append(index);s['frame']+=20
                if len(choices)==1:s['controls']['controllers']=['HandleInputChooseMove']
                else:s.update(in_battle=False);s['controls']['callback']='CB2_Overworld';s['party'][0].update(level=10,experience=100,exp_to_next_level=20)
            t.grid_choice=choose;t.fight(retreat=retreat);self.assertEqual(choices,[0,0]);t.party_select.assert_not_called();self.assertEqual(t.battles,1)
    def test_move_guard_suspension_rechecks_walk_without_key_error(self):
        s=dict(frame=100,map=dict(name='Route11'),position=dict(x=1,y=1),in_battle=False,party=[],controls=dict(callback='CB2_Overworld',field_locked=False,moving=False))
        t=object.__new__(RouteTrainer);t.state=lambda:s;t.wait=Mock();grid=dict(width=8,height=5,tiles=[[[0,0,3,0] for _ in range(8)] for _ in range(5)],obstacles=[]);t.bot=SimpleNamespace(map=lambda:grid);calls=[]
        def walk(*a,**kw):
            calls.append(a)
            if len(calls)==1:return dict(interrupted='move_plan')
            s['position'].update(x=3,y=1);return dict(reason='reached')
        t.bot.walk_segment=walk
        with patch('pokemon_red.training.path_to',return_value=[(2,1),(3,1)]),patch('pokemon_red.movement.safe_segment',return_value=[(2,1),(3,1)]),patch('pokemon_red.field_tools.party_cut',return_value=grid):t.go((3,1),search=True)
        self.assertEqual(len(calls),2);t.wait.assert_called_once_with(1)
    def test_transition_snapshot_is_not_used_as_navigation_map(self):
        s=dict(in_battle=False,map=dict(name='Map 0:0'),position=dict(x=3,y=1),controls=dict(callback='CB2_OverworldBasic',field_locked=True,moving=True))
        t=object.__new__(RouteTrainer);t.state=lambda:s
        def settle():s['map']['name']='Route11';s['controls'].update(callback='CB2_Overworld',field_locked=False,moving=False)
        t.wait=Mock(side_effect=settle);t.go((3,1),search=True);t.wait.assert_called_once()

if __name__=='__main__':unittest.main()
