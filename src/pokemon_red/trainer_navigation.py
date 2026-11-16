from .i18n import t
"""One trainer detail stack; hidden source pages keep their widgets and inputs."""
from dataclasses import dataclass
from . import localized_tk as tk
from .ui import BG,MUTED,Button,label
from .move_details_ui import ArticleBody

SECTION_NAMES={'overview':'Отряд','collection':t('design.collection'),'inventory':'Инвентарь','automation':'Автоматизация','settings':'Настройки','slots':'Сохранения','journal':'Журнал','scripts':'Скрипты','location':'Локация','tasks':t('workspace.tasks'),'hotkeys':t('workspace.settings')}

@dataclass(frozen=True)
class DetailRoute:
    kind:str
    key:str

class DetailHistory:
    def __init__(self):self.origin='overview';self.routes=[]
    def push(self,route,origin):
        if self.routes and self.routes[-1]==route:return False
        if not self.routes:self.origin=origin
        self.routes.append(route);return True
    def back(self):
        if self.routes:self.routes.pop()
        return self.routes[-1] if self.routes else None
    def clear(self):self.routes.clear()

class DetailScreen:
    def __init__(self,router,title,back_title,*,scroll=True):
        self.frame=tk.Frame(router.host,bg=BG);bar=tk.Frame(self.frame,bg=BG,pady=6);bar.pack(fill='x')
        self.back=Button(bar,back_title,router.back,variant='ghost',height=32);self.back.pack(side='left');label(bar,title,10,MUTED,pack=False).pack(side='right')
        self.article=ArticleBody(self.frame) if scroll else None;self.body=self.article.body if self.article else tk.Frame(self.frame,bg=BG)
        if not scroll:self.body.pack(fill='both',expand=True)
        self.refresh=lambda state:None;self.suspend=lambda:None
    @property
    def canvas(self):return getattr(self,'embedded_canvas',None) or (self.article.canvas if self.article else None)
    def destroy(self):
        if hasattr(self,'training'):self.training.close()
        if hasattr(self,'editor'):self.editor.close()
        if hasattr(self,'acquisition'):self.acquisition.close()
        self.frame.destroy()

