"""FireRed/LeafGreen intro and starter search through verified game buttons."""
from .new_game_config import NewGameConfig,STATS
from .telemetry import symbols,read_controls,decode_text,read_map
from .game_layout import save_block
from .acquisition_play import AcquisitionAttention,JobPaused
from .acquisition import read_json,write_json
from .i18n import t
import time,hashlib

# Page IDs and keyboard rows in the pinned Kanto naming_screen.c.
PAGES={1:('ABCDEF .','GHIJKL ,','MNOPQRS','TUVWXYZ'),2:('abcdef .','ghijkl ,','mnopqrs','tuvwxyz'),0:('01234','56789','!?♂♀/-',"…“”‘’")}

def naming_state(game):
    sy=symbols(game.root);p=game.read32(sy['sNamingScreen'])
    if not 0x02000000<=p<0x02040000-0x1e40:raise AcquisitionAttention(t('prologue.naming_unavailable'))
    cursor=sy['gSprites']+game.read8(p+0x1e23)*68
    return dict(pointer=p,state=game.read8(p+0x1e10),page=game.read8(p+0x1e22),x=game.read16(cursor+0x2e),y=game.read16(cursor+0x30),text=decode_text(game.read_bytes(p+0x1800,16)),template=game.read8(p+0x1e2c))

def enter_name(p,name):
    def wait():
        for _ in range(240):
            state=naming_state(p.g)
            if state['state']==2:return state
            p.advance(1)
        raise AcquisitionAttention(t('prologue.naming_unavailable'))
    state=wait()
    for _ in range(12):
        if not state['text']:break
        p.tap('B',wait=12);state=wait()
    for index,char in enumerate(name):
        page,row,column=next((page,y,text.index(char)) for page,rows in PAGES.items() for y,text in enumerate(rows) if char in text)
        for _ in range(3):
            state=wait()
            if state['page']==page:break
            p.tap('SELECT',wait=36)
        for _ in range(24):
            state=wait();x,y=state['x'],state['y']
            if (x,y)==(column,row):break
            # Leave the button column before selecting a keyboard row.
            key='LEFT' if x==(6 if page==0 else 8) else 'DOWN' if y<row else 'UP' if y>row else 'RIGHT' if x<column else 'LEFT'
            p.tap(key,wait=10)
        else:raise AcquisitionAttention(t('prologue.naming_unavailable'))
        p.tap('A',wait=16)
        actual=wait()['text']
        if actual!=name[:index+1].rstrip():raise AcquisitionAttention(t('prologue.name_mismatch'))
    p.tap('START',wait=20);p.tap('A',wait=36)
    for _ in range(300):
        if read_controls(p.g)['callback']!='CB2_NamingScreen':return
        p.advance(1)
    raise AcquisitionAttention(t('prologue.naming_unavailable'))

