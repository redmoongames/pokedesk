"""Origins survive nested references; evolution warnings follow the actual graph."""
from pathlib import Path
from types import SimpleNamespace,MethodType
from unittest.mock import Mock
import sys,unittest,copy
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.catalog import catalog,species,move
from pokemon_red.evolution_reference import EvolutionIndex,outlook_text
from pokemon_red.trainer_navigation import DetailHistory,DetailRoute,TrainerDetails

class EvolutionReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.data=catalog(ROOT);cls.index=EvolutionIndex(cls.data['species'])
    def test_family_includes_previous_forms_and_every_branch(self):
        self.assertEqual(self.index.family(65),[63,64,65])
        self.assertEqual(set(self.index.family(134)),{133,134,135,136,196,197})
        self.assertEqual(set(self.index.family(237)),{106,107,236,237})
    def test_kadabra_role_play_is_lost_but_psychic_is_shared(self):
        result=self.index.outlook(64);self.assertEqual(result[272]['kind'],'exclusive');self.assertEqual(result[94]['kind'],'shared')
        self.assertEqual(self.index.outlook(65),{})
    def test_stone_evolution_does_not_falsely_lose_level_one_move(self):
        p=self.index.outlook(25);self.assertEqual(p[85]['kind'],'shared');self.assertEqual(p[85]['direct'],[(26,1)])
        self.assertEqual(p[97]['kind'],'exclusive');self.assertIn('Lv 1',outlook_text(p[85],self.data['species']))
    def test_branched_loss_is_different_from_loss_for_every_evolution(self):
        p=self.index.outlook(133);self.assertEqual(p[226]['kind'],'exclusive');self.assertEqual(p[44]['kind'],'branch');self.assertIn(135,p[44]['missing']);self.assertNotIn(134,p[44]['missing'])
    def test_later_form_can_reintroduce_a_move(self):
        def s(n,moves,next):return dict(id=n,national_id=n,evolutions=[dict(target=i) for i in next],learnset=[dict(move=i,level=lv) for i,lv in moves])
        index=EvolutionIndex({'1':s(1,[(10,5)],[2]),'2':s(2,[],[3]),'3':s(3,[(10,50)],[])})
        r=index.outlook(1)[10];self.assertEqual(r['kind'],'later');self.assertEqual(r['later'],[3])
    def test_known_unique_move_is_described_as_retained(self):
        text=outlook_text(self.index.outlook(64)[272],self.data['species'],known=True)
        self.assertIn('при эволюции он сохранится',text)
    def test_every_species_outlook_agrees_with_all_reachable_learnsets(self):
        for key,sp in self.data['species'].items():
            n=int(key);future=self.index.descendants(n);all_moves=set().union(*(set(self.index.levels(i)) for i in future))
            result=self.index.outlook(n)
            for m in self.index.levels(n):
                if future:self.assertEqual(result[m]['kind']=='exclusive',m not in all_moves,(n,m))
                else:self.assertNotIn(m,result)

class HistoryTests(unittest.TestCase):
    def test_nested_back_and_duplicate_open_keep_original_section(self):
        for source in ('overview','collection','automation'):
            h=DetailHistory();p=DetailRoute('pokemon','one');m=DetailRoute('move','60')
            self.assertTrue(h.push(p,source));self.assertFalse(h.push(p,'overview'));h.push(m,'overview');self.assertEqual(h.origin,source)
            self.assertEqual(h.back(),p);self.assertIsNone(h.back());self.assertEqual(h.origin,source)
            h.clear();h.push(p,'collection');self.assertEqual(h.origin,'collection')

class EmbeddedNavigationTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from pokemon_red.ui import BG,Tabs
        from pokemon_red.panel import TrainerPanel
        self.tk=tk;self.root=tk.Tk();self.root.geometry('580x780');self.root.configure(bg=BG);self.refresh=Mock()
        self.errors=[];self.root.report_callback_exception=lambda kind,error,tb:self.errors.append(error)
        self.mon=dict(uid='test',species_id=64,species='KADABRA',nickname='Test',level=30,hp=50,max_hp=70,status='В норме',experience=22000,exp_to_next_level=2294,checksum_valid=True,ability_id=39,stats=dict(attack=30,defense=25,speed=70,special_attack=80,special_defense=45),moves=[dict(move(60,ROOT),current_pp=20)])
        monitor=SimpleNamespace(folder=ROOT,last_state={'party':[self.mon]},last_inventory=dict(boxes=[]),inventory_snapshot=lambda:dict(ready=True,party=[self.mon],boxes=[]))
        p=self.panel=SimpleNamespace(window=self.root,monitor=monitor,active_section='overview',page_canvases={},page_containers={},refresh=self.refresh,refresh_slots=Mock(),collection_view=SimpleNamespace(refresh=Mock()))
        p.content=tk.Frame(self.root,bg=BG);p.content.pack(fill='both',expand=True);p.tabs=Tabs(p.content);p.tabs.pack(fill='both',expand=True);p.tabs.nav.pack_forget();p.settings_shell=tk.Frame(p.content,bg=BG);p.settings_tabs=Tabs(p.settings_shell)
        self.inputs={}
        for section in ('overview','collection','automation'):
            container=tk.Frame(p.tabs,bg=BG);canvas=tk.Canvas(container,bg=BG,scrollregion=(0,0,500,2200));canvas.pack(fill='both',expand=True);p.tabs.add(container,text=section);p.page_containers[section]=container;p.page_canvases[str(container)]=canvas
            self.inputs[section]=tk.StringVar(value='keep-'+section)
        p.show=MethodType(TrainerPanel.show,p);p.details=TrainerDetails(p,p.content);p.open_pokemon=p.details.open_pokemon;p.open_move=p.details.open_move;self.root.update()
    def tearDown(self):
        self.panel.details.clear();self.root.destroy();self.assertEqual(self.errors,[])
    def test_each_origin_nested_move_back_and_form_state_survive(self):
        for source in ('overview','collection','automation'):
            p=self.panel;p.show(source);self.root.update();origin=p.page_canvases[str(p.page_containers[source])];origin.yview_moveto(.35);old=origin.yview()[0]
            screen=p.open_pokemon(self.mon);self.root.update();page=screen.page
            self.assertEqual(p.active_section,source);self.assertEqual(len(p.details.screens),1)
            self.assertNotIn('Опыт',[text for _,text,_ in page.tabs.entries]);page.tabs.select(page.pages['moves']);page.select_form(65);page.learnset.query.set('PSYCHIC');self.root.update()
            p.open_move(94);self.root.update();self.assertEqual(len(p.details.screens),2);p.details.back();self.root.update()
            self.assertIs(p.details.screens[-1],screen);self.assertEqual(page.selected,65);self.assertEqual(page.learnset.query.get(),'PSYCHIC');self.assertIs(page.tabs.current,page.pages['moves'])
            p.details.back();self.root.update();self.assertFalse(p.details.active);self.assertEqual(p.active_section,source);self.assertEqual(self.inputs[source].get(),'keep-'+source);self.assertAlmostEqual(origin.yview()[0],old,places=2)
    def test_section_switch_clears_detail_and_sets_new_return_target(self):
        p=self.panel;p.show('automation');p.open_pokemon(self.mon);p.show('collection');self.root.update();self.assertFalse(p.details.active)
        p.open_pokemon(self.mon);p.details.back();self.root.update();self.assertEqual(p.active_section,'collection')
    def test_unique_highlight_and_per_form_filters(self):
        p=self.panel;page=p.open_pokemon(self.mon).page;page.tabs.select(page.pages['moves']);page.learnset.only_unique.set(True);page.learnset.fill();self.root.update()
        self.assertEqual(set(page.learnset.mapping.values()),{272});key=next(iter(page.learnset.mapping));self.assertIn('exclusive',page.learnset.view.item(key,'tags'))
        table=page.learnset.view.master;self.assertLess(page.learnset.preview.winfo_y()-(table.winfo_y()+table.winfo_height()),20);self.assertLess(table.winfo_height()-page.learnset.view.winfo_height(),10)
        page.select_form(65);self.assertFalse(page.learnset.only_unique.get());page.select_form(64);self.assertTrue(page.learnset.only_unique.get());self.assertEqual(set(page.learnset.mapping.values()),{272})
    def test_reference_only_page_and_move_from_root_return_without_new_windows(self):
        p=self.panel;p.show('automation');before=set(self.root.winfo_children());p.open_move(60);p.details.back();self.assertEqual(p.active_section,'automation')
        page=p.open_pokemon(species_id=133).page;self.assertEqual(set(page.pages),{'moves','base','source'});self.assertIsNone(page.uid)
        self.assertEqual(set(self.root.winfo_children()),before);self.assertEqual(len(page.forms.cards),6)
    def test_table_fits_trainer_width_and_hides_secondary_type_column(self):
        page=self.panel.open_pokemon(self.mon).page;page.tabs.select(page.pages['moves'])
        for width in (540,840):
            self.root.geometry(str(width)+'x780');self.root.update();view=page.learnset.view;columns=list(view['displaycolumns'])
            self.assertLessEqual(sum(view.column(c,'width') for c in columns),view.winfo_width()+2)
            self.assertEqual('type' in columns,page.pages['moves'].winfo_width()>=600)
    def test_live_evolution_updates_identity_without_resetting_browsed_form(self):
        page=self.panel.open_pokemon(self.mon).page;page.select_form(63);new=dict(self.mon,species_id=65,species='ALAKAZAM',hp=40);self.panel.monitor.last_state={'party':[new]};page.refresh(self.panel.monitor.last_state)
        self.assertEqual(page.current_number,65);self.assertEqual(page.selected,63);self.assertIn('40 / 70',page.health.cget('text'))
    def test_related_articles_keep_the_original_section_without_pokemon_stack(self):
        for origin,title in [('overview','Отряд'),('collection',str(__import__('pokemon_red.i18n',fromlist=['t']).t('design.collection')))]:
            p=self.panel;p.show(origin);self.root.update();canvas=p.page_canvases[str(p.page_containers[origin])];canvas.yview_moveto(.3);old_scroll=canvas.yview()[0]
            mon=dict(self.mon,species_id=65,species='ALAKAZAM');page=p.open_pokemon(mon).page;page.tabs.select(page.pages['source'])
            for number in (64,63,64,65):
                link=next(l for l in page.source_view.links if l.record['species_id']==number);link.invoke();self.root.update()
                self.assertEqual(len(p.details.screens),1);screen=p.details.screens[0];page=screen.page
                self.assertEqual(page.current_number,number);self.assertEqual(page.source_view.number,number);self.assertIsNone(page.uid)
                self.assertIs(page.tabs.current,page.pages['source']);self.assertEqual(screen.back.cget('text'),'← '+title)
                self.assertEqual(p.details.history.origin,origin);self.assertEqual(len(p.details.history.routes),1)
            p.details.back();self.root.update();self.assertFalse(p.details.active);self.assertEqual(p.active_section,origin)
            self.assertAlmostEqual(canvas.yview()[0],old_scroll,places=2);self.assertEqual(self.inputs[origin].get(),'keep-'+origin)
    def test_source_tracks_article_identity_and_learnset_link_opens_that_species(self):
        p=self.panel;page=p.open_pokemon(dict(self.mon,species_id=65,species='ALAKAZAM')).page
        page.select_form(63);self.root.update();self.assertEqual(page.source_view.number,65)
        page.open_source();self.root.update();current=p.details.screens[0].page
        self.assertEqual(current.current_number,63);self.assertEqual(current.source_view.number,63);self.assertEqual(len(p.details.screens),1)
        self.assertIs(current.tabs.current,current.pages['source'])
    def test_related_article_still_has_normal_back_from_a_move(self):
        p=self.panel;p.show('collection');p.open_pokemon(self.mon);p.details.open_related_pokemon(63);page=p.details.screens[0].page
        p.open_move(94);self.root.update();self.assertEqual(len(p.details.screens),2)
        p.details.back();self.root.update();self.assertIs(p.details.screens[0].page,page)
        p.details.back();self.root.update();self.assertEqual(p.active_section,'collection');self.assertFalse(p.details.active)
    def test_related_card_mouse_press_opens_a_real_species_article(self):
        p=self.panel;page=p.open_pokemon(dict(self.mon,species_id=65,species='ALAKAZAM')).page;page.tabs.select(page.pages['source']);self.root.update()
        link=next(l for l in page.source_view.links if l.record['species_id']==64)
        link.event_generate('<ButtonPress-1>',x=30,y=20);self.root.update()
        self.assertEqual(p.details.screens[0].page.current_number,64);self.assertEqual(len(p.details.screens),1)
    def test_source_search_filters_exact_maps_and_has_no_inline_form_selector(self):
        page=self.panel.open_pokemon(species_id=63).page;view=page.source_view
        page.tabs.select(page.pages['source']);self.root.update()
        self.assertLess(view.table_frame.winfo_height()-view.table.winfo_height(),10)
        self.assertIs(page.forms.frame.master,page.pages['moves']);self.assertFalse(hasattr(view,'forms'))
        view.query.set('Route24');self.root.update();self.assertEqual(len(view.rows),1);self.assertEqual(view.rows[0]['probability'],15)
        view.query.set('нет такого места');self.root.update();self.assertFalse(view.table_frame.winfo_manager())
        view.query.set('');self.root.update();self.assertEqual(len(view.rows),2);self.assertTrue(view.table_frame.winfo_manager())
    def test_source_view_handles_switching_between_wild_and_nonwild_data(self):
        page=self.panel.open_pokemon(species_id=65).page;view=page.source_view
        for number,count in [(63,2),(65,0),(64,2)]:
            view.set_species(number);self.root.update();self.assertEqual(len(view.rows),count)
            self.assertEqual(bool(view.table_frame.winfo_manager()),bool(count))
    def test_location_click_uses_filtered_row_and_back_preserves_the_article(self):
        for origin in ('overview','collection'):
            p=self.panel;p.show(origin);page=p.open_pokemon(self.mon).page;page.tabs.select(page.pages['source'])
            view=page.source_view;view.query.set('B1F');self.root.update();screen=p.details.screens[0]
            screen.canvas.yview_moveto(.5);self.root.update();old_scroll=screen.canvas.yview()[0];self.refresh.reset_mock()
            # Click the drawn body, rather than the invisible ttk data model.
            view.table.body.event_generate('<ButtonPress-1>',x=25,y=12);view.table.body.event_generate('<ButtonRelease-1>',x=25,y=12);self.root.update()
            self.assertEqual(len(p.details.screens),2);map_screen=p.details.screens[-1]
            self.assertEqual(map_screen.page.place['name'],'CeruleanCave_B1F');self.assertEqual(map_screen.back.cget('text'),'← Pokémon')
            self.assertTrue(map_screen.page.canvas.find_withtag('destination'))
            self.assertFalse(self.refresh.called)
            p.details.back();self.root.update();self.assertIs(p.details.screens[0],screen);self.assertEqual(view.query.get(),'B1F')
            self.assertIs(page.tabs.current,page.pages['source']);self.assertAlmostEqual(screen.canvas.yview()[0],old_scroll,places=2)
            p.details.back();self.root.update();self.assertEqual(p.active_section,origin)
    def test_location_selection_does_not_open_until_activated(self):
        p=self.panel;page=p.open_pokemon(species_id=63).page;page.tabs.select(page.pages['source']);self.root.update();view=page.source_view;table=view.table
        table.selection_set('1');self.root.update();self.assertEqual(len(p.details.screens),1)
        table.event_generate('<ButtonPress-1>',x=20,y=10);table.event_generate('<ButtonRelease-1>',x=20,y=10);self.root.update();self.assertEqual(len(p.details.screens),1)
        table.body.event_generate('<ButtonPress-1>',x=20,y=10);table.body.event_generate('<ButtonRelease-1>',x=65,y=10);self.root.update();self.assertEqual(len(p.details.screens),1)
        table.selection_set('1');view.open_location();self.root.update();self.assertEqual(p.details.screens[-1].page.place['name'],'Route25')
    def test_location_after_related_species_keeps_original_return_section(self):
        p=self.panel;p.show('collection');p.open_pokemon(dict(self.mon,species_id=65));p.details.open_related_pokemon(64);page=p.details.screens[0].page
        page.source_view.open_location();self.root.update();p.details.back();self.root.update();self.assertIs(p.details.screens[0].page,page)
        self.assertEqual(p.details.screens[0].back.cget('text'),__import__('pokemon_red.i18n',fromlist=['t']).t('design.back_collection'));p.details.back();self.root.update();self.assertEqual(p.active_section,'collection')

if __name__=='__main__':unittest.main()