class TrainerDetails:
    def __init__(self,panel,parent):
        self.panel=panel;self.host=tk.Frame(parent,bg=BG);self.history=DetailHistory();self.screens=[];self.origin_scroll=0;self.origin_canvas=None;self.parked={}
    @property
    def active(self):return bool(self.screens)
    @property
    def current_canvas(self):return self.screens[-1].canvas if self.screens else None
    def origin(self):
        p=self.panel
        if p.active_section=='settings':return next((k for k,c in p.page_containers.items() if str(c)==p.settings_tabs.select()),'settings')
        return p.active_section
    def back_caption(self,origin):
        if getattr(self.panel,'workspace',False):
            if origin=='collection':
                key={'party':'party','owned':'collection','dex':'dex'}.get(self.panel.collection_view.current,'pokemon')
                title=t('workspace.'+key)
            else:title={'inventory':t('workspace.items'),'location':t('workspace.world'),'tasks':t('workspace.tasks')}.get(origin,SECTION_NAMES.get(origin,t('workspace.settings')))
            return t('workspace.back_to',section=title)
        return t('design.back_collection') if origin=='collection' else '← '+SECTION_NAMES[origin]
    def push(self,route,title,builder,*,scroll=True,replace=False):
        origin=self.origin()
        if replace and self.screens:
            # A related species is a new article, with the original section as Back.
            origin=self.history.origin
            screen=DetailScreen(self,title,self.back_caption(origin),scroll=scroll)
            try:builder(screen)
            except Exception:screen.destroy();raise
            for old in self.screens:old.destroy()
            self.screens=[screen];self.history.routes=[route]
            screen.frame.pack(fill='both',expand=True);self.panel.window.lift();return screen
        if not self.history.push(route,origin):
            self.panel.window.deiconify();self.panel.window.lift();return self.screens[-1]
        if not self.screens:
            p=self.panel;self.origin_canvas=p.page_canvases[str(p.page_containers[origin])];self.origin_scroll=self.origin_canvas.yview()[0]
            p.tabs.pack_forget();p.settings_shell.pack_forget();self.host.pack(fill='both',expand=True)
        else:self.screens[-1].suspend();self.screens[-1].frame.pack_forget()
        previous='Pokémon' if len(self.screens) else SECTION_NAMES[origin]
        screen=DetailScreen(self,title,self.back_caption(origin) if not self.screens else '← '+previous,scroll=scroll)
        try:builder(screen)
        except Exception:
            screen.destroy();self.history.back()
            if self.screens:self.screens[-1].frame.pack(fill='both',expand=True)
            else:self.host.pack_forget();self.panel.show(origin,_detail_return=True)
            raise
        self.screens.append(screen);screen.frame.pack(fill='both',expand=True);self.panel.window.deiconify();self.panel.window.lift();return screen
    def park(self):
        if not self.screens:return
        self.screens[-1].suspend();self.screens[-1].frame.pack_forget();self.host.pack_forget()
        self.parked[self.history.origin]=(self.history,self.screens,self.origin_scroll,self.origin_canvas)
        self.history=DetailHistory();self.screens=[];self.origin_scroll=0;self.origin_canvas=None
    def restore(self,origin):
        saved=self.parked.pop(origin,None)
        if not saved:return False
        self.history,self.screens,self.origin_scroll,self.origin_canvas=saved
        self.panel.tabs.pack_forget();self.panel.settings_shell.pack_forget();self.host.pack(fill='both',expand=True)
        self.screens[-1].frame.pack(fill='both',expand=True);self.screens[-1].refresh(self.panel.monitor.last_state)
        return True
    def close(self):
        self.clear()
        for _,screens,_,_ in self.parked.values():
            for screen in screens:screen.destroy()
        self.parked.clear()
    def open_pokemon(self,mon=None,*,uid=None,species_id=None,replace=False,initial_tab=None):
        from .pokemon_page import PokemonPage
        if mon is None and uid:
            inv=getattr(self.panel.monitor,'last_inventory',{}) or {}
            rows=(self.panel.monitor.last_state or {}).get('party',[])+inv.get('boxes',[])+inv.get('daycare',[])
            mon=next((m for m in rows if m['uid']==uid),None)
            if mon is None:
                inv=self.panel.monitor.inventory_snapshot();mon=next((m for m in inv.get('party',[])+inv.get('boxes',[])+inv.get('daycare',[]) if m['uid']==uid),None)
            if mon is None:return
        number=species_id or (mon or {}).get('species_id')
        from .catalog import species
        if not number or not species(number,self.panel.monitor.folder):return
        key=('enemy:' if (mon or {}).get('opponent') else 'owned:')+str((mon or {}).get('uid',uid)) if mon else 'species:'+str(number)
        def build(screen):
            screen.page=PokemonPage(self.panel,screen.body,number,mon);screen.refresh=screen.page.refresh
            if initial_tab in screen.page.pages:screen.page.tabs.select(screen.page.pages[initial_tab])
        return self.push(DetailRoute('pokemon',key),'Pokémon',build,replace=replace)
    def open_training(self,uid=None):
        from .training_view import TrainingSetup
        from .scrolling import Scrollbar
        if self.screens and self.history.routes[-1].kind=='training':
            view=self.screens[-1].training
            if uid:view.trainee.set(uid)
            self.panel.window.deiconify();self.panel.window.lift();return view
        def build(screen):
            shell=tk.Frame(screen.body,bg=BG);shell.pack(fill='both',expand=True)
            canvas=tk.Canvas(shell,bg=BG,highlightthickness=0,yscrollincrement=1);scroll=Scrollbar(shell,command=canvas.yview);canvas.configure(yscrollcommand=scroll.set);scroll.pack(side='right',fill='y');canvas.pack(side='left',fill='both',expand=True)
            body=tk.Frame(canvas,bg=BG,padx=4,pady=8);item=canvas.create_window(0,0,anchor='nw',window=body);body.bind('<Configure>',lambda _:canvas.configure(scrollregion=canvas.bbox('all')));canvas.bind('<Configure>',lambda e:canvas.itemconfigure(item,width=e.width));screen.embedded_canvas=canvas
            view=TrainingSetup(self.panel,body,dock=shell,embedded=True);screen.training=view;screen.refresh=view.refresh;screen.suspend=view.suspend
            if uid:view.trainee.set(uid)
            manager=self.panel.automation_windows;manager.tools['training']=dict(window=screen.frame,view=view,embedded=True)
            screen.frame.bind('<Unmap>',lambda e:view.suspend() if e.widget is screen.frame and not view.closed else None,add='+')
        screen=self.push(DetailRoute('training',uid or 'choose'),t('training.auto_train'),build,scroll=False)
        screen.refresh(self.panel.monitor.last_state);return screen.training
    def open_party_editor(self):
        from .party_editor import PartyEditor
        def build(screen):
            dock=tk.Frame(screen.frame,bg=BG,padx=4,pady=8);dock.pack(side='bottom',fill='x',before=screen.article)
            screen.editor=PartyEditor(self.panel,screen.body,dock=dock)
            screen.refresh=screen.editor.refresh;screen.suspend=screen.editor.suspend
        return self.push(DetailRoute('party_editor','draft'),t('party_edit.title'),build)
    def open_acquisition(self):
        from .acquisition_view import AcquisitionView
        def build(screen):
            screen.acquisition=AcquisitionView(self.panel,screen.body,screen.body,embedded=True)
            screen.acquisition.actions.pack(fill='x')
            screen.refresh=lambda state:screen.acquisition.refresh()
        screen=self.push(DetailRoute('acquisition','setup'),t('workspace.catch_setup'),build)
        screen.refresh(self.panel.monitor.last_state);return screen.acquisition
    def open_item(self,number):
        def build(screen):self.panel.inventory_view.build_article(screen.body,number)
        return self.push(DetailRoute('item',str(number)),t('workspace.item'),build)
    def open_related_pokemon(self,number):
        return self.open_pokemon(species_id=number,replace=True,initial_tab='source')
    def open_location_map(self,name,*,encounter=None):
        from .region_map import destination
        from .location_map_ui import LocationMapView
        place=destination(self.panel.monitor.folder,name)
        if place is None:return
        def build(screen):screen.page=LocationMapView(self.panel,screen.body,place,encounter)
        return self.push(DetailRoute('location',name),'Карта',build)
    def open_move(self,number):
        from .catalog import move
        if not move(number,self.panel.monitor.folder):return
        from .move_details_ui import build_move
        def build(screen):screen.article=build_move(self.panel,number,screen.body)
        return self.push(DetailRoute('move',str(number)),'Приём',build,scroll=False)
    def back(self):
        if not self.screens:return
        self.screens.pop().destroy();self.history.back()
        if self.screens:
            screen=self.screens[-1];screen.frame.pack(fill='both',expand=True);screen.refresh(self.panel.monitor.last_state)
        else:
            self.host.pack_forget();self.panel.show(self.history.origin,_detail_return=True)
            canvas=self.origin_canvas;fraction=self.origin_scroll
            def restore():
                if not self.active and canvas.winfo_exists():
                    if getattr(canvas,'_smooth_controller',None):canvas._smooth_controller.cancel()
                    canvas.yview_moveto(fraction)
            self.panel.window.after_idle(restore)
    def clear(self):
        for screen in self.screens:screen.destroy()
        self.screens=[];self.history.clear();self.host.pack_forget()
    def refresh(self,state):
        if self.screens:self.screens[-1].refresh(state)
