"""Real Tk viewports: partial rows, event coordinates and nested scroll routing."""
from pathlib import Path
import sys,time,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
import tkinter as tk
from pokemon_red.ui import theme,Select
from pokemon_red.table import Table,ChoiceList
from pokemon_red.scrolling import Controller,install,Motion

class PixelTableTests(unittest.TestCase):
    def setUp(self):
        self.root=tk.Tk();self.root.geometry('500x330');theme(self.root);self.errors=[]
        self.root.report_callback_exception=lambda kind,error,tb:self.errors.append(error)
        self.table=Table(self.root,columns=('name','count'),show='headings',height=5,style='Trainer.Treeview')
        self.table.heading('name',text='Предмет');self.table.column('name',width=300);self.table.column('count',width=70,stretch=False)
        self.table.pack(fill='both',expand=True)
        for i in range(100):self.table.insert('','end',iid=str(i),values=('Row '+str(i),i))
        self.root.update()
    def tearDown(self):
        self.root.destroy();self.assertEqual(self.errors,[])
    def drive(self,seconds=.35):
        end=time.monotonic()+seconds
        while time.monotonic()<end:self.root.update();time.sleep(.003)
    def test_viewport_can_clip_a_row_at_a_fractional_pixel(self):
        self.table.scroll_to_pixel(13.25);self.root.update()
        self.assertEqual(self.table.offset,13.25)
        self.assertLess(self.table.bbox('0')[1],self.table.header_height)
        self.assertEqual(self.table.identify_row(self.table.header_height+1),'0')
        self.assertEqual(self.table.identify_row(self.table.header_height+self.table.rowheight),'1')
    def test_tree_icons_and_headers_are_painted_and_only_visible_rows_exist(self):
        self.table.configure(show='tree headings');self.table.column('#0',width=48,stretch=False)
        photo=tk.PhotoImage(master=self.root,width=20,height=20);self.table.item('0',image=photo)
        self.root.update()
        self.assertEqual(self.table.header_height,34)
        self.assertTrue(any(self.table.header.type(i)=='text' for i in self.table.header.find_all()))
        self.assertTrue(any(self.table.body.type(i)=='image' for i in self.table.body.find_all()))
        self.assertLess(len(self.table.body.find_all()),100)
    def test_router_smooths_small_gestures_without_a_row_jump(self):
        install(self.root).route(self.table.body,9.5)
        self.assertGreater(self.table.offset,0);self.assertLess(self.table.offset,9.5)
        self.drive()
        self.assertAlmostEqual(self.table.offset,9.5)
        self.assertLess(self.table.offset,self.table.rowheight)
    def test_pending_motion_reverses_without_consuming_old_momentum(self):
        motion=Motion();motion.add(100,0,1000);motion.step();previous=motion.position
        motion.add(-3,previous,1000);motion.step()
        self.assertLess(motion.position,previous)
    def test_text_scroll_also_allows_partially_visible_lines(self):
        self.table.pack_forget();text=tk.Text(self.root,font=('Helvetica',12),padx=0,pady=0)
        text.pack(fill='both',expand=True);text.insert('1.0','\n'.join('Line '+str(i) for i in range(100)));self.root.update()
        install(self.root).route(text,7);self.drive()
        self.assertGreater(text.yview()[0],0);self.assertLess(text.dlineinfo('@0,0')[1],0)
    def test_canvas_mouse_events_keep_the_table_coordinates(self):
        seen=[];self.table.bind('<ButtonRelease-1>',lambda e:seen.append((e.widget,self.table.identify_row(e.y))))
        self.table.scroll_to_pixel(17);self.root.update()
        self.table.body.event_generate('<ButtonPress-1>',x=60,y=10)
        self.table.body.event_generate('<ButtonRelease-1>',x=60,y=10)
        self.root.update()
        self.assertEqual(self.table.selection(),('0',));self.assertEqual(seen,[(self.table,'0')])
    def test_header_sort_does_not_select_a_data_row(self):
        called=[];self.table.heading('name',command=lambda:called.append(True))
        self.table.header.event_generate('<ButtonPress-1>',x=30,y=15);self.root.update()
        self.assertEqual(called,[True]);self.assertEqual(self.table.selection(),())
    def test_painting_preserves_zero_padded_numbers(self):
        self.table.item('0',values=('001','02'));self.root.update()
        painted=[self.table.body.itemcget(i,'text') for i in self.table.body.find_all() if self.table.body.type(i)=='text']
        self.assertIn('001',painted);self.assertIn('02',painted)
    def test_selection_tags_and_order_survive_sort_and_scroll(self):
        self.table.tag_configure('special',foreground='#ffdc91')
        self.table.item('7',tags=('special',));self.table.selection_set('7');self.table.move('7','',0);self.table.see('7');self.root.update()
        self.assertEqual(self.table.get_children()[0],'7');self.assertEqual(self.table.selection(),('7',))
        self.assertIn('special',self.table.item('7','tags'));self.assertEqual(self.table.offset,0)
    def test_destroy_cancels_animation_and_releases_unmapped_model(self):
        controller=self.table._smooth_controller=Controller(self.table);controller.scroll(100)
        model=self.table.model;self.table.destroy();self.root.update()
        self.assertIsNone(controller.timer);self.assertFalse(model.winfo_exists())
    def test_dropdown_uses_the_same_pixel_viewport_without_a_grab(self):
        variable=tk.StringVar(value='B');picked=[];select=Select(self.root,variable,values=list('ABCDEFGHIJKLMN'),command=picked.append)
        select.place(x=15,y=15,width=250);self.root.update();select.open();self.root.update()
        listing=next(w for w in select.popup.winfo_children() if isinstance(w,ChoiceList))
        self.assertEqual(listing.curselection(),(1,));listing.scroll_to_pixel(7.5);self.root.update()
        self.assertEqual(listing.offset,7.5);listing.key('Down');self.assertEqual(listing.curselection(),(2,))
        listing.event_generate('<Return>');self.root.update()
        self.assertEqual(variable.get(),'C');self.assertEqual(picked,['C']);self.assertIsNone(self.root.grab_current())

class NestedScrollTests(unittest.TestCase):
    def test_finished_inner_list_passes_the_gesture_to_the_page(self):
        root=tk.Tk();root.geometry('500x350');theme(root)
        try:
            canvas=tk.Canvas(root,scrollregion=(0,0,450,1200),yscrollincrement=1);canvas.pack(fill='both',expand=True)
            frame=tk.Frame(canvas,width=450,height=1200);frame.pack_propagate(False);canvas.create_window(0,0,anchor='nw',window=frame,width=450,height=1200)
            table=Table(frame,columns=('name',),show='headings',height=3);table.pack(fill='x')
            for i in range(40):table.insert('','end',iid=str(i),values=(i,))
            root.update();table.yview_moveto(1);old=table.offset
            install(root).route(table.body,40)
            end=time.monotonic()+.35
            while time.monotonic()<end:root.update();time.sleep(.003)
            self.assertEqual(table.offset,old);self.assertGreater(canvas.yview()[0],0)
        finally:root.destroy()

if __name__=='__main__':unittest.main()
