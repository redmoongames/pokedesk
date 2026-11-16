"""Nurse recovery and both former duplicate-healing capture call sites."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1];sys.path.insert(0, str(ROOT / 'src'))
from pokemon_red.acquisition_play import Player, AcquisitionAttention, JobPaused
from pokemon_red.grass_search import prepare_grass
from pokemon_red.autocatch import run_autocatch
from pokemon_red.journey import Journey


def observation():
    return dict(ready=True,telemetry_valid=True,in_battle=False,map=dict(name='Clinic'),
                controls=dict(callback='CB2_Overworld',field_locked=False),
                party=[dict(uid='hunter',hp=30,max_hp=30,status_code=0,checksum_valid=True,
                            moves=[dict(id=79,current_pp=15,max_pp=15)])])


class NurseTests(unittest.TestCase):
    def player(self, state):
        player = object.__new__(Player);player.g = Mock(root=ROOT);player.w = Mock();player.learning = None
        player.state = Mock(side_effect=lambda:deepcopy(state));player.go = Mock()
        started = [False]
        def nurse(key, **kwargs):
            if key != 'A':return
            if started[0]:state['controls']['field_locked'] = False;return
            started[0] = True;state['controls']['field_locked'] = True
            for mon in state['party']:
                mon.update(hp=mon['max_hp'],status_code=0)
                for move in mon['moves']:move['current_pp'] = move['max_pp']
        player.tap = Mock(side_effect=nurse)
        return player

    def test_healthy_calls_send_no_movement_or_buttons(self):
        player = self.player(observation())
        for _ in range(4):self.assertIs(player.heal(), False)
        player.tap.assert_not_called();player.go.assert_not_called();player.g.advance.assert_not_called()

    def test_restores_all_resources_once_and_repeated_calls_are_noops(self):
        state = observation();state['party'][0].update(hp=0,status_code=8);state['party'][0]['moves'][0]['current_pp'] = 0
        player = self.player(state)
        with patch('pokemon_red.zones.zone_spec',return_value={'hubs':{'clinic':{'map':'Clinic','nurse':[7,4]}}}):
            self.assertIs(player.heal(), True);count = player.tap.call_count
            for _ in range(4):self.assertIs(player.heal(), False)
        self.assertEqual(player.tap.call_count, count);player.go.assert_called_once_with((7,4))

    def test_invalid_telemetry_or_scene_sends_no_input(self):
        for change in ('checksum', 'transient', 'dialog', 'battle'):
            state = observation()
            if change == 'checksum':state['party'][0]['checksum_valid'] = False
            elif change == 'transient':state['telemetry_valid'] = False
            elif change == 'dialog':state['controls']['field_locked'] = True
            else:state['in_battle'] = True
            player = self.player(state)
            with self.subTest(change=change), self.assertRaises(AcquisitionAttention):player.heal()
            player.tap.assert_not_called();player.go.assert_not_called()

    def test_cancel_before_nurse_input_keeps_per_frame_guard(self):
        state = observation();state['party'][0]['hp'] = 1;player = self.player(state)
        player.w.before_frame.side_effect = JobPaused;player.tap = Player.tap.__get__(player)
        with patch('pokemon_red.zones.zone_spec',return_value={'hubs':{}}),self.assertRaises(JobPaused):player.heal()
        player.g.advance.assert_not_called()

    def test_unconfirmed_healing_times_out_without_restarting_nurse(self):
        state = observation();state['party'][0]['hp'] = 1;player = self.player(state);player.tap = Mock()
        with patch('pokemon_red.zones.zone_spec',return_value={'hubs':{}}),self.assertRaisesRegex(AcquisitionAttention,'Лечение не подтвердилось'):player.heal()
        player.go.assert_called_once();self.assertLess(player.tap.call_count, 230)


class CaptureCallSites(unittest.TestCase):
    class ReachedLead(Exception):pass

    def player(self):
        player = Mock();state = observation();state['map']['name'] = 'Route1';state['party'][0]['hp'] = 1
        player.g.root = ROOT;player.capture_hunter = 'hunter';player.state.return_value = state
        player.center.side_effect = lambda:player.heal()
        player.lead.side_effect = self.ReachedLead
        return player

    def test_grass_frontier_heals_only_once_before_return_to_grass(self):
        player = self.player()
        with self.assertRaises(self.ReachedLead):prepare_grass(player,dict(map='Route1'))
        player.center.assert_called_once();player.heal.assert_called_once()

    def test_autocatch_heals_only_once_before_return_to_hunting(self):
        player = self.player();context = dict(selected=dict(map='Route1',method='land_mons'),initial=[],hunter='hunter')
        with patch('pokemon_red.autocatch.CaptureTarget.parse'),patch('pokemon_red.autocatch.prepare_hunt',return_value=context),patch('pokemon_red.telemetry.read_walk_state',return_value={'battle_pending':False}),self.assertRaises(self.ReachedLead):run_autocatch(player,{})
        player.center.assert_called_once();player.heal.assert_called_once()

    def test_center_contract_returns_hub_after_one_ensure_heal(self):
        player = Mock();hub = dict(map='Clinic',nurse=[7,4]);player.nav.nearest_clinic.return_value = ('clinic',0);player.nav.spec = {'hubs':{'clinic':hub}}
        self.assertIs(Journey.center(player), hub)
        player.nav.travel.assert_called_once_with('Clinic',[7,4]);player.heal.assert_called_once()
