"""Actor integration on private saves: ownership, frame safety and UI liveness."""
from pathlib import Path
from types import SimpleNamespace
from concurrent.futures import CancelledError
from unittest.mock import patch,Mock
import socket,sys,time,threading,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.engine import Game,BUTTONS
from pokemon_red.engine_runtime import EngineRuntime
from pokemon_red.automation import Session,Request
from test_runtime_performance import PrivateSessionTestCase


class ProbeRuntime(EngineRuntime):
    """Test-only injection, executed on the owner. Production accepts no callable."""
    def _dispatch(self,c,method,args):
        if method=='probe':return args[0](c)
        return super()._dispatch(c,method,args)


class ActorTests(PrivateSessionTestCase):
    def setUp(self):
        super().setUp();self.runtime=ProbeRuntime(self.root,paused=True);self.runtime.ready.result(5)
    def probe(self,fn):return self.runtime.submit('probe',fn).result(5)
    def wait(self,predicate,timeout=3):
        end=time.monotonic()+timeout
        while not predicate() and time.monotonic()<end:time.sleep(.001)
        self.assertTrue(predicate())
    def tearDown(self):
        if not self.runtime.finished.done():self.runtime.take_control(close=True)
        self.runtime.finished.result(8);self.runtime.thread.join(1)
        self.assertFalse(self.runtime.thread.is_alive());super().tearDown()
    def test_native_core_and_every_guard_have_one_non_ui_owner(self):
        owner=self.probe(lambda c:(threading.get_ident(),c.game.owner_thread,c.automation.thread))
        self.assertEqual(len(set(owner)),1);self.assertNotEqual(owner[0],threading.get_ident())
        checks=[]
        def install(c):
            original=c.game.advance
            def advance(frames=1,keys=0):checks.append(threading.get_ident());return original(frames,keys)
            c.game.advance=advance;c.set_speed(16)
        self.probe(install);time.sleep(.05);self.runtime.take_control(pause=True)
        self.wait(lambda:self.runtime.latest.status['paused'])
        self.assertGreater(len(checks),10);self.assertEqual(set(checks),{owner[0]})
        self.assertTrue(self.runtime.latest.video.startswith(b'P6\n240 160\n255\n'))
    def test_location_and_travel_snapshots_are_captured_on_owner(self):
        owners=[]
        def facts(root,name,flag):
            owners.append(threading.get_ident());return dict(name=name,flag=flag(0))
        with patch('pokemon_red.location_reference.map_info',side_effect=facts):
            info=self.runtime.submit('location_info','Route1').result(3)
        snapshot=self.runtime.submit('travel_snapshot').result(3)
        self.assertEqual(info['name'],'Route1');self.assertTrue(snapshot['state'])
        self.assertEqual(snapshot['generation'],self.runtime.latest.generation)
        self.assertEqual(owners,[self.runtime.thread.ident]);self.assertNotEqual(owners[0],threading.get_ident())
    def test_takeover_bypasses_full_queue_and_revokes_stale_manual_commands(self):
        gate,entered=threading.Event(),threading.Event()
        blocked=self.runtime.submit('probe',lambda c:(entered.set(),gate.wait(3)))
        self.assertTrue(entered.wait(1))
        stale=[self.runtime.submit('manual','A',True) for _ in range(self.runtime.capacity)]
        overflow=self.runtime.submit('manual','A',True)
        with self.assertRaisesRegex(RuntimeError,'заполнена'):overflow.result()
        try:
            at=time.perf_counter();epoch=self.runtime.take_control();self.assertLess(time.perf_counter()-at,.01)
            gate.set();self.wait(lambda:self.runtime.latest.epoch>=epoch)
            self.assertEqual(self.probe(lambda c:sorted(c.keys)),[])
            for f in stale:
                with self.assertRaises(CancelledError):f.result(3)
        finally:gate.set()
    def test_takeover_during_inflight_frame_allows_no_old_mask_after_ack(self):
        entered,release=threading.Event(),threading.Event();masks=[];request=[]
        def setup(c):
            original=c.game.advance
            def advance(frames=1,keys=0):
                if frames:
                    masks.append((self.runtime.applied_epoch,keys));entered.set();release.wait(3)
                return original(frames,keys)
            c.game.advance=advance;c.automation.session=Session(socket.socket())
            r=Request(c.automation.session,'press',dict(button='A',frames=1000));request.append(r);c.automation._dispatch(r);c.set_speed(16)
        self.probe(setup);self.assertTrue(entered.wait(1))
        try:
            epoch=self.runtime.take_control();release.set();self.wait(lambda:self.runtime.latest.epoch>=epoch)
            self.runtime.submit('manual','UP',True).result(2);time.sleep(.02)
            self.assertTrue(request[0].response['cancelled'])
            self.assertFalse(any(keys&BUTTONS['A'] for e,keys in masks if e>=epoch))
            self.assertTrue(any(keys&BUTTONS['UP'] for e,keys in masks if e>=epoch))
        finally:release.set()
    def test_frame_guard_still_interrupts_before_second_button(self):
        masks=[]
        def setup(c):
            start=c.game.frame;original=c.game.advance
            def advance(frames=1,keys=0):
                if frames:masks.append(keys)
                return original(frames,keys)
            def guard():
                if c.game.frame>start:c.paused=True;return True
                return False
            c.game.advance=advance;c.check_training_decision=guard
            c.automation.session=Session(socket.socket());c.automation._dispatch(Request(c.automation.session,'press',dict(button='A',frames=200)))
            c.set_speed(16)
        self.probe(setup);self.wait(lambda:bool(masks));time.sleep(.03)
        self.assertEqual(masks,[BUTTONS['A']]);self.assertTrue(self.runtime.latest.status['paused'])
    def test_snapshot_cannot_mutate_authoritative_state(self):
        snapshot=self.runtime.latest;original=self.probe(lambda c:c.session_state().get('player'))
        snapshot.state['player']='wrong';self.assertEqual(self.probe(lambda c:c.session_state().get('player')),original)
    def test_same_frame_reload_changes_generation_and_rejects_old_maps(self):
        from pokemon_red.planning_state import PlanningSnapshotExpired
        generation=self.runtime.latest.generation
        with patch('pokemon_red.planning_state.read_world_revision',return_value='flags'):
            old=self.runtime.submit('navigation_revision').result(2)
            self.probe(lambda c:c.game.load_state(self.root/'Data/FireRed.state'))
            self.wait(lambda:self.runtime.latest.generation>generation)
            with self.assertRaises(PlanningSnapshotExpired):self.runtime.submit('map_snapshot','Route1',old).result(3)
        self.assertFalse(self.probe(lambda c:bool(c.keys)))
    def test_manual_press_revokes_a_pending_start_even_before_ui_snapshot(self):
        self.probe(lambda c:setattr(c,'pending_start',object()))
        self.runtime.submit('manual','A',True).result(2)
        self.assertFalse(self.probe(lambda c:c.pending_start is not None))
    def test_pause_does_not_spend_frames_and_short_manual_tap_is_not_lost(self):
        start=self.runtime.latest.frame;time.sleep(.03);self.assertEqual(self.runtime.latest.frame,start)
        masks=[]
        def setup(c):
            original=c.game.advance
            def advance(frames=1,keys=0):
                if frames:masks.append(keys)
                return original(frames,keys)
            c.game.advance=advance;c.set_speed(.5)
        self.probe(setup);self.runtime.submit('manual','A',True);self.runtime.submit('manual','A',False)
        self.wait(lambda:BUTTONS['A'] in masks);self.wait(lambda:0 in masks[masks.index(BUTTONS['A'])+1:])
    def test_final_close_is_not_lost_when_followed_by_takeover(self):
        gate,entered=threading.Event(),threading.Event()
        self.runtime.submit('probe',lambda c:(entered.set(),gate.wait(3)));self.assertTrue(entered.wait(1))
        self.runtime.take_control(close=True);self.runtime.take_control();gate.set();self.runtime.finished.result(5)


