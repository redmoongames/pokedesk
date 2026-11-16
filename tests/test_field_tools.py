from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import json,sys,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from test_grind import mon
from pokemon_red.field_tools import choose_runner,available,cut_grid,party_cut,teleport_slot
from pokemon_red.planning import make_plan
from pokemon_red.navigation import Navigator
from pokemon_red.field_actions import CutRuntime,FieldMismatch
from pokemon_red.engine import BUTTONS

class FieldToolsTests(unittest.TestCase):
    def team(self):return [mon(25,12,'target',[84]),mon(19,10,'rat',[33],ability_id=50),mon(64,25,'kadabra',[100,93]),mon(21,20,'bird',[64]),mon(12,20,'butterfree',[93]),mon(1,20,'cut',[15],location='box')]
    def test_kadabra_teleport_precedes_run_away_and_goal_is_never_own_runner(self):
        team=self.team();self.assertEqual(choose_runner(team,'target')['uid'],'kadabra')
        self.assertEqual(choose_runner(team,'kadabra')['uid'],'rat')
        self.assertEqual(choose_runner(team,'rat')['uid'],'kadabra')
        self.assertIsNone(choose_runner([team[1]],'rat'))
        self.assertIsNone(choose_runner([dict(team[1],ability_id=62)],'target'))
        team[2]['moves'][0]['current_pp']=0;self.assertEqual(choose_runner(team,'target')['uid'],'kadabra') # Clinic restores PP.
    def test_no_escape_candidate_is_valid_and_all_slots_are_available(self):
        team=[m for m in self.team() if m['uid'] not in ('rat','kadabra')]
        p=make_plan(dict(ready=True,party=team,boxes=[]),dict(trainee='target',target=15,route='Route1'),ROOT)
        self.assertIsNone(p['runner']);self.assertEqual(set(p['team_uids']),{m['uid'] for m in team})
    def test_boxed_cut_provider_is_reserved_in_team_and_shared_roles_deduplicate(self):
        team=self.team();inv=dict(ready=True,party=team[:5],boxes=team[5:])
        p=make_plan(inv,dict(trainee='target',target=15,route='Route9',_required_tools=['cut']),ROOT)
        self.assertIn('cut',p['team_uids']);self.assertEqual(p['utility_uids'],['cut']);self.assertLessEqual(len(p['team']),6)
        team[2]['moves'].append(dict(id=15,name='CUT',power=50,pp=30,max_pp=30,type_id=0,category='Physical',accuracy=95))
        p=make_plan(inv,dict(trainee='target',target=15,route='Route9',_required_tools=['cut']),ROOT)
        self.assertEqual(p['runner'],'kadabra');self.assertEqual(p['utility_uids'],['kadabra']);self.assertEqual(p['team_uids'].count('kadabra'),1)
    def test_badge_and_learned_move_are_both_required(self):
        team=self.team();tools=available(team,[]);self.assertFalse(tools['cut']['unlocked']);self.assertEqual(tools['cut']['providers'],['cut'])
        self.assertTrue(available(team,[2])['cut']['unlocked']);self.assertFalse(available(team,[1,2,3,4,5])['surf']['automatic'])
    def test_cut_removes_only_tree_obstacle_and_keeps_fast_walk_hazard(self):
        g=dict(obstacles=[[2,0],[3,0]],objects=[dict(x=2,y=0,graphics_id=95)],field_badges=[2]);before=json.dumps(g)
        changed=party_cut(g,self.team());self.assertEqual(changed['obstacles'],[[3,0]]);self.assertEqual(changed['objects'],g['objects']);self.assertEqual(json.dumps(g),before)
        self.assertEqual(party_cut(dict(g,field_badges=[]),self.team())['obstacles'],g['obstacles'])
    def test_boxed_tool_cannot_be_used_to_reach_first_clinic(self):
        grid=dict(name='Room',width=5,height=1,tiles=[[[0,0,3,0] for _ in range(5)]],obstacles=[[2,0]],objects=[dict(local_id=1,x=2,y=0,graphics_id=95)],field_badges=[2])
        t=SimpleNamespace(root=ROOT,bot=SimpleNamespace(map=lambda _:grid),state=lambda:dict(map={'name':'Room'},position={'x':0,'y':0}))
        nav=Navigator(t).configure_tools(dict(party=[],boxes=[self.team()[-1]],field_badges=[2]));nav.spec=dict(links=[],hubs={'Only':dict(map='Room',nurse=[4,0])},zones={})
        # The post-PC plan can cut; the initial plan cannot reach the PC at all.
        self.assertTrue(nav.plan('Room',[0,0],'Room',[4,0])['field_actions'])
        initial=nav.initial_tools();initial.spec=nav.spec
        with self.assertRaises(RuntimeError):initial.current_plan('Room',[4,0])
    def test_retreat_cancels_an_already_open_attack_menu(self):
        from pokemon_red.training import RouteTrainer
        m=self.team()[0];m.update(experience=100,exp_to_next_level=200)
        state=dict(frame=1,in_battle=True,party=[m],battle=dict(flags=0,allies=[],enemies=[]),controls=dict(tasks=[],controllers=['HandleInputChooseMove'],move_cursor=[0],callback='BattleMainCB2',field_locked=False))
        bot=SimpleNamespace(project_dir=ROOT,log=lambda _:None);t=RouteTrainer(bot,dict(trainee=m['uid'],fighters=[m['uid']],target=99));t.state=lambda:state;t.stage=lambda _:None;t.learn_dialog=lambda _:False;t.healthy_fighters=lambda _:[m];calls=[]
        def tap(key):
            calls.append(key);state['in_battle']=False;state['controls']['callback']='CB2_Overworld'
        t.tap=tap;t.fight(retreat=True,travel=True);self.assertEqual(calls,['B'])
    def test_teleport_pp_checked_at_runtime(self):
        k=self.team()[2];self.assertEqual(teleport_slot(k),0);k['moves'][0]['current_pp']=0;self.assertIsNone(teleport_slot(k))

