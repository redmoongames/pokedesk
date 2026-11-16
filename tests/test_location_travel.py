"""Location facts, explicit trainer consent, reachability and speed ceilings."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
import copy,json,sys,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.automatic_speed import AutomaticSpeed,automatic_rates
from pokemon_red.run_context import RunConfig
from pokemon_red.location_reference import reference,map_info,moving
from pokemon_red.travel import destination_plan
from pokemon_red.travel_policy import eligible_trainers,trainer_grid,guard,make_policy

class SpeedCapTests(unittest.TestCase):
    def test_every_limit_clamps_initial_speed_and_all_phases(self):
        phases=[{},dict(callback='CB2_Overworld',movement_mode='run'),dict(callback='CB2_UpdatePartyMenu'),dict(callback='BattleMainCB2',battle=True),dict(callback='CB2_Overworld',waiting=True)]
        for maximum in range(1,17):
            values=[];speed=AutomaticSpeed(lambda v,p:values.append(v));speed.configure(True,max_speed=maximum)
            for i,context in enumerate(phases):
                for f in range(30):speed.step(i*30+f,context)
            self.assertTrue(all(1<=v<=maximum for v in values));self.assertLessEqual(max(automatic_rates(maximum)),maximum)
    def test_lowering_a_running_limit_applies_immediately_and_manual_release_still_works(self):
        speed=AutomaticSpeed(Mock());speed.configure(True,max_speed=16)
        for f in range(20):speed.step(f,dict(callback='BattleMainCB2',battle=True))
        self.assertEqual(speed.speed,12);speed.configure(True,max_speed=4);self.assertEqual(speed.speed,4)
        speed.configure(False);self.assertIsNone(speed.speed)
    def test_configuration_is_strict_and_default_is_twelve(self):
        self.assertEqual(RunConfig.parse({}).max_auto_speed,12)
        for value in (0,17,True,'8',8.5,None):
            with self.assertRaises(ValueError):RunConfig.parse(dict(max_auto_speed=value))
        self.assertEqual(RunConfig.parse(dict(max_auto_speed=4)).rules()['max_auto_speed'],4)

class ArrivalPauseTests(unittest.TestCase):
    def test_travel_handoff_pauses_before_checkpoint_and_releasing_control(self):
        from pokemon_red.travel import Traveler
        traveler=object.__new__(Traveler);traveler.bot=Mock();traveler.route='Автопутешествие'
        traveler.handoff('needs_input','Нужно решение')
        calls=traveler.bot.mock_calls;self.assertEqual(calls[0][0],'set_speed');self.assertEqual(calls[0].args,(0,));self.assertEqual(calls[-1][0],'handoff')

class ReferenceTests(unittest.TestCase):
    def test_all_rom_maps_have_reference_and_concrete_event_coordinates(self):
        data=reference(ROOT);self.assertEqual(len(data['maps']),425)
        for name,info in data['maps'].items():
            for obj in info['objects']:self.assertTrue(all(type(v) is int for v in obj['point']),(name,obj))
            for method in info['encounters']:self.assertEqual(sum(r['probability'] for r in method['population']),100,(name,method))
    def test_firered_weights_and_exact_hidden_item_coordinates(self):
        info=map_info(ROOT,'Route1');self.assertEqual({m['species_id']:m['probability'] for m in info['encounters'][0]['population']},{16:50,19:50})
        route=map_info(ROOT,'Route13');item=next(i for i in route['items'] if i['kind']=='hidden');self.assertEqual(item['point'],[23,14]);self.assertEqual(item['name'],'PP UP')
    def test_static_anchor_does_not_change_and_overlay_does_not_mutate_catalog(self):
        before=json.dumps(reference(ROOT));info=map_info(ROOT,'Route2',lambda _:True)
        self.assertTrue(all(i['collected'] for i in info['items'] if i.get('hide_flag')));self.assertEqual(before,json.dumps(reference(ROOT)))
        self.assertFalse(moving(dict(movement='WALK_IN_PLACE_NORMAL_DOWN')));self.assertTrue(moving(dict(movement='WANDER_AROUND')))
    def test_trainer_team_and_starter_gifts_are_real_script_data(self):
        route=map_info(ROOT,'Route3');robin=next(o for o in route['objects'] if any(t['name']=='ROBIN' for t in o['trainers']))
        self.assertEqual(robin['trainers'][0]['party'],[dict(species_id=39,level=14)])
        lab=map_info(ROOT,'PalletTown_ProfessorOaksLab');starters=[o for o in lab['objects'] if o['facts']['pokemon']]
        self.assertEqual({m['species_id'] for o in starters for m in o['facts']['pokemon']},{1,4,7});self.assertTrue(all(o['kind']=='npc' for o in starters))

class TrainerPermissionTests(unittest.TestCase):
    def test_only_ordinary_known_single_trainers_can_be_unblocked(self):
        trainers=[dict(trainer_id=1,trainer_type=1,script_kind=0,defeated=False),dict(trainer_id=2,trainer_type=1,script_kind=4,defeated=False),dict(trainer_id=3,trainer_type=0,script_kind=0,defeated=False)]
        grid=dict(trainers=trainers);value=trainer_grid(grid,[1,2,3]);self.assertEqual([t['trainer_id'] for t in eligible_trainers(grid)],[1]);self.assertEqual([t['defeated'] for t in value['trainers']],[True,False,False]);self.assertFalse(grid['trainers'][0]['defeated'])
    def test_without_consent_no_game_memory_is_read(self):
        game=Mock();self.assertEqual(guard(game,None),dict(scene=False,battle=False));self.assertEqual(guard(game,dict(ids=[])),dict(scene=False,battle=False));game.read8.assert_not_called()
    def test_bad_identifiers_cannot_install_permission(self):
        grid=dict(name='Test',trainers=[])
        for ids in ([True],[-1],['1'],list(range(100))):
            with self.assertRaises(ValueError):make_policy(Mock(),grid,ids)

class ReachabilityTests(unittest.TestCase):
    def fixtures(self):
        leader=dict(uid='one',hp=20,level=20,stats={});inventory=dict(party=[leader],boxes=[])
        state=dict(map=dict(name='Start'));spec=dict(hubs={})
        trip=dict(legs=[dict(source='Start',start=[0,0],destination='End',goal=None,required_tools=['cut'],roster={},plan=dict(cost=[0,12],links=[]))])
        nav=SimpleNamespace(t=SimpleNamespace(state=lambda:state),spec=spec,itinerary=Mock(side_effect=RuntimeError('Нет пути')))
        allowed=SimpleNamespace(spec=spec,itinerary=Mock(return_value=trip))
        return nav,allowed,inventory,trip
    def test_battle_blocker_explains_checkbox_and_cannot_become_startable_without_it(self):
        nav,allowed,inv,_=self.fixtures()
        with patch('pokemon_red.travel.battle_requirements',return_value={'Road':[42]}):
            row=destination_plan(nav,allowed,Mock(),inv,'End',False)
            self.assertFalse(row['reachable']);self.assertTrue(row['can_battle']);self.assertIn('Сражаться',row['reason'])
            row=destination_plan(nav,allowed,Mock(),inv,'End',True)
            self.assertTrue(row['reachable']);self.assertEqual(row['trainer_ids'],{'Road':[42]});self.assertEqual(row['tools'],['cut'])
    def test_safe_route_is_preferred_even_when_trainers_are_allowed(self):
        nav,allowed,inv,trip=self.fixtures();nav.itinerary=Mock(return_value=trip)
        row=destination_plan(nav,allowed,Mock(),inv,'End',True)
        self.assertTrue(row['reachable']);self.assertEqual(row['trainer_ids'],{});allowed.itinerary.assert_not_called()
    def test_missing_tools_or_story_passage_never_turn_into_trainer_permission(self):
        nav,allowed,inv,_=self.fixtures();nav.itinerary=Mock(side_effect=ValueError('Нет значка для Cut'));allowed.itinerary=Mock(side_effect=ValueError('Нет значка для Cut'))
        row=destination_plan(nav,allowed,Mock(),inv,'End',True);self.assertFalse(row['reachable']);self.assertIn('значка',row['reason'])

    def test_unsupported_current_map_is_explained_as_navigation_limit(self):
        from pokemon_red.travel import destinations,reachability_summary
        nav,allowed,inv,_=self.fixtures();nav.t.state=lambda:dict(map=dict(name='Start'),position=dict(x=1,y=2));nav.spec['links']=[]
        with patch('pokemon_red.travel.navigator',return_value=nav),patch('pokemon_red.travel.reference',return_value=dict(maps={'Start':{},'End':{}})):
            result=destinations(ROOT,nav.t.state(),inv,Mock())
        self.assertTrue(result['rows'][0]['current']);self.assertIn('ограничение навигации',reachability_summary(result))

    def test_summary_explains_additional_routes_requiring_trainer_permission(self):
        from pokemon_red.travel import reachability_summary
        self.assertIn('ещё 1',reachability_summary(dict(rows=[dict(reachable=True),dict(reachable=False,can_battle=True)])))


class LocationViewTests(unittest.TestCase):
    def test_map_reference_is_built_once_while_player_coordinates_change(self):
        import tkinter as tk
        from pokemon_red.location_view import LocationView
        window=tk.Tk();window.withdraw()
        try:
            state=dict(ready=True,map=dict(name='Route1'),position=dict(x=4,y=3))
            game=SimpleNamespace(read32=lambda _:0)
            monitor=SimpleNamespace(folder=ROOT,last_state=state,generation=1,location_info=Mock(side_effect=lambda name:map_info(ROOT,name)),watch=lambda value,success,failure:success(value))
            panel=SimpleNamespace(monitor=monitor,open_pokemon=Mock())
            view=LocationView(panel,tk.Frame(window))
            with patch.object(monitor,'location_info',wraps=monitor.location_info) as lookup:
                for x in range(20):state['position']['x']=x;view.refresh(state)
                self.assertEqual(lookup.call_count,1);self.assertIn('19',view.position.cget('text'))
                self.assertEqual(len(view.encounter_photos),sum(len(method['population']) for method in map_info(ROOT,'Route1')['encounters']))
                view.refresh(state,force=True);self.assertEqual(lookup.call_count,2)
        finally:window.destroy()
    def test_destination_keyboard_navigation_selects_and_explains_rows(self):
        from pokemon_red.location_view import TravelWindow
        window=object.__new__(TravelWindow);selected=[]
        window.tree=SimpleNamespace(get_children=lambda:['a','b','c'],selection=lambda:selected,selection_set=lambda key:selected.__setitem__(slice(None),[key]),focus=Mock(),see=Mock());window.select=Mock()
        window.move_selection(1);self.assertEqual(selected,['a']);window.move_selection(1);self.assertEqual(selected,['b']);window.move_selection(-1,edge=True);self.assertEqual(selected,['c'])
    def test_buttons_remain_inside_the_travel_window(self):
        import tkinter as tk
        from pokemon_red.location_view import TravelWindow
        root=tk.Tk();root.withdraw()
        try:
            state=dict(ready=True,map=dict(name='Route1'),position=dict(x=4,y=3))
            monitor=SimpleNamespace(folder=ROOT,last_state=state,generation=1,travel_snapshot=lambda:dict(state=b'copy',generation=1),watch=lambda value,success,failure:success(value),operation=None,automation=SimpleNamespace(info=lambda:dict(running=False)),take_control=Mock())
            with patch('pokemon_red.location_view.TravelService') as service:
                service.return_value.poll.return_value=None
                view=TravelWindow(SimpleNamespace(monitor=monitor,panel=SimpleNamespace(window=root)));view.window.withdraw();view.window.update_idletasks()
                bottom=view.start.winfo_rooty()+view.start.winfo_height()-view.window.winfo_rooty()
                self.assertLessEqual(bottom,view.window.winfo_height());view.close()
        finally:root.destroy()

if __name__=='__main__':unittest.main()
