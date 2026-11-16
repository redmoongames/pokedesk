"""Party identity, embedded training navigation and the early Route 1 policy."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
import sys,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.training_view import starter_training
from pokemon_red.i18n import t,set_locale,get_locale
from pokemon_red.optimizer import make_training_plan,PlanningUnavailable
from test_grind import mon

class EarlyTrainingTests(unittest.TestCase):
    def test_weak_single_starter_can_plan_ordinary_route1_without_relaxing_fast_policy(self):
        target=mon(1,6,'starter',[33,45]);target['stats']['attack']=9;inventory=dict(ready=True,party=[target],boxes=[]);cfg=dict(route='Route1',trainee='starter',target=10)
        geometry=dict(farm=dict(hub='Viridian',pair=[[12,6],[13,6]],cost=[0,40]),travel_seconds=20,preparation_seconds=10,preparation_steps=40)
        with patch('pokemon_red.optimizer.route_geometry',return_value=geometry):
            with self.assertRaises(PlanningUnavailable) as error:make_training_plan(inventory,dict(cfg,training_policy='coverage'),ROOT,navigator=object(),evidence=dict(cycles=[],battles=[]))
            self.assertTrue(error.exception.excluded);self.assertEqual(error.exception.excluded[0]['route'],'Route1')
            plan=make_training_plan(inventory,dict(cfg,training_policy='eta'),ROOT,navigator=object(),evidence=dict(cycles=[],battles=[]))
        self.assertEqual(plan['route'],'Route1');self.assertIn('starter',plan['fighters']);self.assertGreater(plan['expected_attacks'],2)
    def test_starter_recommendation_is_scoped_to_early_solo_kanto_team(self):
        starter=dict(uid='a',species_id=1,level=6);state=dict(map=dict(name='Route1'))
        self.assertTrue(starter_training(dict(party=[starter],boxes=[]),'a',state))
        self.assertFalse(starter_training(dict(party=[starter],boxes=[dict(uid='b')]),'a',state))
        self.assertFalse(starter_training(dict(party=[dict(starter,level=30)],boxes=[]),'a',state))
        self.assertFalse(starter_training(dict(party=[starter],boxes=[]),'a',dict(map=dict(name='Route11'))))
    def test_english_battle_label_is_not_a_transliteration(self):
        previous=get_locale()
        try:set_locale('en');self.assertEqual(str(t('battle.auto')),'Auto Battle')
        finally:set_locale(previous)

class PartyNavigationTests(unittest.TestCase):
    def setUp(self):
        from test_trainer_navigation import EmbeddedNavigationTests
        self._case=EmbeddedNavigationTests();self._case.setUp();self.panel=self._case.panel;self.root=self._case.root;self.mon=self._case.mon
    def tearDown(self):self._case.tearDown()
    def test_party_mark_and_training_button_use_exact_uid_not_species(self):
        p=self.panel;page=p.open_pokemon(self.mon).page;self.root.update();self.assertTrue(page.party_badge.winfo_manager());self.assertTrue(page.train_button.winfo_manager())
        p.monitor.last_state=dict(party=[dict(self.mon,uid='other')]);page.refresh(p.monitor.last_state);self.assertFalse(page.party_badge.winfo_manager());self.assertFalse(page.train_button.winfo_manager())
        p.details.clear();page=p.open_pokemon(species_id=self.mon['species_id']).page;self.root.update();self.assertFalse(page.party_badge.winfo_manager());self.assertTrue(page.train_button.winfo_manager())
    def test_training_and_its_back_button_reuse_trainer_window_and_pokemon_page(self):
        from pokemon_red.automation_windows import AutomationWindows
        p=self.panel;m=p.monitor;m.settings={'speed':1};m.planning_end=Mock();m.automation=SimpleNamespace(info=lambda:dict(running=False,status='idle',reason=''),running=False);m.history=SimpleNamespace(run=None,completed_write=None,completed_revision=0,stats_revision=0,local_revision=0,comparisons=lambda:[],cycles=lambda:[])
        m.pending_start=False;m.paused=True;m.automatic_speed_info={};m.bot_snapshot=lambda:m.last_state
        p.automation_windows=AutomationWindows(p);p.open_training=p.automation_windows.open_training;p.inspect_uid=p.open_pokemon
        original=p.open_pokemon(self.mon);self.root.update();page=original.page;page.learnset.query.set('PSYCHIC');before=[w for w in self.root.winfo_children() if isinstance(w,self._case.tk.Toplevel)]
        view=page.open_training();self.root.update();self.assertEqual(view.trainee.get(),self.mon['uid']);self.assertEqual(p.details.history.routes[-1].kind,'training');self.assertTrue(view.embedded)
        self.assertEqual([w for w in self.root.winfo_children() if isinstance(w,self._case.tk.Toplevel)],before)
        p.details.back();self.root.update();self.assertIs(p.details.screens[-1],original);self.assertEqual(page.learnset.query.get(),'PSYCHIC');self.assertTrue(view.closed)
