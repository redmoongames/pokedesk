"""Shared weighted IV ranking, embedded setup and bounded pool adoption safety."""
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock,patch
import hashlib,json,sys,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.models import STAT_KEYS
from pokemon_red.new_game_config import NewGameConfig
from pokemon_red.capture_target import CaptureTarget
from pokemon_red.starter_candidates import assess
from pokemon_red.iv_preferences import score_ivs
from pokemon_red.acquisition_play import JobPaused,AcquisitionAttention

def mon(number=19,uid='new',hp=25,speed=25):
    values=dict.fromkeys(STAT_KEYS,10);values.update(hp=hp,speed=speed)
    return dict(uid=uid,species_id=number,checksum_valid=True,is_egg=False,personality=100,nature=0,shiny=False,level=5,ivs=values)

class WeightedIVTests(unittest.TestCase):
    def test_speed_star_breaks_the_users_hp_speed_tie_in_both_searches(self):
        goals=dict.fromkeys(STAT_KEYS,0);goals.update(hp=31,speed=31)
        target=CaptureTarget.parse(dict(species_id=19,gender='any',min_ivs=goals,priority_ivs=['speed']),ROOT)
        starter=NewGameConfig.parse(dict(min_ivs=list(goals.values()),priority_ivs=['speed']))
        hp=mon(hp=26,speed=25);speed=mon(hp=25,speed=26)
        self.assertGreater(target.assess(speed,ROOT)['rank'],target.assess(hp,ROOT)['rank'])
        self.assertGreater(assess(starter,dict(speed,species_id=1))['rank'],assess(starter,dict(hp,species_id=1))['rank'])
        self.assertEqual(target.assess(speed,ROOT)['score'],77);self.assertEqual(target.assess(hp,ROOT)['score'],76)
        self.assertFalse(target.matches(speed,ROOT));self.assertFalse(starter.matches(dict(speed,species_id=1)))
    def test_surplus_ivs_do_not_compensate_for_other_goals(self):
        goals=(0,5,0,20,0,0);values=dict(zip(STAT_KEYS,(31,31,31,10,31,31)))
        rated=score_ivs(values,goals,('speed',));self.assertEqual(rated['score'],25);self.assertEqual(rated['target_score'],45)
    def test_roundtrip_and_old_configs_keep_unit_weights(self):
        cfg=NewGameConfig.parse(dict(priority_ivs=['hp','speed']));self.assertEqual(NewGameConfig.parse(cfg.json()),cfg)
        target=CaptureTarget.parse(dict(species_id=19,priority_ivs=['hp'],search_workers=4),ROOT);self.assertEqual(CaptureTarget.parse(target.as_dict(),ROOT),target)
        self.assertEqual(NewGameConfig.parse({}).priority_ivs,());self.assertEqual(CaptureTarget.parse(dict(species_id=19),ROOT).search_workers,1)
    def test_stars_and_process_count_are_validated(self):
        for invalid in ('speed',['speed','speed'],['accuracy'],[True]):
            with self.assertRaises(ValueError):NewGameConfig.parse(dict(priority_ivs=invalid))
            with self.assertRaises(ValueError):CaptureTarget.parse(dict(species_id=19,priority_ivs=invalid),ROOT)
        for invalid in (0,7,True,1.5):
            with self.assertRaises(ValueError):CaptureTarget.parse(dict(species_id=19,search_workers=invalid),ROOT)
    def test_priority_does_not_relax_identity_filters_or_change_odds(self):
        from pokemon_red.search_odds import wild_odds
        cfg=dict(species_id=19,gender='any',min_ivs=dict.fromkeys(STAT_KEYS,10));plain=CaptureTarget.parse(cfg,ROOT);star=CaptureTarget.parse(dict(cfg,priority_ivs=['hp']),ROOT)
        self.assertEqual(wild_odds(plain,ROOT),wild_odds(star,ROOT))
        for update in (dict(species_id=16),dict(checksum_valid=False),dict(shiny=True),dict(ivs=dict.fromkeys(STAT_KEYS,32))):self.assertIsNone(star.assess(dict(mon(),**update),ROOT))