class Prologue:
    def __init__(self,p,config,progress=None):
        self.p=p;self.w=p.w;self.g=p.g;self.config=NewGameConfig.parse(config);self.progress=dict(progress or {});self.progress.setdefault('phase','intro');self.progress.setdefault('attempts',0)
    def pace(self,speed,key):
        from .worker_pacing import FramePacer
        self.w.pacer=FramePacer(speed) if speed else None
        self.w.update(stage=t(key),speed_limit=speed,prologue=self.progress)
    def run(self):
        phases=('intro','laboratory','choice','search','finish','outside','complete')
        while self.progress['phase']!='complete':
            phase=self.progress['phase']
            if phase not in phases:raise ValueError(t('prologue.invalid_options'))
            before=self.g.capture_save(metadata=False).state
            try:getattr(self,phase)()
            except Exception:
                if phase!='search':self.g.restore_checkpoint(before)
                raise
            self.progress['phase']=phases[phases.index(phase)+1]
            self.p.persist()
            write_json(self.g.root/'Data/prologue-checkpoint.json',dict(prologue=self.progress,main_hashes={n:hashlib.sha256((self.g.root/'Data'/n).read_bytes()).hexdigest() for n in ('FireRed.state','FireRed.sav')}))
            self.w.update(prologue=self.progress)
            self.w.safe_point()
        state=self.p.state();mon=next((m for m in state['party'] if self.config.matches(m) or m.get('uid')==self.progress.get('accepted_uid')),None)
        if self.g.read8(save_block(self.g,2)+8)!=self.config.player_gender or state['player']!=self.config.player_name or state['map']['name']!='PalletTown' or not mon or state['controls']['field_locked'] or state['in_battle']:raise AcquisitionAttention(t('prologue.final_mismatch'))
        self.p.save_game();return mon
    def intro(self):
        self.pace(16,'prologue.phase_intro');p=self.p;named=set()
        if p.state().get('party'):raise AcquisitionAttention(t('prologue.not_new_game'))
        for _ in range(1500):
            c=read_controls(self.g);tasks={v['name'] for v in c['tasks']}
            if c['callback']=='CB2_Overworld' and p.state()['map']['name']=='PalletTown_PlayersHouse_2F' and not c['field_locked']:
                if p.state()['player']!=self.config.player_name:raise AcquisitionAttention(t('prologue.name_mismatch'))
                return
            if c['callback']=='CB2_NamingScreen':
                p.advance(30);state=naming_state(self.g);which=state['template']
                if which in named:raise AcquisitionAttention(t('prologue.name_mismatch'))
                enter_name(p,self.config.player_name if which==0 else self.config.rival_name);named.add(which);continue
            if 'Task_OakSpeech_HandleGenderInput' in tasks:
                target=self.config.player_gender
                if c['menu_cursor']!=target:p.tap('DOWN' if target else 'UP',wait=12)
                else:p.tap('A',wait=24)
            elif 'Task_OakSpeech_HandleRivalNameInput' in tasks:
                p.tap('UP' if c['menu_cursor'] else 'A',wait=20)
            elif c['callback'] in ('CB2_InitTitleScreen','CB2_MainMenu','CB2_InitMainMenu') or any('TitleScreen' in v for v in tasks):p.tap('START',wait=60)
            else:p.tap('A',wait=24)
        raise AcquisitionAttention(t('prologue.intro_timeout'))
    def laboratory(self):
        self.pace(16,'prologue.phase_lab');p=self.p
        p.go((10,3));p.tap('UP',frames=16,wait=24);p.transition('LEFT','PalletTown_PlayersHouse_1F');p.settle(button='A')
        p.go((4,7));p.transition('DOWN','PalletTown');p.go((12,1),allow_trigger=True)
        for _ in range(600):
            s=p.state()
            if s['map']['name']=='PalletTown_ProfessorOaksLab' and not s['controls']['field_locked'] and s['controls']['callback']=='CB2_Overworld':p.advance(60);return
            p.tap('A',wait=24)
        raise AcquisitionAttention(t('prologue.lab_timeout'))
    def choice(self):
        self.pace(12,'prologue.phase_choice');p=self.p
        x={1:8,4:10,7:9}[self.config.species_id];p.go((x,5));p.advance(30);p.tap('UP',frames=16,wait=24);p.tap('A',wait=120)
        for _ in range(40):
            c=read_controls(self.g)
            if any(v['name']=='Task_YesNoMenu_HandleInput' for v in c['tasks']):break
            p.tap('A',wait=24)
        else:raise AcquisitionAttention(t('prologue.choice_timeout'))
        if c['menu_cursor']:p.tap('UP')
        p.tap('A',wait=240)
        if p.state()['party'] or 'energetic' not in p.text().lower():raise AcquisitionAttention(t('prologue.choice_timeout'))
    def search(self):
        self.pace(None,'prologue.phase_search')
        from .starter_search import search
        mon,stats=search(self.g,self.config,self.w,self.progress)
        self.w.event('starter_search_finished',dict(workers=stats['workers'],attempts=stats['attempts'],seconds=stats['seconds'],candidates_per_second=stats['candidates_per_second']))
    def finish(self):
        self.pace(16,'prologue.phase_rival');p=self.p
        for _ in range(200):
            s=p.state()
            if p.var(0x4055)>=3 and not s['controls']['field_locked']:break
            p.tap('B',wait=24)
        else:raise AcquisitionAttention(t('prologue.choice_timeout'))
        p.go((6,7));p.tap('DOWN',frames=16,wait=60)
        for _ in range(200):
            if p.state()['in_battle']:break
            p.tap('A',wait=24)
        else:raise AcquisitionAttention(t('prologue.rival_timeout'))
        p.battle('fight',trainer=True);p.settle(button='A')
        if p.var(0x4055)!=4:raise AcquisitionAttention(t('prologue.rival_timeout'))
    def outside(self):
        self.pace(16,'prologue.phase_outside');p=self.p;s=p.state()
        if s['map']['name']=='PalletTown_PlayersHouse_1F':p.go((4,7));p.transition('DOWN','PalletTown')
        elif s['map']['name']=='PalletTown_ProfessorOaksLab':p.go((6,11));p.transition('DOWN','PalletTown')
        if p.state()['map']['name']!='PalletTown':raise AcquisitionAttention(t('prologue.final_mismatch'))