class CutGuardTests(unittest.TestCase):
    def runtime(self):
        r=object.__new__(CutRuntime);r.badge=2;r.graphics=95;r.map='Route9';r.point=(2,8);r.local_id=10;r.mask=0;r.phase='awaiting';r.frame=0;r.last_frame=-1;r.last_pulse=-20;r.start=(1,8);r.provider='cut'
        c=dict(frame=30,map='Route9',position=[1,8],in_battle=False,battle_pending=False,open=False,moving=False,tree=dict(x=2,y=8),cut_script=True,last_talked=10,native=True,cursor=0)
        return r,c
    def tick(self,r,c):
        g=SimpleNamespace(frame=c['frame'])
        with patch('pokemon_red.field_actions.control',return_value=c),patch('pokemon_red.field_actions.read_field_badges',return_value=[2]):return r.poll(g)
    def test_unknown_dialog_or_wrong_object_never_receives_confirmation(self):
        for change in (dict(cut_script=False),dict(last_talked=9),dict(map='Elsewhere'),dict(in_battle=True)):
            r,c=self.runtime();c.update(change)
            with self.assertRaises(FieldMismatch):self.tick(r,c)
            self.assertEqual(r.mask,0)
    def test_yes_no_cursor_and_tree_removal_are_verified(self):
        r,c=self.runtime();c['cursor']=1;self.tick(r,c);self.assertEqual(r.mask,BUTTONS['UP'])
        c.update(frame=42,cursor=0);self.tick(r,c);self.assertEqual(r.mask,BUTTONS['A'])
        c.update(frame=60,open=True,tree=None);self.assertTrue(self.tick(r,c));self.assertEqual(r.mask,0)
    def test_cancel_releases_cut_input(self):
        r,c=self.runtime();self.tick(r,c);self.assertNotEqual(r.mask,0);r.cancel();self.assertEqual(r.mask,0)

if __name__=='__main__':unittest.main()
