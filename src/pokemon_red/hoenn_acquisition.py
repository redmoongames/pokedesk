"""RS starter story adapter. Shared jobs own retries, checkpoints and results."""
import time
from .acquisition import read_json,write_json,starters_for
from .acquisition_play import AcquisitionAttention
from .journey import Journey
from .telemetry import read_map

CENTER='OldaleTown_PokemonCenter_1F'

def prepare_choice(worker):
    p=worker.player;target={277:0,280:1,283:2}[worker.config.species_id]
    p.go((7,15));p.tap('UP',frames=16);p.tap('A',wait=120)
    for _ in range(100):
        task=next((t for t in p.state()['controls']['tasks'] if t['name']=='Task_StarterChoose2'),None)
        if task:
            if task['data'][0]==target:p.tap('A',wait=120);break
            p.tap('RIGHT' if task['data'][0]<target else 'LEFT')
        else:p.advance(6)
    else:raise AcquisitionAttention('Не открылся выбор стартового Хоэнна')
    if 'Task_StarterChoose5' not in p.tasks() or p.state()['party']:raise AcquisitionAttention('Не подтверждена точка перед генерацией стартового Хоэнна')

def known_story(p,operation):
    """Only this explicit prologue owns its known mandatory story triggers."""
    try:return operation()
    except AcquisitionAttention as error:
        s=p.state();expected=p.var(0x4084)>=4 and s['map']['name'] in ('OldaleTown','LittlerootTown','LittlerootTown_ProfessorBirchsLab') and s['controls']['field_locked']
        if not expected or not any(text in str(error) for text in ('Неожиданный диалог','Ходьба прервана: interrupted')):raise
        p.settle(button='A')
        return operation()

def initial_battle(w):
    p=w.player
    for _ in range(400):
        if p.state()['in_battle']:break
        p.tap('A',wait=24)
    p.battle('fight')
    for _ in range(800):
        s=p.state()
        if s['map']['name']!='LittlerootTown_ProfessorBirchsLab':p.tap('A',wait=24);continue
        if p.var(0x4084)>=3 and not s['controls']['field_locked']:return
        if 'Task_YesNoMenu_HandleInput' in p.tasks(s):
            # The first question is optional naming; the second must be Yes.
            naming='nickname' in p.text().lower()
            if naming:p.tap('B')
            else:p.tap('A' if s['controls']['menu_cursor']==0 else 'UP')
        else:p.tap('A',wait=24)
    raise AcquisitionAttention('Не завершилось получение стартового у профессора Бирча')

def train(w,target):
    p=w.player
    from .learning import LearningRuntime
    from .move_plan import default_moves,compile_plan
    mon=next(m for m in p.state()['party'] if m['uid']==w.uid)
    if mon['level']>=target:return
    plan=compile_plan(mon,target,default_moves(mon,target,p.root,mode='stay'),p.root,mode='stay')
    p.learning=LearningRuntime(plan,event=w.event,checkpoint=lambda _:p.checkpoint('learning-'+__import__('uuid').uuid4().hex),suspend=lambda:None)
    try:
        for _ in range(2000):
            s=p.state();mon=next(m for m in s['party'] if m['uid']==w.uid)
            if mon['level']>=target:return
            p.nav.travel(CENTER);p.heal();p.nav.travel('Route101')
            from .navigation import safe_grass_pair
            pair=safe_grass_pair(read_map(p.g),(p.state()['position']['x'],p.state()['position']['y']))['pair']
            for turn in range(3000):
                s=p.state();mon=next(m for m in s['party'] if m['uid']==w.uid)
                if mon['level']>=target or mon['hp']*100<mon['max_hp']*65 or mon.get('status_code') or not any(m.get('power') and m['current_pp'] for m in mon['moves']):break
                p.go(pair[turn%2],encounters='fight')
            p.persist();w.safe_point()
        raise AcquisitionAttention('Превышен лимит тренировки стартового Хоэнна')
    finally:p.learning=None

def rival(w):
    p=w.player
    if p.var(0x4084)>=4:return
    train(w,8);p.nav.travel(CENTER);p.heal();p.nav.travel('Route103');p.go((10,3));p.tap('UP',frames=16);p.tap('A')
    for _ in range(200):
        if p.state()['in_battle']:break
        p.tap('A',wait=24)
    else:raise AcquisitionAttention('Не начался ожидаемый бой с соперником на Route 103')
    p.battle('fight',trainer=True);p.settle(button='A')
    if p.var(0x4084)!=4:raise AcquisitionAttention('Не подтверждена победа над соперником')

def dex(w):
    p=w.player
    if p.var(0x4084)>=5:return
    p.nav.travel('OldaleTown');known_story(p,lambda:p.go((10,19),allow_trigger=True))
    p.transition('DOWN','Route101')
    known_story(p,lambda:p.nav.travel('LittlerootTown_ProfessorBirchsLab'))
    p.settle(button='A')
    if not p.flag(0x801) or not p.ball_count():raise AcquisitionAttention('Не получены Pokédex и покеболы')

def companion(w):
    p=w.player
    if p.state()['map']['name']=='LittlerootTown_ProfessorBirchsLab':
        p.go((6,11));p.transition('DOWN','LittlerootTown')
    if not p.flag(0x860):
        known_story(p,lambda:p.go((11,9),allow_trigger=True));p.settle(button='A')
    if len(p.state()['party'])<2:p.hunt(route='Route101')
    p.nav.travel(CENTER);p.heal()

def run(w):
    w.player=Journey(w.game,w)
    if not w.uid:w.search()
    stages=[('Получаем стартового у Бирча',initial_battle),('Готовимся и побеждаем соперника',rival),('Получаем Pokédex и покеболы',dex),('Готовим второго Pokémon и Center',companion)]
    for number,(title,action) in enumerate(stages,1):
        if w.progress['milestone']>=number:continue
        w.update(status='preparing',stage=title);action(w);w.milestone(number)
    if w.config.train:
        w.update(status='training',stage='Прокачиваем до уровня '+str(w.config.target_level))
        train(w,w.config.target_level)
    p=w.player;p.nav.travel(CENTER);p.heal();p.save_game()
    s=p.state();mon=next(m for m in s['party'] if m['uid']==w.uid)
    if not p.flag(0x801) or len(s['party'])<2 or mon['species_id']!=w.config.species_id or w.config.shiny and not mon['shiny']:raise AcquisitionAttention('Не выполнены условия готовности стартового Хоэнна')
    checkpoint=p.checkpoint('ready-for-transfer',permanent=True)
    result=read_json(w.job/'result.json');result.update(pokemon=mon,transfer_ready=True,ready_checkpoint=str(checkpoint),ready_at=time.time());write_json(w.job/'result.json',result)
    w.update(status='ready',stage='Готов к переносу · Oldale Center',pokemon=mon,transfer_ready=True,ready_checkpoint=str(checkpoint));w.heartbeat()
