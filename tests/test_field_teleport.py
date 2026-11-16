from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
import copy,sys,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.field_teleport import offer,destinations,TeleportRuntime,TELEPORT_ACTION,OUTDOOR_TYPES
from pokemon_red.field_actions import FieldMismatch
from pokemon_red.telemetry import read_map,read_state
from pokemon_red.engine import Game,BUTTONS
from pokemon_red.zones import zone_spec
from pokemon_red.grind import GrindTrainer
from pokemon_red.optimizer import forecast_cycle
from pokemon_red.planning import make_plan
from pokemon_red.session_controller import SessionController as Monitor
from pokemon_red.automation import Automation,Request,Session
from test_grind import mon

class TeleportTests(unittest.TestCase):
    def state(self):
        k=mon(64,28,'k',[100,93]);k['slot']=2
        return dict(ready=True,in_battle=False,map=dict(name='Route11'),position=dict(x=18,y=16),party=[k],controls=dict(callback='CB2_Overworld',field_locked=False,moving=False),field_teleport=dict(map_type=3,landing=copy.deepcopy(destinations(ROOT)['Vermilion'])))
    def runtime(self):
        s=self.state();g=SimpleNamespace(frame=100,root=ROOT);r=TeleportRuntime(g,offer(s,'Vermilion',ROOT),s);c=dict(s['controls'],fading=False,tasks=[],party_action=0,party_cursor=1,party_actions=[0,29,25,1,3,2],menu_cursor=0,walk=dict(map='Route11',position=[18,16],ready=True,open=False,moving=False,in_battle=False,battle_pending=False),teleport=s['field_teleport'],post_callback=0,field_callback=0,field_move=7)
        return s,g,r,c
    def poll(self,s,g,r,c):
        with patch('pokemon_red.field_teleport.control',return_value=c),patch('pokemon_red.field_teleport.read_learning_mon',return_value=s['party'][0]):return r.poll(g)
    def test_all_registered_clinics_have_exact_outdoor_warp_coordinates(self):
        d=destinations(ROOT);self.assertEqual(set(d),set(zone_spec(ROOT)['hubs']));self.assertEqual(d['Fuchsia'],dict(map='FuchsiaCity',point=[25,32],warp_id=-1));self.assertEqual(d['Vermilion'],dict(map='VermilionCity',point=[15,7],warp_id=-1));self.assertEqual(d['MtMoon']['map'],'Route4');self.assertEqual(d['Route10']['point'],[13,21])
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'Data').mkdir();(root/'Data/FireRed.gba').symlink_to(ROOT/'Data/FireRed.gba')
            for name in ('vendor','native'):(root/name).symlink_to(ROOT/name)
            with Game(root,resume=False) as game:
                for record in d.values():
                    grid=read_map(game,record['map']);x,y=record['point'];self.assertIn(grid['map_type'],OUTDOOR_TYPES);self.assertFalse(grid['tiles'][y][x][0]);self.assertEqual(grid['tiles'][y][x][3],0)
    def test_exact_center_match_not_similar_name_or_same_region(self):
        s=self.state();self.assertTrue(offer(s,'Vermilion',ROOT)['teleported']);self.assertEqual(offer(s,'Cerulean',ROOT)['reason'],'wrong_destination')
        for change in (dict(point=[15,8]),dict(warp_id=0)):
            s=self.state();s['field_teleport']['landing'].update(change);self.assertEqual(offer(s,'Vermilion',ROOT)['reason'],'wrong_destination')
    def test_no_provider_eggs_checksum_and_boxes_do_not_invent_a_party_member(self):
        for change in ('absent','egg','checksum','boxed'):
            s=self.state()
            if change=='absent':s['party'][0]['moves']=[]
            elif change=='egg':s['party'][0]['is_egg']=True
            elif change=='checksum':s['party'][0]['checksum_valid']=False
            else:s['boxes']=s['party'];s['party']=[]
            self.assertEqual(offer(s,'Vermilion',ROOT)['reason'],'no_provider')
    def test_field_move_uses_game_rules_without_battle_pp_or_escape_role_requirement(self):
        s=self.state();s['party'][0].update(hp=0);s['party'][0]['moves'][0]['current_pp']=0
        self.assertTrue(offer(s,'Vermilion',ROOT)['teleported'])
    def test_indoor_caves_battle_and_locked_transition_send_no_input(self):
        for kind in (4,8,9,0):
            s=self.state();s['field_teleport']['map_type']=kind;self.assertEqual(offer(s,'Vermilion',ROOT)['reason'],'map_forbidden')
        for key in ('field_locked','moving'):
            s=self.state();s['controls'][key]=True;self.assertFalse(offer(s,'Vermilion',ROOT)['teleported'])
        s=self.state();s['in_battle']=True;self.assertFalse(offer(s,'Vermilion',ROOT)['teleported'])
    def test_unavailable_server_preflight_never_creates_checkpoint_or_runtime(self):
        s=self.state();m=SimpleNamespace(game=object(),folder=ROOT,create_slot=Mock())
        with patch('pokemon_red.session_controller.read_state',return_value=s):self.assertFalse(Monitor.install_field_action(m,dict(action='teleport',clinic='Cerulean'))['teleported'])
        m.create_slot.assert_not_called()
    def test_dynamic_menu_chooses_teleport_id_after_sweet_scent(self):
        s,g,r,c=self.runtime();r.phase='options';c['tasks']=[dict(name='Task_HandleSelectionMenuInput')];c['menu_cursor']=1
        self.poll(s,g,r,c);self.assertEqual(r.mask,BUTTONS['DOWN']);g.frame+=12;c['menu_cursor']=2;self.poll(s,g,r,c);self.assertEqual(r.mask,BUTTONS['A']);self.assertEqual(r.phase,'prompt')
    def test_fade_and_uninitialized_start_menu_do_not_consume_confirmation(self):
        s,g,r,c=self.runtime();r.phase='start_menu';c.update(start_order=[0,1,2],start_cursor=1,tasks=[dict(name='Task_StartMenuHandleInput',data=[0])]);self.poll(s,g,r,c);self.assertEqual(r.mask,0);self.assertEqual(r.phase,'start_menu')
        g.frame+=12;c['tasks'][0]['data']=[1];c['fading']=True;self.poll(s,g,r,c);self.assertEqual(r.mask,0)
    def test_destination_changes_close_menu_before_walking_fallback(self):
        s,g,r,c=self.runtime();r.phase='prompt';c['teleport']=dict(c['teleport'],landing=destinations(ROOT)['Cerulean']);self.poll(s,g,r,c);self.assertEqual(r.phase,'closing');self.assertEqual(r.mask,0)
        g.frame+=12;c.update(callback='CB2_UpdatePartyMenu');self.poll(s,g,r,c);self.assertEqual(r.mask,BUTTONS['B'])
        g.frame+=12;c['walk']['open']=True;self.assertTrue(self.poll(s,g,r,c));self.assertEqual(r.result()['reason'],'destination_changed');self.assertFalse(r.result()['teleported'])
    def test_wrong_field_callback_never_confirms_and_cancel_has_no_late_keys(self):
        s,g,r,c=self.runtime();r.phase='prompt';c['tasks']=[dict(name='Task_HandleFieldMoveExitAreaYesNoInput')]
        with self.assertRaises(FieldMismatch):self.poll(s,g,r,c)
        self.assertEqual(r.mask,0);r.mask=BUTTONS['A'];r.cancel();g.frame+=12;self.assertFalse(r.poll(g));self.assertEqual(r.mask,0)
    def test_party_confirmation_waits_for_native_menu_acknowledgement(self):
        s,g,r,c=self.runtime();r.phase='party';c['tasks']=[dict(name='Task_HandleChooseMonInput')]
        c['party_cursor']=1
        self.poll(s,g,r,c);self.assertEqual(r.mask,BUTTONS['A']);self.assertEqual(r.phase,'party')
        g.frame+=12;self.poll(s,g,r,c);self.assertEqual(r.mask,BUTTONS['A']);self.assertEqual(r.phase,'party')
        g.frame+=1;c['tasks']=[dict(name='Task_HandleSelectionMenuInput')]
        self.poll(s,g,r,c);self.assertEqual(r.mask,0);self.assertEqual(r.phase,'options')

    def test_arrival_requires_exact_landing_and_unlocked_controls(self):
        s,g,r,c=self.runtime();r.phase='warping';r.confirmed=True;c['walk'].update(map='VermilionCity',position=[15,7],open=False)
        self.assertFalse(self.poll(s,g,r,c));g.frame+=1;c['walk']['open']=True;self.assertTrue(self.poll(s,g,r,c))
        g.frame+=1;c['walk']['position']=[16,7]
        with self.assertRaises(FieldMismatch):self.poll(s,g,r,c)
    def test_heal_uses_shortcut_or_walking_then_only_one_recovery(self):
        for performed in (False,True):
            t=object.__new__(GrindTrainer);t.root=ROOT;t.clinic='Vermilion';t.preparing=False;t.cycle_number=1;t.farm_pair=[[18,16],[34,16]];t.bot=SimpleNamespace(event=Mock(),teleport_to_clinic=Mock(return_value=dict(teleported=performed)));t.state=lambda:dict(party=[],in_battle=False);t.stage=Mock();t.travel_lead=Mock();t.heal_here=Mock();t.navigator=SimpleNamespace(travel=Mock())
            t.heal();t.bot.teleport_to_clinic.assert_called_once_with('Vermilion');t.navigator.travel.assert_called_once_with('VermilionCity_PokemonCenter_1F',[7,4]);t.heal_here.assert_called_once();self.assertEqual(t.travel_lead.call_count,0 if performed else 1);self.assertEqual(sum(c.args[0]=='cycle_complete' for c in t.bot.event.call_args_list),1)
    def test_forecast_changes_only_return_leg_and_keeps_walk_without_provider(self):
        team=[mon(25,20,'t',[84,98]),mon(64,28,'k',[100,93])];cfg=dict(route='Route1',trainee='t',target=25);p=make_plan(dict(ready=True,party=team,boxes=[]),cfg,ROOT)
        geo=dict(farm=dict(hub='Viridian',pair=[[12,6],[13,6]]),travel_seconds=200,outbound_seconds=100,walk_return_seconds=100,teleport_return_seconds=14)
        tele=forecast_cycle(p,cfg,ROOT,geo,dict(cycles=[],battles=[]));self.assertEqual(tele['return_method'],'teleport');self.assertEqual(tele['components']['travel_seconds'],114)
        p=copy.deepcopy(p);next(m for m in p['team'] if m['uid']=='k')['moves']=[mon(64,28,'k',[93])['moves'][0]]
        walk=forecast_cycle(p,cfg,ROOT,geo,dict(cycles=[],battles=[]));self.assertEqual(walk['return_method'],'walk');self.assertEqual(walk['components']['travel_seconds'],200);self.assertGreater(walk['game_seconds'],tele['game_seconds'])
    def test_actual_walking_fallback_never_calibrates_teleport_forecast(self):
        team=[mon(25,20,'t',[84]),mon(64,28,'k',[100,93])];cfg=dict(route='Route1',trainee='t',target=25);p=make_plan(dict(ready=True,party=team,boxes=[]),cfg,ROOT)
        geo=dict(farm=dict(hub='Viridian',pair=[[12,6],[13,6]]),travel_seconds=200,teleport_return_seconds=14)
        row=dict(id=7,status='completed',target_xp=100,game_seconds=100,battles=1,body=dict(return_method='walk',forecast=dict(return_method='teleport')))
        with patch('pokemon_red.optimizer.compatible_cycles',return_value=[row]):
            tele=forecast_cycle(p,cfg,ROOT,geo,dict(cycles=[],battles=[]));self.assertEqual(tele['evidence']['exact_cycles'],0)
            geo.pop('teleport_return_seconds');walk=forecast_cycle(p,cfg,ROOT,geo,dict(cycles=[],battles=[]));self.assertEqual(walk['evidence']['exact_cycles'],1)
    def test_takeover_cancels_field_request_and_rejects_late_session_input(self):
        with tempfile.TemporaryDirectory() as folder:
            runtime=SimpleNamespace(provider='k',mask=BUTTONS['A']);runtime.cancel=lambda:setattr(runtime,'mask',0)
            a=Automation(Path(folder),snapshot=lambda:{},checkpoint=lambda _:None,set_speed=lambda _:None,release=Mock(),field_installer=lambda _:runtime);session=Session(SimpleNamespace(close=lambda:None));a.session=session;a.safety_profile='training'
            request=Request(session,'field_teleport',dict(clinic='Vermilion'));a._dispatch(request);self.assertFalse(request.done.is_set());a.stop()
            self.assertTrue(request.response['cancelled']);self.assertEqual(runtime.mask,0);self.assertIsNone(a.field_runtime)
            late=Request(session,'field_teleport',dict(clinic='Vermilion'));a.requests.put(late);a.poll();self.assertTrue(late.response['cancelled']);self.assertEqual(a.next_mask(0),0);a.close()

if __name__=='__main__':unittest.main()
