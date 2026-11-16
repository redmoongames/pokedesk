"""Adaptive gait, directed portal caching and per-leg utility constraints."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,Mock
import copy,sys,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.movement import movement_mode,WalkSegment,safe_step
from pokemon_red.engine import BUTTONS
from pokemon_red.automatic_speed import decide
from pokemon_red.portal_graph import PortalGraph
from pokemon_red.path_cache import PathCache,map_key
from pokemon_red.training import path_to,paths_to
from pokemon_red.field_tools import utility_team
from pokemon_red.travel_plan import itinerary
from test_movement import grid,sample

class GaitTests(unittest.TestCase):
    def test_short_approaches_locked_shoes_and_forbidden_maps_walk(self):
        self.assertEqual(movement_mode(dict(can_run=True),4),'run')
        for state,count in ((dict(can_run=True),3),(dict(can_run=False),14),({},14)):
            self.assertEqual(movement_mode(state,count),'walk')
    def test_running_releases_both_keys_before_arrival_and_on_all_interruptions(self):
        w=WalkSegment('TestMap',(2,4),(10,4),100,mode='run')
        self.assertEqual(w.next(sample(can_run=True))[0],BUTTONS['RIGHT']|BUTTONS['B'])
        self.assertEqual(w.next(sample(x=10,moving=True,frame=166,can_run=True)),(0,None))
        self.assertEqual(w.next(sample(x=10,frame=174,can_run=True))[1]['reason'],'reached')
        for change in (dict(open=False),dict(in_battle=True),dict(map='Other'),dict(actors=[[6,4]])):
            w=WalkSegment('TestMap',(2,4),(10,4),100,mode='run')
            self.assertEqual(w.next(sample(can_run=True,**change))[0],0)
    def test_other_transport_never_receives_direction_or_B(self):
        w=WalkSegment('TestMap',(2,4),(10,4),100,mode='run')
        self.assertEqual(w.next(sample(on_foot=False,can_run=False)),(0,dict(reason='unsupported_transport',start_frame=100,end_frame=100,position=[2,4],goal=[10,4],tiles=0,mode='run')))
    def test_permission_revocation_drops_B_immediately(self):
        w=WalkSegment('TestMap',(2,4),(10,4),100,mode='run')
        self.assertEqual(w.next(sample(can_run=False))[0],BUTTONS['RIGHT']);self.assertEqual(w.mode,'walk')
    def test_run_rate_does_not_override_menus_or_unknown_script(self):
        self.assertEqual(decide(dict(callback='CB2_Overworld',movement_mode='run',directional=True)).speed,4)
        self.assertEqual(decide(dict(callback='CB2_Overworld',movement_mode='walk')).speed,8)
        self.assertEqual(decide(dict(callback='CB2_Overworld',movement_mode='run',locked=True)).speed,8)
        self.assertEqual(decide(dict(callback='CB2_UpdatePartyMenu',movement_mode='run')).speed,4)
    def test_precision_cell_releases_on_entry_and_blocks_actual_npc_not_neighbor(self):
        g=grid();self.assertTrue(safe_step(g,(2,4),(3,4)))
        for kind in ('obstacles','script_triggers'):
            g=grid();g[kind]=[[3,4]];self.assertFalse(safe_step(g,(2,4),(3,4)))
        w=WalkSegment('TestMap',(2,4),(3,4),100,precision=True)
        self.assertEqual(w.next(sample(actors=[[3,3]]))[0],BUTTONS['RIGHT'])
        self.assertEqual(w.next(sample(x=3,moving=True,frame=102))[0],0)
        self.assertEqual(w.next(sample(x=3,frame=120))[1]['reason'],'reached')
        w=WalkSegment('TestMap',(2,4),(3,4),100,precision=True)
        self.assertEqual(w.next(sample(actors=[[3,4]]))[1]['reason'],'obstacle')

class RpcGaitTests(unittest.TestCase):
    def test_server_selects_gait_but_precision_and_field_owner_never_hold_B(self):
        import test_movement as fixtures
        from pokemon_red.automation import Request
        fixture=fixtures.ControllerWalkingTests();fixture.setUp()
        try:
            fixture.state=sample(can_run=True)
            request=fixture.request();self.assertEqual(fixture.c.action['walk'].mode,'run')
            self.assertEqual(fixture.c.next_mask(0),BUTTONS['RIGHT']|BUTTONS['B'])
            fixture.state=sample(can_run=True,x=10,frame=174);fixture.c.next_mask(0)
            fixture.state=sample(can_run=True,x=10,frame=176)
            request=Request(fixture.session,'walk_step',dict(map='TestMap',start=[10,4],goal=[11,4]))
            fixture.c._dispatch(request);self.assertEqual(fixture.c.next_mask(0),BUTTONS['RIGHT'])
            fixture.c.field_runtime=SimpleNamespace(mask=BUTTONS['A'],cancel=lambda:None)
            self.assertEqual(fixture.c.next_mask(0),BUTTONS['A'])
            fixture.c.field_runtime=None;fixture.c.stop();self.assertEqual(fixture.c.next_mask(0),0)
        finally:fixture.tearDown()
    def test_new_sdk_preserves_movement_with_an_already_open_old_game(self):
        from pokemon_red.bot import Bot
        b=object.__new__(Bot);b._call=Mock(side_effect=RuntimeError('Неизвестная команда API'))
        self.assertEqual(b.walk_step('Map',(1,1),(2,1)),dict(reason='legacy'))
        self.assertEqual(b.walk_step('Map',(1,1),(2,1)),dict(reason='legacy'));self.assertEqual(b._call.call_count,1)


class GraphTests(unittest.TestCase):
    def test_one_sweep_builds_all_directed_exits_and_survives_disk_reopen(self):
        g=grid();spec=dict(links=[dict(source='TestMap',point=[2,4],destination='Other',arrival=[1,1]),dict(source='TestMap',point=[12,4],destination='Third',arrival=[1,1])],hubs={'c':dict(map='TestMap',nurse=[6,8])})
        atlas=PortalGraph(spec)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'vendor').symlink_to(ROOT/'vendor');cache=PathCache(root)
            with patch('pokemon_red.portal_graph.paths_to',wraps=paths_to) as find:
                atlas.connect('TestMap',(2,4),(12,4),g,map_key(g),cache)
                atlas.connect('TestMap',(2,4),(6,8),g,map_key(g),cache)
                self.assertEqual(find.call_count,1)
            cache.close();cache=PathCache(root)
            with patch('pokemon_red.portal_graph.paths_to',side_effect=AssertionError('recomputed')):
                self.assertTrue(atlas.connect('TestMap',(2,4),(6,8),g,map_key(g),cache)['ok'])
            g['obstacles']=[[8,4]]
            value=atlas.connect('TestMap',(2,4),(12,4),g,map_key(g),cache)
            self.assertNotIn((8,4),map(tuple,value['value']));cache.close()
    def test_batch_matches_exact_heading_search_and_does_not_reverse_ledge(self):
        g=grid();goals=[(12,4),(5,8),(2,2)];g['obstacles']=[[7,y] for y in range(3,7)]
        batch=paths_to(g,(2,4),goals)
        for goal in goals:self.assertEqual(batch[goal],path_to(g,(2,4),goal))
        for y in range(10):g['tiles'][y][6]=[1,0x38,3,0]
        self.assertIn((9,4),paths_to(g,(4,4),[(9,4)]));self.assertNotIn((4,4),paths_to(g,(9,4),[(4,4)]))


def mon(uid,moves=(),**kw):return dict(dict(uid=uid,moves=[dict(id=m) for m in moves],checksum_valid=True,is_egg=False,hp=20,level=20),**kw)

class UtilityTests(unittest.TestCase):
    def test_pinned_provider_uses_no_extra_slot_and_duplicate_roles_are_shared(self):
        inv=dict(party=[mon('learner',[15]),mon('fighter')],boxes=[mon('other',[15])],field_badges=[2])
        roster=utility_team(inv,['cut'],pinned=['learner','learner'],preferred=['fighter'])
        self.assertEqual(roster['team_uids'],['learner','fighter']);self.assertEqual(roster['utility_uids'],['learner'])
    def test_minimum_provider_cover_can_replace_a_filler_but_never_pinned_or_mail(self):
        party=[mon('p'+str(i)) for i in range(6)];party[-1]['held_item']=121
        inv=dict(party=party,boxes=[mon('tool',[15])],field_badges=[2])
        roster=utility_team(inv,['cut'],pinned=['p0','p1'],preferred=[m['uid'] for m in party])
        self.assertEqual(len(roster['team_uids']),6);self.assertTrue({'p0','p1','p5','tool'}<=set(roster['team_uids']))
        with self.assertRaises(ValueError):utility_team(inv,['cut'],pinned=[m['uid'] for m in party])
    def test_owned_move_does_not_grant_badge_or_unsupported_executor(self):
        inv=dict(party=[mon('tool',[15,57])],boxes=[],field_badges=[])
        with self.assertRaisesRegex(ValueError,'значка'):utility_team(inv,['cut'])
        inv['field_badges']=[2,5]
        with self.assertRaisesRegex(ValueError,'автоматизировано'):utility_team(inv,['surf'])
    def test_multiple_tools_use_one_provider_and_free_previous_leg_reservation(self):
        inv=dict(party=[mon('fighter'),mon('cut',[15])],boxes=[mon('both',[15,57])],field_badges=[2,5])
        from pokemon_red.field_tools import TOOLS
        with patch.dict(TOOLS,{'surf':dict(TOOLS['surf'],automatic=True)}):
            roster=utility_team(inv,['cut','surf'],pinned=['fighter'],preferred=['fighter'])
            self.assertEqual(roster['utility_uids'],['both'])
        next_leg=utility_team(inv,[],pinned=['fighter'],preferred=['fighter'])
        self.assertEqual(next_leg['utility_uids'],[])

class ItineraryTests(unittest.TestCase):
    def test_centers_split_local_requirements_and_boxed_cut_is_not_used_before_pc(self):
        inv=dict(party=[mon('fighter')],boxes=[mon('tool',[15])],field_badges=[2])
        initial=dict(field_actions=[],links=[],arrival=(1,1),cost=(0,5))
        def plan(source,start,destination,goal=None,**_):
            actions=[dict(tool='cut')] if source=='C1' else []
            links=[dict(destination='Town2')] if source=='C1' and destination=='End' else []
            return dict(field_actions=actions,links=links,arrival=goal or (1,1),cost=(0,5))
        nav=SimpleNamespace(t=SimpleNamespace(state=lambda:dict(map=dict(name='Road'),position=dict(x=1,y=1))),tool_inventory=inv,
            spec=dict(hubs={'a':dict(map='C1',nurse=[1,1]),'b':dict(map='C2',nurse=[1,1])},links=[dict(source='Town2',destination='C2')]),
            plan=Mock(side_effect=plan),nearest_clinic=Mock(return_value=('a',initial)))
        trip=itinerary(nav,'End',(9,9),pinned=['fighter'],preferred=['fighter'])
        self.assertEqual([l['destination'] for l in trip['legs']],['C1','C2','End'])
        self.assertFalse(trip['legs'][0]['prepare']);nav.nearest_clinic.assert_called_once_with(('End',(9,9)),before_preparation=True)
        self.assertEqual(trip['legs'][1]['required_tools'],['cut']);self.assertEqual(trip['legs'][2]['required_tools'],[])

if __name__=='__main__':unittest.main()