class PoolSafetyTests(unittest.TestCase):
    def exercise(self,*,cancel=False,missing_original=False,attention=False,race=False):
        from pokemon_red.wild_search import search
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'Data').mkdir();(root/'vendor').symlink_to(ROOT/'vendor')
            worker=NS(safe_point=Mock(),update=Mock(),event=Mock(),parent_pid=123)
            game=NS(root=root,capture_save=Mock(return_value=NS(state=b"baseline",publish=Mock())),restore_checkpoint=Mock())
            player=NS(g=game,w=worker);created=[];wanted=mon()
            def clone(project,folder,snapshot,**_):
                (folder/'Data').mkdir(parents=True);created.append(folder)
            def spawn(args,**kw):
                folder=Path(args[-1]);data=b'winning branch';(folder/('attention.state' if attention else 'found.state')).write_bytes(data)
                from pokemon_red.acquisition import write_json
                write_json(folder/'progress.json',dict(status='attention' if attention else 'found',error='unexpected shiny',pokemon=wanted,sha256=hashlib.sha256(data).hexdigest(),attempts=2,heartbeat=1))
                return NS(poll=lambda:0,wait=lambda **_:0)
            def stop(children):
                for _,_,log in children:log.close()
                if cancel:worker.safe_point.side_effect=JobPaused()
            from pokemon_red.acquisition import read_json as real_read
            read_once=set()
            def raced_read(path,default=None):
                result=real_read(path,default)
                if race and Path(path).name=='progress.json' and str(path) not in read_once:
                    read_once.add(str(path));return dict(result,status='running')
                return result
            inventory=dict(party=[wanted]+([] if missing_original else [dict(uid='original')]),boxes=[])
            with patch('pokemon_red.wild_search.read_json',side_effect=raced_read),patch('pokemon_red.telemetry.read_walk_state',return_value=dict(on_bike=False)),patch('pokemon_red.wild_search.prepare_hunt',return_value=dict(initial=['original'],hunter='original',selected=dict(method="water_mons") )) as prepare,patch('pokemon_red.wild_search.clone_session',side_effect=clone),patch('pokemon_red.wild_search.subprocess.Popen',side_effect=spawn),patch('pokemon_red.wild_search.stop_children',side_effect=stop),patch('pokemon_red.wild_search.read_inventory',return_value=inventory),patch('pokemon_red.wild_search.read_roster_uids',return_value={m['uid'] for m in inventory['party']+inventory['boxes']}):
                if cancel:
                    with self.assertRaises(JobPaused):search(player,dict(species_id=19,gender='any',search_workers=4))
                    game.restore_checkpoint.assert_not_called()
                elif missing_original or attention:
                    with self.assertRaises(AcquisitionAttention):search(player,dict(species_id=19,gender='any',search_workers=4))
                else:self.assertEqual(search(player,dict(species_id=19,gender='any',search_workers=4))['uid'],'new');game.restore_checkpoint.assert_called_once()
                prepare.assert_called_once();self.assertEqual(len(created),4)
    def test_revoked_lane_cannot_step_even_the_first_requested_frame(self):
        from pokemon_red.acquisition_play import Player
        game=NS(advance=Mock());worker=NS(before_frame=Mock(side_effect=JobPaused()),heartbeat=Mock())
        with self.assertRaises(JobPaused):Player(game,worker).advance(100,1)
        game.advance.assert_not_called();worker.heartbeat.assert_not_called()
    def test_final_publication_between_progress_read_and_exit_poll_is_not_an_error(self):self.exercise(race=True)
    def test_four_searches_share_one_preparation_and_only_one_branch_is_adopted(self):self.exercise()
    def test_revocation_during_shutdown_cannot_import_a_late_winner(self):self.exercise(cancel=True)
    def test_selected_branch_must_preserve_every_original_pokemon(self):self.exercise(missing_original=True)
    def test_attention_stops_the_pool_without_reporting_a_caught_match(self):self.exercise(attention=True)

class IVEditorTests(unittest.TestCase):
    def test_compact_editor_uses_two_columns_and_recomputes_star_score(self):
        import tkinter as tk,gc
        from pokemon_red.iv_preferences_ui import IVPreferences
        gc.collect();root=tk.Tk();root.geometry('520x380');root.update()
        try:
            changed=Mock();editor=IVPreferences(root,minimums=(31,)*6,command=changed);root.update();self.assertEqual(editor.columns,2)
            editor.buttons['speed'].invoke();self.assertEqual(editor.preferred,('speed',));changed.assert_called_once()
            self.assertEqual(editor.values['speed'].get(),31);self.assertEqual(editor.buttons['speed'].cget('text'),'★')
            editor.arrange(280);self.assertEqual(editor.columns,1)
        finally:root.destroy()

from test_runtime_performance import PrivateSessionTestCase

class EmbeddedCatchTests(PrivateSessionTestCase):
    def test_setup_stays_in_existing_left_window_and_preserves_species_page(self):
        import tkinter as tk,gc,time
        from pokemon_red.gui import Monitor
        from test_engine_runtime import ProbeRuntime
        from pokemon_red.catch_view import open_autocatch
        gc.collect();window=tk.Tk();window.withdraw();errors=[]
        m=Monitor(window,self.root,paused=True,runtime_factory=ProbeRuntime);window.report_callback_exception=lambda kind,error,tb:errors.append(error)
        def drive(predicate):
            deadline=time.monotonic()+6
            while not predicate() and time.monotonic()<deadline:window.update();time.sleep(.005)
            self.assertTrue(predicate(),errors);self.assertEqual(errors,[])
        try:
            drive(lambda:m.ready);m.show_panel('collection');m.panel.window.geometry('540x800');m.panel.open_pokemon(species_id=19);m.show_battle_panel();window.update()
            before=[w for w in window.winfo_children() if isinstance(w,tk.Toplevel)]
            with patch('pokemon_red.catch_view.HuntService') as service:
                service.return_value.poll.return_value=None
                view=open_autocatch(m.panel,19);window.update()
                self.assertIs(view.window,m.battle_panel.window);self.assertTrue(view.visible());self.assertFalse(view.iv_host.winfo_manager());self.assertEqual(view.target().search_seconds,60);self.assertFalse(view.target().exact_ivs)
                self.assertEqual([w for w in window.winfo_children() if isinstance(w,tk.Toplevel)],before)
                self.assertEqual(m.panel.details.history.routes[-1].kind,'pokemon')
                view.stat_editor.controls['speed'].choose('positive');self.assertEqual(view.target().priority_ivs,('speed',))
                self.assertIs(open_autocatch(m.panel,19),view)
                m.battle_panel.close_catch();window.update();self.assertTrue(view.closed);self.assertEqual(m.panel.details.history.routes[-1].kind,'pokemon')
                service.return_value.close.assert_called()
        finally:
            if not m.closed:m.close();drive(lambda:m.closed)
            # Tk can retain script IDs after a standalone test root is destroyed.
            for token in window.tk.call('after','info'):
                try:window.after_cancel(token)
                except tk.TclError:pass
            gc.collect()

if __name__=='__main__':unittest.main()
