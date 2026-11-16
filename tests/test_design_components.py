"""Display selection, model-copy, keyboard help and usable desktop geometry."""
from pathlib import Path
from types import SimpleNamespace as NS
import sys,unittest
from unittest.mock import Mock
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
import tkinter as tk
from pokemon_red.text_values import SelectableLabel
from pokemon_red.ui import BG,Toggle,Slider,Button,theme
from pokemon_red.tooltips import Tooltip,dismiss_tooltips
from pokemon_red.table import Table
from pokemon_red.window_layout import Rect,layout
from pokemon_red.scrolling import Router

class DesignComponentsTests(unittest.TestCase):
    def setUp(self):
        import gc
        gc.collect()
        self.root=tk.Tk();self.root.geometry('540x450');self.root.configure(bg=BG);theme(self.root)
        self.errors=[];self.root.report_callback_exception=lambda *args:self.errors.append(str(args[1]))
        self.root.update()
    def tearDown(self):
        self.root.destroy();self.assertEqual(self.errors,[])
    def test_drag_surface_is_read_only_and_refresh_does_not_destroy_selection(self):
        label=SelectableLabel(self.root,text='Venusaur: 165 / 165 HP',anchor='w',justify='left',font=('Helvetica',12));label.pack(fill='x');self.root.update()
        label.pressed(NS(x=1,y=3));label.dragged(NS(x=100,y=3));self.root.update()
        text=label.editor;self.assertEqual(text['state'],'disabled');self.assertTrue(text.tag_ranges('sel'))
        selection=text.get('sel.first','sel.last');label.configure(text='Venusaur: 100 / 165 HP');self.root.update()
        self.assertEqual(text.get('sel.first','sel.last'),selection)
        self.assertEqual(text.get('1.0','end-1c'),'Venusaur: 165 / 165 HP')
        self.assertIsNone(getattr(text,'_scroll_indicator',None))
    def test_tk_mouse_events_activate_selectable_surface(self):
        label=SelectableLabel(self.root,text='Venusaur: 165 / 165 HP',anchor='w',justify='left',font=('Helvetica',12));label.pack(fill='x');self.root.update()
        label.event_generate('<ButtonPress-1>',x=2,y=8)
        label.event_generate('<B1-Motion>',x=100,y=8,state=256)
        self.root.update();self.assertIsNotNone(label.editor);self.assertTrue(label.editor.tag_ranges('sel'))
        label.destroy();self.root.update()
    def test_single_character_button_never_turns_into_ellipsis(self):
        for glyph in ('✦','×','↻'):
            button=Button(self.root,glyph,width=26,height=24);button.pack();self.root.update();button.draw()
            values=[button.itemcget(i,'text') for i in button.find_all() if button.type(i)=='text']
            self.assertIn(glyph,values);button.destroy()
    def test_context_copy_does_not_grab_f9(self):
        from pokemon_red.text_values import copy_menu
        label=SelectableLabel(self.root,text='value');label.pack();self.root.update()
        handler=Mock();self.root.bind_all('<F9>',lambda _:handler())
        copy_menu(label,NS(x_root=80,y_root=80),[('Copy','value')]);popup=self.root._copy_popup
        popup.focus_force();self.root.update();self.assertIsNone(self.root.grab_current());popup.event_generate('<KeyPress-F9>');self.root.update();handler.assert_called_once()
        popup.destroy()
    def test_party_row_preserves_status_and_uses_full_width(self):
        from pokemon_red.party_row import PartyRow,party_row_signature
        from pokemon_red.catalog import catalog,species
        mon=dict(uid='test',species_id=25,nickname='PIKACHU',species='PIKACHU',level=10,hp=30,max_hp=30,experience=1000,exp_to_next_level=331,status_code=0,shiny=True)
        row=PartyRow(self.root,ROOT,Mock());row.pack(fill='x');row.set(mon);self.root.update()
        self.assertGreater(row.winfo_width(),450);self.assertLess(row.winfo_height(),110);self.assertEqual(row.hp_text.cget('text'),'30 / 30 HP')
        signature=party_row_signature(mon);self.assertEqual(signature,party_row_signature(dict(mon,moves=[{'id':1}])))
        row.set(dict(mon,hp=0,status_code=8));self.root.update();self.assertEqual(row.hp.value,0)
        self.assertTrue(row.status.winfo_manager());self.assertNotEqual(row.status.cget('text'),'…')
    def test_ordinary_click_does_not_allocate_text_or_intercept_actions(self):
        label=SelectableLabel(self.root,text='data');label.pack();self.root.update()
        label.pressed(NS(x=2,y=3));label.dragged(NS(x=3,y=3));self.assertIsNone(label.editor)
    def test_display_selection_is_not_a_nested_scroll_target(self):
        label=SelectableLabel(self.root,text='data');label.pack();self.root.update();editor=label.surface()
        self.assertNotIn(editor,list(self.root._scroll_router.targets(editor)))
    def test_copy_table_uses_full_values_and_preserves_zeroes(self):
        table=Table(self.root,columns=('name','number'),show='headings',height=2);table.pack();table.insert('','end',iid='a',values=('Very long full name','001'));table.selection_set('a')
        table.clipboard_clear=Mock();table.clipboard_append=Mock();table.copy_selection()
        table.clipboard_append.assert_called_once_with('Very long full name\t001')
        self.assertEqual(table.hover_value(),'Very long full name · 001')
    def test_pointer_and_keyboard_help_share_one_instance(self):
        label=SelectableLabel(self.root,text='data');label.pack();self.root.update()
        hint=Tooltip(label,'Explain');hint.focused();hint.show();self.root.update()
        self.assertIsNotNone(hint.window);self.assertIsNone(self.root.grab_current())
        dismiss_tooltips();self.assertIsNone(hint.window)
        old=hint;hint=Tooltip(label,'New');old.enter();self.assertIsNone(old.timer)
        hint.focused();self.assertIsNotNone(hint.timer);label.destroy();self.assertIsNone(hint.timer)
    def test_toggle_and_slider_have_visible_focus_and_disabled_toggle_cannot_change(self):
        variable=tk.BooleanVar(value=False);toggle=Toggle(self.root,'Enabled',variable);slider=Slider(self.root,tk.DoubleVar(value=50))
        toggle.pack(fill='x');slider.pack(fill='x');self.root.update()
        for widget in (toggle,slider):
            widget.focus_force();self.root.update();widget.draw();self.assertTrue(widget.find_withtag('focus'))
        toggle.configure(state='disabled');toggle.toggle();self.assertFalse(variable.get());self.assertFalse(toggle.enabled)

class ResponsiveLayoutTests(unittest.TestCase):
    def test_game_scale_and_panel_minimum_survive_small_desktop(self):
        for width,height,scale in ((1024,768,2),(1280,800,3),(1440,900,3),(1920,1080,3)):
            with self.subTest(width=width):
                result=layout(Rect(0,0,width,height),3)
                self.assertLessEqual(result.scale,3);self.assertGreaterEqual(result.trainer.width,480)
                self.assertEqual(result.game.x+result.game.width/2,width/2)
                for rect in (result.game,result.trainer,result.battle):
                    self.assertGreaterEqual(rect.x,0);self.assertLessEqual(rect.x+rect.width,width)
    def test_secondary_monitor_has_no_assumed_zero_origin(self):
        result=layout(Rect(-1440,-200,1440,900),3)
        self.assertLess(result.game.x,0);self.assertLess(result.trainer.x,0)
        self.assertGreaterEqual(result.game.x,-1440);self.assertGreaterEqual(result.trainer.x,-1440)

if __name__=='__main__':unittest.main()