class GuiActorTests(PrivateSessionTestCase):
    def setUp(self):
        import gc
        gc.collect()
        super().setUp()
        import tkinter as tk
        from pokemon_red.gui import Monitor
        self.window=tk.Tk();self.window.withdraw();self.errors=[]
        self.monitor=Monitor(self.window,self.root,paused=True,runtime_factory=ProbeRuntime)
        self.monitor.show_battle_panel=lambda:None
        self.window.report_callback_exception=lambda kind,error,tb:self.errors.append(error)
        self.drive(lambda:self.monitor.ready)
    def drive(self,predicate,timeout=4):
        end=time.monotonic()+timeout
        while not predicate() and time.monotonic()<end:
            self.window.update();time.sleep(.001)
        detail=self.errors
        if not predicate():
            import traceback
            runtime=self.monitor.runtime
            frame=sys._current_frames().get(runtime.thread.ident)
            detail=dict(errors=self.errors,ready=str(runtime.ready),finished=str(runtime.finished),model=str(runtime.latest)[:300],owner_stack=''.join(traceback.format_stack(frame)) if frame else 'gone')
        self.assertTrue(predicate(),detail);self.assertEqual(self.errors,[])
    def probe(self,fn):return self.monitor.runtime.submit('probe',fn).result(4)
    def tearDown(self):
        if not self.monitor.closed:self.monitor.close();self.drive(lambda:self.monitor.closed,8)
        self.monitor.runtime.thread.join(2)
        super().tearDown()
        self.monitor=None;self.window=None
        # Avoid collecting a destroyed Tcl interpreter on the next owner thread.
        import gc
        gc.collect()
    def test_hotkey_settings_open_inside_panel_and_do_not_write_from_ui(self):
        from test_keyboard import event
        m=self.monitor
        with patch('pokemon_red.settings.atomic_bytes',side_effect=AssertionError('UI must not write settings')):
            m.show_panel('hotkeys');self.window.update()
            p=m.panel;view=p.hotkey_settings
            self.assertEqual(p.active_section,'settings')
            self.assertEqual(p.settings_tabs.select(),str(p.page_containers['hotkeys']))
            view.remove_key('UP',1)
            m.settings.bind('UP','t',1);view.refresh_bindings()
            view.speed_vars['3'].set('2,75');view.apply_speeds()
            self.drive(lambda:m.status.get('preferences_version',0)>=m._preferences_version)
            self.assertEqual(self.probe(lambda c:c.settings['bindings']['UP']),['Up','t'])
            self.assertEqual(self.probe(lambda c:c.settings['speed_bindings']['3']),2.75)
            # Digits in this form must not change the simulation speed.
            m.key_down(event(0x14,'3',widget=view.speed_entries['3']))
            self.assertTrue(m.paused)

    def test_same_speed_hotkey_cannot_leave_manual_alias_held_on_owner(self):
        from test_keyboard import event
        from types import SimpleNamespace
        m=self.monitor;m.set_speed(1);self.drive(lambda:not m.status['paused'])
        widget=SimpleNamespace(winfo_toplevel=lambda:m.window)
        m.key_down(event(126,widget=widget));m.key_down(event(13,'ц',widget=widget))
        self.assertEqual(self.probe(lambda c:sorted(c.keys)),['UP'])
        # Owner set_speed may return early at an unchanged rate. The UI still
        # must release both physical sources before forgetting their lifetimes.
        m.key_down(event(0x12,'1',widget=widget))
        m.key_up(event(126,widget=widget));m.key_up(event(13,'w',widget=widget))
        self.assertEqual(self.probe(lambda c:sorted(c.keys)),[])
        self.assertFalse(m.keys)
        m.key_down(event(13,'ц',widget=widget))
        self.assertEqual(self.probe(lambda c:sorted(c.keys)),['UP'])
        m.toggle_pause();self.drive(lambda:m.status['paused'])
        self.assertFalse(m.keys);self.assertFalse(m._held_keys)
        self.assertEqual(self.probe(lambda c:sorted(c.keys)),[])

    def test_preferences_are_patches_and_have_one_background_writer(self):
        from pokemon_red.settings import Settings
        m=self.monitor
        with patch('pokemon_red.settings.atomic_bytes',side_effect=AssertionError('UI must not write settings')):
            m.settings.bind('A','c');m.settings.bind('A','v',1);m.settings.set('speed_bindings',dict(m.settings['speed_bindings'],**{'3':2.75}));m.settings.set('autosave_seconds',10);m.settings.set('volume',55)
            self.drive(lambda:m.status.get('preferences_version',0)>=m._preferences_version)
            # Do not service Tk here: the UI has not received the bot speed yet.
            self.probe(lambda c:c.set_speed(2))
            m.settings.set('panel_on_start',True)
            self.drive(lambda:m.status.get('preferences_version',0)>=m._preferences_version)
            values=self.probe(lambda c:dict(c.settings.values))
            self.assertEqual(values['speed'],2);self.assertEqual(values['bindings']['A'],['c','v'])
            self.assertEqual(values['speed_bindings']['3'],2.75);self.assertEqual(values['autosave_seconds'],10);self.assertEqual(values['volume'],55)
            m.close();self.drive(lambda:m.closed)
        saved=Settings(self.root)
        self.assertEqual(saved['speed_bindings']['3'],2.75);self.assertEqual(saved['bindings']['A'],['c','v']);self.assertEqual(saved['speed'],2);self.assertTrue(saved['panel_on_start'])
    def test_volume_applies_immediately_but_durable_slider_save_stays_debounced(self):
        from pokemon_red.settings import Settings
        m=self.monitor;before=Settings(self.root)['volume']
        m.settings.set('volume',55,persist=False);m.sync_audio()
        self.drive(lambda:m.status.get('preferences_version',0)>=m._preferences_version)
        self.assertEqual(self.probe(lambda c:c.settings['volume']),55)
        self.assertEqual(Settings(self.root)['volume'],before)
        m.settings.save();self.drive(lambda:Settings(self.root)['volume']==55)

    def test_autosave_timer_keeps_running_without_servicing_tk(self):
        m=self.monitor;previous=m.model.frame
        def due(c):
            c.settings.values['autosave_enabled']=True;c.game.advance(2)
            c.last_save=c.last_save_request=time.monotonic()-6
            return c.game.frame
        captured=self.probe(due);time.sleep(.15)
        self.assertEqual(m.model.frame,previous)
        self.assertEqual(self.probe(lambda c:c.last_saved_frame),captured)
        with Game(self.root) as restored:self.assertEqual(restored.frame,captured)

    def test_ui_never_calls_a_game_and_remains_live_during_slow_core_frame(self):
        m=self.monitor;checks=[];original=Game._check
        def checked(game):checks.append(threading.get_ident());return original(game)
        with patch.object(Game,'_check',checked):
            def install(c):
                advance=c.game.advance
                def slow(frames=1,keys=0):
                    if frames:time.sleep(.02)
                    return advance(frames,keys)
                c.game.advance=slow;c.set_speed(16)
            self.probe(install);beats=[]
            def beat():
                beats.append(time.perf_counter())
                if not m.close_requested:self.window.after(10,beat)
            self.window.after(10,beat);self.drive(lambda:len(beats)>=20)
            self.assertLess(max(b-a for a,b in zip(beats,beats[1:])),.06)
            self.assertTrue(checks);self.assertEqual(set(checks),{m.runtime.thread.ident})
            at=time.perf_counter();m.take_control(focus=False);self.assertLess(time.perf_counter()-at,.02)
            self.drive(lambda:not m.pending_takeover)
    def test_tools_are_lazy_and_map_requests_are_futures(self):
        m=self.monitor;m.show_panel('overview');self.window.update()
        self.assertNotIn('automation',m.panel.pages);self.assertEqual(m.panel.automation_windows.tools,{})
        view=m.panel.open_training();self.drive(view.visible)
        self.assertTrue(hasattr(m.planning_map('Route1',None),'done'))
        m.panel.automation_windows.hide('training');self.window.update();self.assertIsNone(view.planner.process)
        acquisition=m.panel.open_acquisition();self.window.update();self.assertEqual(len(acquisition.cards),4)
    def test_actual_bot_takeover_rejects_late_input_and_accepts_manual_keys(self):
        m=self.monitor;script=self.root/'held.py';script.write_text("def run(bot):\n    bot.press('RIGHT',frames=3600)\n    bot.press('LEFT',frames=3600)\n")
        masks=[]
        def instrument(c):
            original=c.game.advance
            def advance(frames=1,keys=0):
                if frames:masks.append(keys)
                return original(frames,keys)
            c.game.advance=advance
        self.probe(instrument);m.start_bot(script);self.drive(lambda:m.automation.info().get('action') is not None)
        # Session objects remain on the owner: inject the late request there.
        saved=[];self.probe(lambda c:saved.append((c.automation.session,c.automation.action['request'])))
        m.shortcut_down(SimpleNamespace(keycode=(0x65<<24),state=0));self.drive(lambda:not m.pending_takeover)
        self.assertTrue(saved[0][1].response['cancelled']);point=len(masks)
        def late(c):
            request=Request(saved[0][0],'press',dict(button='LEFT',frames=1000));c.automation.requests.put(request);return request
        late_request=[];self.probe(lambda c:late_request.append(late(c)))
        self.drive(lambda:late_request[0].done.is_set());self.assertTrue(late_request[0].response['cancelled'])
        key=SimpleNamespace(keycode=(0x07<<24),state=0,widget=m.canvas)
        m.key_down(key);self.drive(lambda:BUTTONS['A'] in masks[point:]);m.key_up(key)
        self.assertNotIn(BUTTONS['LEFT'],masks[point:]);self.assertFalse(m.automation.running)
    def test_cancel_during_checkpoint_preparation_prevents_late_start(self):
        m=self.monitor;gate,entered=threading.Event(),threading.Event()
        self.probe(lambda c:(c.writer.submit(lambda:(entered.set(),gate.wait(3))),None)[1]);self.assertTrue(entered.wait(1))
        script=self.root/'pending.py';script.write_text("def run(bot):\n    bot.press('A',frames=3000)\n")
        try:
            m.start_bot(script);self.drive(lambda:m.pending_start)
            m.take_control(focus=False);self.drive(lambda:not m.pending_takeover);gate.set()
            self.drive(lambda:not m.pending_writes);self.assertFalse(m.automation.running)
            self.assertFalse(self.probe(lambda c:c.pending_start is not None))
        finally:gate.set()
    def test_critical_checkpoint_waits_without_advancing_or_blocking_ui(self):
        m=self.monitor;gate,entered=threading.Event(),threading.Event();requests=[]
        def setup(c):
            c.writer.submit(lambda:(entered.set(),gate.wait(3)))
            c.automation.session=Session(socket.socket());c.create_slot('Before A')
            request=Request(c.automation.session,'press',dict(button='A',frames=30));requests.append(request);c.automation._dispatch(request);c.paused=False
            return c.game.frame
        before=self.probe(setup);self.assertTrue(entered.wait(1))
        try:
            beat=[];self.window.after(30,lambda:beat.append(True));self.drive(lambda:bool(beat));self.assertEqual(m.frame,before)
            m.take_control(focus=False);self.drive(lambda:not m.pending_takeover);gate.set()
            self.drive(lambda:not m.pending_writes);self.assertTrue(requests[0].response['cancelled'])
        finally:gate.set()
    def test_failed_critical_write_stops_before_queued_button(self):
        m=self.monitor;requests=[]
        def broken():raise OSError('test disk full')
        def setup(c):
            c.automation.session=Session(socket.socket());before=c.game.frame;c.submit_write(broken,critical=True)
            request=Request(c.automation.session,'press',dict(button='A',frames=30));requests.append(request);c.automation._dispatch(request);c.paused=False
            return before
        before=self.probe(setup);self.drive(lambda:m.save_failed)
        self.assertTrue(m.paused);self.assertFalse(m.automation.running);self.assertEqual(m.frame,before);self.assertTrue(requests[0].response['cancelled'])
    def test_slow_autosave_acknowledges_capture_while_core_and_ui_continue(self):
        m=self.monitor;gate,entered=threading.Event(),threading.Event()
        from pokemon_red.persistence import publish_checkpoint as publish
        def slow(*args,**kwargs):entered.set();gate.wait(3);return publish(*args,**kwargs)
        try:
            self.probe(lambda c:c.game.advance(10));captured=self.probe(lambda c:c.game.frame)
            with patch('pokemon_red.session_controller.publish_checkpoint',side_effect=slow):
                m.save();self.assertTrue(entered.wait(1));self.probe(lambda c:c.game.advance(15))
                beat=[];self.window.after(0,lambda:beat.append(True));self.drive(lambda:bool(beat));self.assertNotEqual(m.last_saved_frame,captured)
                gate.set();self.drive(lambda:m.last_saved_frame==captured)
            with Game(self.root) as restored:self.assertEqual(restored.frame,captured)
        finally:gate.set()
    def test_close_waits_for_final_save_without_waiting_in_tk(self):
        m=self.monitor;gate,entered=threading.Event(),threading.Event()
        self.probe(lambda c:(c.writer.submit(lambda:(entered.set(),gate.wait(3))),None)[1]);self.assertTrue(entered.wait(1))
        try:
            m.close();beat=[];self.window.after(0,lambda:beat.append(True));self.drive(lambda:bool(beat));self.assertFalse(m.closed)
            gate.set();self.drive(lambda:m.closed)
        finally:gate.set()
    def test_close_during_replacement_saves_destination_and_keeps_order(self):
        m=self.monitor;gate,entered=threading.Event(),threading.Event()
        self.probe(lambda c:(c.writer.submit(lambda:(entered.set(),gate.wait(3))),None)[1]);self.assertTrue(entered.wait(1))
        def replace(c):
            candidate=Game(self.root,resume=False);candidate.advance(75);return c.replace_game(candidate,'test destination')
        self.monitor.runtime.submit('probe',replace)
        self.drive(lambda:m.session_transition)
        try:
            m.close();gate.set();self.drive(lambda:m.closed)
            with Game(self.root) as restored:self.assertEqual(restored.frame,75)
        finally:gate.set()

if __name__=='__main__':unittest.main()
