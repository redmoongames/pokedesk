"""Compact IV/EV labels follow the exact stat and the latest detached model."""
from pathlib import Path
from types import SimpleNamespace
import sys,unittest
import tkinter as tk
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.team_view import OwnedDetail,STATS,HIDDEN_STATS
from pokemon_red.stat_values_ui import STAT_NAMES
from pokemon_red.ui import BG,TEXT,MUTED,GREEN,RED

class StatValuesTests(unittest.TestCase):
    def setUp(self):
        self.window=tk.Tk();self.window.geometry('540x780');self.window.configure(bg=BG);self.errors=[]
        self.window.report_callback_exception=lambda kind,error,tb:self.errors.append(error)
        self.view=OwnedDetail(SimpleNamespace(monitor=SimpleNamespace(folder=ROOT)),self.window);self.view.frame.pack(fill='x');self.view.hero.pack_forget()
        keys=['hp','attack','defense','speed','special_attack','special_defense']
        self.mon=dict(uid='stats-test',species_id=64,species='KADABRA',nickname='Kadabra',level=30,hp=50,max_hp=80,status='В норме',moves=[],friendship=170,
                      stats=dict(zip(keys[1:],[42,35,71,90,60])),ivs=dict(zip(keys,[31,30,29,28,27,26])),evs=dict(zip(keys,[0,252,4,252,1,1])))
        self.view.set(self.mon);self.window.update()
    def tearDown(self):self.window.destroy();self.assertEqual(self.errors,[])
    def test_all_six_stats_show_exact_values_and_distinct_muted_colors(self):
        self.assertEqual(set(self.view.stat_values),set(self.mon['ivs']));self.assertEqual(self.view.stats['hp'].cget('text'),'80')
        self.assertIn('Friendship: 170',self.view.identity.cget('text'))
        colors={g:color for g,_,color in HIDDEN_STATS};self.assertEqual(len(set(colors.values())),2)
        for key,title in STATS:
            for group,abbreviation,_ in HIDDEN_STATS:
                value=self.view.stat_values[key][group];self.assertEqual(value.cget('text'),str(self.mon[group][key]));self.assertEqual(value.cget('fg'),colors[group]);self.assertNotEqual(value.cget('fg'),TEXT)
                self.assertNotIn(abbreviation,value.cget('text'));self.assertIn(abbreviation+' · '+STAT_NAMES[key]+': '+str(self.mon[group][key]),self.view.stat_hints[key][group].text)
    def test_refresh_updates_ev_and_does_not_retain_missing_values(self):
        hint=self.view.stat_hints['attack']['evs'];hint.enter();self.window.after(400,self.window.quit);self.window.mainloop();self.assertIsNotNone(hint.window)
        current=dict(self.mon,evs=dict(self.mon['evs'],attack=0),ivs={'hp':0},stages={'attack':2});self.view.update_detail(current);self.window.update()
        self.assertEqual(self.view.stat_values['attack']['evs'].cget('text'),'0');self.assertIn('Атака: 0',hint.text);self.assertIsNone(hint.window)
        self.assertEqual(self.view.stat_values['hp']['ivs'].cget('text'),'0');self.assertEqual(self.view.stat_values['speed']['ivs'].cget('text'),'—');self.assertIn('нет данных',self.view.stat_hints['speed']['ivs'].text)
        self.assertEqual(self.view.stats['attack'].cget('text'),'42 (+2)')
    def test_missing_iv_and_ev_are_unknown_rather_than_zero(self):
        current=dict(self.mon);current.pop('ivs');current.pop('evs');self.view.update_detail(current)
        for values in self.view.stat_values.values():self.assertTrue(all(w.cget('text')=='—' for w in values.values()))
    def test_compact_grid_fits_narrow_and_wide_windows_with_battle_stages(self):
        current=dict(self.mon,nature=23,max_hp=714,stats={key:999 for key in self.mon['stats']},stages={key:-6 for key in self.mon['stats']})
        self.view.update_detail(current)
        for width in (500,540,800):
            self.window.geometry(str(width)+'x780');self.window.update()
            grid=self.view.stat_grid;self.assertLessEqual(grid.winfo_height(),110)
            for key,_ in STATS:
                main=self.view.stats[key];cell=grid.cells[key];left=cell.winfo_rootx();right=left+cell.winfo_width()
                for group,_,_ in HIDDEN_STATS:
                    value=self.view.stat_values[key][group];self.assertLessEqual(value.winfo_rootx()+value.winfo_width(),right);self.assertGreaterEqual(value.winfo_rootx(),left)
                self.assertLessEqual(main.winfo_rootx()+main.winfo_width(),right)
                iv=grid.values[key]['ivs'];ev=grid.values[key]['evs']
                self.assertLessEqual(main.winfo_rootx()+main.winfo_width(),grid.group_labels[key]['ivs'].winfo_rootx())
                self.assertLessEqual(iv.winfo_rootx()+iv.winfo_width(),grid.group_labels[key]['evs'].winfo_rootx())
    def test_abbreviations_and_inline_iv_ev_labels_keep_russian_hover_names(self):
        grid=self.view.stat_grid
        self.assertEqual([grid.names[key].cget('text') for key,_ in STATS],['HP','ATK','DEF','SP ATK','SP DEF','SPEED'])
        for key,_ in STATS:self.assertEqual([w.cget('text') for w in grid.group_labels[key].values()],['IV','EV'])
        for key,_ in STATS:self.assertIn(STAT_NAMES[key],grid.name_hints[key].text)
        places=[(grid.cells[key].grid_info()['row'],grid.cells[key].grid_info()['column']) for key,_ in STATS];self.assertEqual(places,[(0,0),(0,1),(1,0),(1,1),(2,0),(2,1)])
    def test_nature_highlights_correct_stats_without_changing_values_or_iv_ev(self):
        view=self.view;view.update_detail(dict(self.mon,nature=2));self.window.update();grid=view.stat_grid
        self.assertIn('Brave',view.nature.cget('text'));self.assertEqual(grid.names['attack'].cget('text'),'ATK ↑');self.assertEqual(grid.names['speed'].cget('text'),'SPEED ↓')
        self.assertEqual(grid.stats['attack'].cget('fg'),GREEN);self.assertEqual(grid.stats['speed'].cget('fg'),RED);self.assertEqual(grid.stats['hp'].cget('fg'),TEXT)
        self.assertEqual(grid.stats['attack'].cget('text'),'42')
        self.assertIn('+10%',grid.name_hints['attack'].text);self.assertIn('-10%',grid.stat_hints['speed'].text);self.assertIn('×0.9',grid.stat_hints['speed'].text);self.assertIn('0%',grid.hp_hint.text)
        for key,_ in STATS:
            for group,_,color in HIDDEN_STATS:self.assertEqual(grid.values[key][group].cget('fg'),color)
    def test_switching_nature_restores_neutral_and_unknown_highlights(self):
        view=self.view;grid=view.stat_grid;view.update_detail(dict(self.mon,nature=2));view.update_detail(dict(self.mon,nature=5))
        self.assertEqual(grid.stats['defense'].cget('fg'),GREEN);self.assertEqual(grid.stats['attack'].cget('fg'),RED);self.assertEqual(grid.stats['speed'].cget('fg'),TEXT)
        view.update_detail(dict(self.mon,nature=24));self.assertIn('Quirky · no changes',view.nature.cget('text'))
        for key,title in STATS:
            self.assertEqual(grid.names[key].cget('text'),title);self.assertEqual(grid.stats[key].cget('fg'),TEXT);self.assertEqual(grid.names[key].cget('fg'),MUTED)
        view.update_detail(self.mon);self.assertIn('no data',view.nature.cget('text'));self.assertIn('Нет данных',grid.stat_hints['attack'].text)
    def test_hover_on_main_stat_explains_percentage_and_updates_without_stale_popup(self):
        view=self.view;view.update_detail(dict(self.mon,nature=15));grid=view.stat_grid
        grid.stats['special_attack'].event_generate('<Enter>');self.window.after(400,self.window.quit);self.window.mainloop()
        hint=grid.stat_hints['special_attack'];self.assertIsNotNone(hint.window)
        popup=hint.window.winfo_children()[0].cget('text');self.assertIn('Modest',popup);self.assertIn('+10%',popup);self.assertIn('Already included',popup)
        view.update_detail(dict(self.mon,nature=24));self.assertIsNone(hint.window);self.assertIn('0%',hint.text)

if __name__=='__main__':unittest.main()
