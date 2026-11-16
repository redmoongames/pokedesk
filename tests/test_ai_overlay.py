"""AI indication, pixel tint, cheap speed updates and preference persistence."""
from pathlib import Path
from types import SimpleNamespace
import sys,tempfile,tkinter as tk,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from pokemon_red.ai_overlay import AIOverlay,tint_video,PPM_HEADER
from pokemon_red.gui import Monitor
from pokemon_red.settings import Settings

class OverlayTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=tk.Tk();self.root.withdraw();self.addCleanup(self.root.destroy)
        m=self.m=Monitor.__new__(Monitor);m.window=self.root;m.canvas=tk.Canvas(self.root)
        m.settings=Settings(Path(self.temp.name));m.display_scale=3;m.ready=True;m.paused=False;m.safety_notice=None
        m.model=SimpleNamespace(video=PPM_HEADER+bytes((32,64,96))*240*160,video_revision=1,generation=1)
        m.status=dict(speed=2.75);m.automation=SimpleNamespace(running=True)
        m.operation=SimpleNamespace(active=False,data={});m.pending_start=False;m.pending_takeover=0;m._render_key=None
        m.canvas_image=m.canvas.create_image(0,0,anchor='nw');m.ai_overlay=AIOverlay(m.canvas)
        m.pause_shade=m.canvas.create_rectangle(0,0,0,0);m.pause_title=m.canvas.create_text(0,0);m.pause_hint=m.canvas.create_text(0,0)
    def visible(self,item):return self.m.canvas.itemcget(item,'state')=='normal'
    def test_tint_preserves_header_and_only_lightens_rgb_by_five_percent(self):
        result=tint_video(self.m.model.video)
        self.assertEqual(result[:len(PPM_HEADER)],PPM_HEADER)
        self.assertEqual(result[len(PPM_HEADER):len(PPM_HEADER)+3],bytes(round(v*.95+255*.05) for v in (32,64,96)))
        self.assertEqual(len(result),len(self.m.model.video))
    def test_takeover_and_preference_restore_original_pixels_and_hide_all_indication(self):
        m=self.m;m.render();self.assertTrue(self.visible(m.ai_overlay.hint));self.assertFalse(self.visible(m.pause_title))
        self.assertNotEqual(m.image.get(0,0),(32,64,96))
        m.settings.set('ai_control_overlay',False,persist=False);m.render()
        self.assertTrue(all(not self.visible(item) for item in m.ai_overlay.items));self.assertEqual(m.image.get(0,0),(32,64,96))
        m.settings.set('ai_control_overlay',True,persist=False);m.automation.running=False;m.render()
        self.assertFalse(self.visible(m.ai_overlay.title));self.assertEqual(m.image.get(0,0),(32,64,96))
    def test_speed_changes_update_caption_without_rebuilding_video(self):
        m=self.m;m.render();image=m.image
        self.assertEqual(m.canvas.itemcget(m.ai_overlay.speed,'text'),'2.75×')
        m.status['speed']=12;m.render()
        self.assertIs(m.image,image);self.assertEqual(m.canvas.itemcget(m.ai_overlay.speed,'text'),'12×')
    def test_new_save_generation_rebuilds_video_even_when_revision_repeats(self):
        m=self.m;m.render();old=m.image
        m.model.generation=2;m.model.video=PPM_HEADER+bytes((100,100,100))*240*160;m.render()
        self.assertIsNot(m.image,old);self.assertNotEqual(m.image.get(0,0),old.get(0,0))
    def test_loading_shiny_and_manual_pause_keep_priority(self):
        m=self.m;m.ready=False;m.render();self.assertFalse(self.visible(m.ai_overlay.title));self.assertTrue(self.visible(m.pause_title))
        m.ready=True;m.safety_notice=dict(species='PIKACHU');m.render()
        self.assertFalse(self.visible(m.ai_overlay.title));self.assertIn('SHINY',m.canvas.itemcget(m.pause_title,'text'))
        m.safety_notice=None;m.automation.running=False;m.paused=True;m.render()
        self.assertFalse(self.visible(m.ai_overlay.title));self.assertTrue(self.visible(m.pause_title))
    def test_operation_indicates_its_own_limit_and_cancellation_until_safe_return(self):
        m=self.m;m.automation.running=False;m.operation.active=True;m.paused=True
        m.operation.data=dict(speed_limit=8);m.render();self.assertEqual(m.canvas.itemcget(m.ai_overlay.speed,'text'),'до 8×')
        m.pending_takeover=1;m.render();self.assertIn('Возвращаем',m.canvas.itemcget(m.ai_overlay.hint,'text'))
        m.operation.data=dict(speed_limit=None);m.render();self.assertEqual(m.canvas.itemcget(m.ai_overlay.speed,'text'),'Без лимита')
    def test_text_fits_all_supported_scales(self):
        m=self.m
        for scale in range(1,6):
            m.display_scale=scale;m.render();self.root.update_idletasks()
            for item in (m.ai_overlay.title,m.ai_overlay.speed,m.ai_overlay.hint):
                x1,y1,x2,y2=m.canvas.bbox(item)
                self.assertGreaterEqual(x1,0);self.assertGreaterEqual(y1,0)
                self.assertLessEqual(x2,240*scale);self.assertLessEqual(y2,160*scale)

class OverlayPreferenceTests(unittest.TestCase):
    def test_enabled_by_default_and_false_survives_reload(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);s=Settings(root);self.assertTrue(s['ai_control_overlay'])
            s.set('ai_control_overlay',False);self.assertFalse(Settings(root)['ai_control_overlay'])
