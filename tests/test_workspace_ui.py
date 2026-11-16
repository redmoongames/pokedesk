"""Real trainer navigation and async editor launch on private copied Data."""
from pathlib import Path
import sys,shutil,time,threading,json
from unittest.mock import Mock
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
import test_engine_runtime as actor
from test_runtime_performance import PrivateSessionTestCase
from pokemon_red.engine_runtime import EngineRuntime
from pokemon_red.models import read_inventory
from pokemon_red.telemetry import read_state,read_map,read_field_badges
from pokemon_red.party_management import roster_plan


class WorkspaceUITests(PrivateSessionTestCase):
    def setUp(self):
        import tkinter as tk
        import gc
        from pokemon_red.gui import Monitor
        gc.collect();super().setUp()
        self.window=tk.Tk();self.window.withdraw();self.errors=[]
        self.monitor=Monitor(self.window,self.root,paused=True,runtime_factory=actor.ProbeRuntime)
        self.monitor.show_battle_panel=lambda:None
        self.window.report_callback_exception=lambda _,e,t:self.errors.append(str(e))
        self.drive(lambda:self.monitor.ready)
    drive=actor.GuiActorTests.drive
    probe=actor.GuiActorTests.probe
    def tearDown(self):
        if not self.monitor.closed:
            self.monitor.close();self.drive(lambda:self.monitor.closed,8)
        self.monitor.runtime.thread.join(2);super().tearDown()
        self.monitor=None;self.window=None
        import gc
        gc.collect()


def prepare(case):
    m=case.monitor
    snapshot=(ROOT/'tests/fixtures/fire_red/clinic.state').read_bytes()
    def restore(c):
        c.game.restore_checkpoint(snapshot);c.game.advance(30);c.last_state=c.session_state();c.inventory_snapshot();c.dirty=True
    case.probe(restore);case.drive(lambda:m.last_state.get('ready',False))
    m.show_panel('overview');case.window.update();case.drive(lambda:m.last_inventory.get('ready',False))
    return m.panel


def test_sections_keep_nested_pokemon_filters_and_party_draft(case):
    p=prepare(case);m=case.monitor
    case.assertEqual(set(p.main_buttons),{'collection','inventory','location','tasks'})
    case.assertEqual(p.collection_view.current,'party')
    screen=p.open_pokemon(mon=m.last_state['party'][0]);page=screen.page
    page.learnset.query.set('PSYCHIC');p.show('inventory');case.window.update()
    case.assertFalse(p.details.active);p.inventory_view.query.set('Potion')
    p.show('collection');case.window.update()
    case.assertIs(p.details.screens[0],screen);case.assertEqual(page.learnset.query.get(),'PSYCHIC')
    p.details.back();editor=p.open_party_editor().editor
    editor.desired.reverse();before=list(editor.desired)
    p.show('tasks');p.show('collection');case.window.update()
    case.assertIs(p.details.screens[-1].editor,editor);case.assertEqual(editor.desired,before)
    p.details.back();case.assertEqual(p.open_party_editor().editor.desired,before)
    p.show('inventory');case.assertEqual(p.inventory_view.query.get(),'Potion')


def test_editor_preview_is_async_and_f9_revokes_pending_apply(case):
    p=prepare(case);m=case.monitor;editor=p.open_party_editor().editor
    editor.desired=[m.last_inventory['boxes'][0]['uid'],m.last_state['party'][0]['uid']]
    editor.changed();at=time.perf_counter();editor.prepare()
    case.assertLess(time.perf_counter()-at,.15)
    case.drive(lambda:editor.plan is not None,12)
    case.assertEqual(editor.plan['destination'],'Route4_PokemonCenter_1F')
    case.assertEqual(editor.apply.cget('state'),'normal')
    entered=threading.Event();release=threading.Event()
    writer_futures=[]
    def block_writer(c):writer_futures.append(c.writer.submit(lambda:(entered.set(),release.wait(5))))
    case.probe(block_writer);case.assertTrue(entered.wait(1));writer_future=writer_futures[0]
    before=[m['uid'] for m in m.last_state['party']]
    try:
        editor.start();case.drive(lambda:m.status.get('pending_start',False))
        epoch=m.runtime.take_control(pause=True);case.drive(lambda:m.model.epoch>=epoch)
        release.set();writer_future.result(3)
        case.drive(lambda:not m.status.get('saving'))
        case.assertFalse(m.automation.running);case.assertFalse(m.status['pending_start'])
        case.assertEqual([m['uid'] for m in m.last_state['party']],before)
    finally:release.set()


def test_selected_world_reference_and_f1_do_not_follow_automation(case):
    p=prepare(case);m=case.monitor;p.show('location');v=p.location_view
    v.selected_map='Route1';v.refresh(force=True);case.drive(lambda:v.map=='Route1')
    p.show('inventory');p.inventory_view.query.set('Potion');m.show_panel()
    case.assertEqual(p.active_section,'inventory');case.assertEqual(p.inventory_view.query.get(),'Potion')
    p.show('location');case.assertEqual(v.selected_map,'Route1')


WorkspaceUITests.test_sections_keep_nested_pokemon_filters_and_party_draft=test_sections_keep_nested_pokemon_filters_and_party_draft
WorkspaceUITests.test_editor_preview_is_async_and_f9_revokes_pending_apply=test_editor_preview_is_async_and_f9_revokes_pending_apply
WorkspaceUITests.test_selected_world_reference_and_f1_do_not_follow_automation=test_selected_world_reference_and_f1_do_not_follow_automation
