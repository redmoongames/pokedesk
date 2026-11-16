"""Background owner of one acquisition core; all game changes use buttons."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import fcntl
import hashlib
import json
import os
import signal
import sqlite3
import time
import traceback
from pokemon_red.acquisition import AcquisitionConfig, read_json, write_json, starters_for
from pokemon_red.acquisition_play import Player, AcquisitionAttention, JobPaused
from pokemon_red.engine import Game, BUTTONS
from pokemon_red.persistence import atomic_bytes
from pokemon_red.telemetry import read_state, read_map, symbols

class Worker:
    def __init__(self,job):
        try:os.nice(10)  # Let foreground simulation/input win under CPU pressure.
        except OSError:pass
        self.job=Path(job).resolve();self.spec=read_json(self.job/'job.json');self.config=AcquisitionConfig.parse(self.spec['config'])
        project=Path(self.spec['project']);project=(project if project.is_absolute() else self.job/project).resolve()
        expected=project/'Sessions/acquisition'/self.job.name
        if self.job!=expected:raise ValueError('Задание должно находиться в отдельной папке Sessions/acquisition')
        self.status=read_json(self.job/'status.json',{});self.progress=read_json(self.job/'progress.json',dict(milestone=0,prepared=False));self.game=None;self.player=None
        self.next_heartbeat=0;self.pause_requested=False;self.cancel_requested=False;self.started=time.monotonic();self.last_ui=0
        self.db=sqlite3.connect(self.job/'attempts.sqlite3')
        self.db.execute('CREATE TABLE IF NOT EXISTS attempts (rng INTEGER PRIMARY KEY, uid TEXT, shiny INTEGER, frame INTEGER)');self.db.commit()
        self.seen={r[0] for r in self.db.execute('SELECT uid FROM attempts')}
        self.attempts=self.db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0]
        self.uid=(read_json(self.job/'result.json',{}) or {}).get('uid');self.recovered_found=False
        found=self.job/'checkpoints/found'
        if not self.uid and (found/'manifest.json').is_file():
            manifest=read_json(found/'manifest.json',{})
            if not manifest or any(Path(n).name!=n or hashlib.sha256((found/n).read_bytes()).hexdigest()!=digest for n,digest in manifest.items()):
                raise ValueError('Повреждён checkpoint найденного Pokémon')
            meta=read_json(found/'metadata.json',{})
            mon=next((m for m in meta.get('state',{}).get('party',[]) if m.get('species_id')==self.config.species_id and m.get('checksum_valid') and (not self.config.shiny or m.get('shiny'))),None)
            if mon:
                self.uid=mon['uid'];self.recovered_found=True;self.progress['milestone']=0
                write_json(self.job/'result.json',dict(uid=self.uid,found=mon,found_at=meta['created_at'],attempts=self.attempts,checkpoint='checkpoints/found',transfer_ready=False))

    def update(self,**values):
        self.status.update(values,pid=os.getpid(),updated_at=time.time(),attempts=self.attempts,unique_candidates=len(self.seen))
        write_json(self.job/'status.json',self.status)

    def event(self,code,details,*extra):
        if extra:details=dict(extra[-1],message=details)
        with (self.job/'events.jsonl').open('a') as f:
            f.write(json.dumps(dict(time=time.time(),frame=self.game.frame if self.game else None,code=code,details=details),ensure_ascii=False)+'\n')

    def heartbeat(self):
        now=time.monotonic()
        if now<self.next_heartbeat:return
        self.next_heartbeat=now+.25
        command=read_json(self.job/'command.json',{}).get('command')
        if command in ('pause','cancel'):self.pause_requested=True;self.cancel_requested=command=='cancel'
        if now-self.last_ui>=.75 and self.game:
            self.last_ui=now;s=read_state(self.game)
            atomic_bytes(self.job/'screen.ppm',b'P6\n240 160\n255\n'+self.game.rgb())
            self.status.update(frame=self.game.frame,map=(s.get('map') or {}).get('name'),level=next((m['level'] for m in s.get('party',[]) if m['uid']==self.uid),None),attempts=self.attempts,unique_candidates=len(self.seen),updated_at=time.time(),pid=os.getpid(),pause_pending=self.pause_requested)
            atomic_bytes(self.job/'status.json',(json.dumps(self.status,ensure_ascii=False,indent=2)+'\n').encode())

    def safe_point(self):
        self.heartbeat()
        if self.pause_requested:raise JobPaused()

    def record_encounter(self,enemy):
        if not enemy:return
        identity=enemy['uid']
        if identity in self.seen:return
        self.seen.add(identity);self.attempts+=1
        self.db.execute('INSERT OR IGNORE INTO attempts VALUES (?,?,?,?)',(self.attempts,identity,int(enemy['shiny']),self.game.frame));self.db.commit()
        self.update(status='searching',stage='Ищем '+('Shiny · ' if self.config.shiny else '')+enemy['species'] if enemy['species_id']==self.config.species_id else 'Поиск · встречено '+str(self.attempts))

    def milestone(self,number):
        self.player.persist();self.player.checkpoint('milestone-'+str(number));self.progress['milestone']=number;write_json(self.job/'progress.json',self.progress);self.safe_point()

    def search(self):
        p=self.player;g=self.game
        STARTERS=starters_for(g.root)
        self.update(status='searching',stage='Выбираем '+STARTERS[self.config.species_id])
        if not self.progress.get('prepared'):
            from pokemon_red.game_layout import hoenn
            if hoenn(g):
                from pokemon_red.hoenn_acquisition import prepare_choice
                prepare_choice(self)
            else:
                x={1:8,4:10,7:9}[self.config.species_id];p.go((x,5));p.tap('UP');p.tap('A',wait=120)
                for _ in range(30):
                    s=p.state()
                    if 'Task_YesNoMenu_HandleInput' in p.tasks(s):break
                    p.tap('A',wait=24)
                else:raise AcquisitionAttention('Не открылось подтверждение стартового')
                if s['controls']['menu_cursor']!=0:p.tap('UP')
                p.tap('A',wait=240)
                if p.state()['party']:raise AcquisitionAttention('Стартовый создан раньше ожидаемой точки RNG')
                if 'energetic' not in p.text().lower():raise AcquisitionAttention('Не подтверждена точка перед генерацией Pokémon: '+p.text())
            p.persist();self.progress['prepared']=True;write_json(self.job/'progress.json',self.progress)
        if not self.progress.get('search_offset_applied'):
            # Ordinary waiting gives independent new sessions different first
            # candidates without editing the RNG or Pokémon data.
            p.advance(1+int(self.job.name[:4],16)%4096);p.persist()
            self.progress['search_offset_applied']=True;write_json(self.job/'progress.json',self.progress)
        frontier=g.capture_save(metadata=False).state;last_disk=time.monotonic()
        self.update(status='searching',stage='Ищем Shiny · '+STARTERS[self.config.species_id] if self.config.shiny else 'Получаем '+STARTERS[self.config.species_id])
        for _ in range(10_000_000):
            g.restore_checkpoint(frontier);p.advance(17)
            frontier=g.capture_save(metadata=False).state
            rng=g.read32(symbols(g.root)['gRngValue'])
            if self.db.execute('SELECT 1 FROM attempts WHERE rng=?',(rng,)).fetchone():continue
            p.tap('A',frames=1,wait=3)
            for frame in range(180):
                s=p.state();mon=s['party'][0] if s['party'] else None
                if mon and mon.get('checksum_valid') and mon['species_id']==self.config.species_id:break
                if frame%12==11:p.tap('A',frames=2,wait=1)
                else:p.advance(1)
            else:raise AcquisitionAttention('Игра не выдала выбранного стартового')
            self.db.execute('INSERT INTO attempts VALUES (?,?,?,?)',(rng,mon['uid'],int(mon['shiny']),g.frame));self.db.commit();self.attempts+=1;self.seen.add(mon['uid'])
            if not self.config.shiny or mon['shiny']:
                self.uid=mon['uid']
                # This checkpoint precedes any dismissal, rival fight or training.
                p.checkpoint('found',permanent=True);p.persist()
                write_json(self.job/'result.json',dict(uid=mon['uid'],found=mon,found_at=time.time(),attempts=self.attempts,checkpoint='checkpoints/found',transfer_ready=False))
                self.event('target_found',dict(uid=mon['uid'],shiny=mon['shiny'],attempt=self.attempts));self.update(status='obtained',stage='Pokémon найден и сохранён',pokemon=mon)
                return
            g.restore_checkpoint(frontier)
            if time.monotonic()-last_disk>5:
                p.persist();last_disk=time.monotonic()
            self.safe_point()
        raise AcquisitionAttention('Достигнут предел поиска; продолжи сохранённое задание')

    def finish_gift(self):
        p=self.player
        for _ in range(180):
            s=p.state()
            if p.var(0x4055)>=3 and not s['controls']['field_locked']:
                p.advance(60)
                if not p.state()['controls']['field_locked']:break
            p.tap('B',wait=24)
        else:raise AcquisitionAttention('Не завершился диалог получения стартового')
        p.save_game();p.checkpoint('obtained',permanent=True)

    def door(self,destination,enter=True):
        p=self.player;grid=read_map(self.game)
        candidates=[e for e in grid['warps'] if e['destination']==destination and 0x60<=grid['tiles'][e['y']][e['x']][1]<=0x71]
        if not candidates:raise AcquisitionAttention('Не найдена дверь в '+destination)
        e=candidates[0];p.go((e['x'],e['y']+(1 if enter else -1)))
        return p.transition('UP' if enter else 'DOWN',destination)

    def town(self,destination,encounters='escape'):
        p=self.player
        for _ in range(6):
            name=p.state()['map']['name']
            if name==destination:return
            if name.endswith('_ProfessorOaksLab'):self.door('PalletTown',False);continue
            if name.endswith('_Mart'):self.door('ViridianCity',False);continue
            if name.endswith('_PokemonCenter_1F'):self.door('ViridianCity',False);continue
            if name=='PalletTown':p.go((12,0));p.transition('UP','Route1');continue
            if name=='ViridianCity':p.go((24,39));p.transition('DOWN','Route1',encounters=encounters);continue
            if name=='Route1':
                if destination=='ViridianCity':p.go((12,0),encounters=encounters);p.transition('UP','ViridianCity',encounters=encounters)
                else:
                    height=read_map(self.game)['height'];p.go((12,height-1),encounters=encounters);p.transition('DOWN','PalletTown',encounters=encounters)
                continue
            raise AcquisitionAttention('Неизвестная карта начального маршрута: '+name)
        raise AcquisitionAttention('Не завершился переход между городами')

    def rival(self):
        p=self.player
        if p.var(0x4055)>=4:return
        p.go((6,7));p.tap('DOWN',frames=16,wait=60)
        for _ in range(150):
            if p.state()['in_battle']:break
            p.tap('A',wait=24)
        else:raise AcquisitionAttention('Не начался ожидаемый бой с GARY')
        p.battle('fight',trainer=True);p.settle(button='A')
        if p.var(0x4055)!=4:raise AcquisitionAttention('Сцена GARY не подтвердила завершение')

    def parcel(self):
        self.town('ViridianCity');self.door('ViridianCity_Mart')
        self.player.settle(button='A')

    def dex(self):
        p=self.player;self.town('PalletTown');self.door('PalletTown_ProfessorOaksLab');p.go((6,4));p.tap('UP');p.tap('A',wait=60)
        for _ in range(500):
            s=p.state()
            if p.flag(0x829) and not s['controls']['field_locked']:
                p.advance(60)
                if not p.state()['controls']['field_locked']:return
            p.tap('A',wait=24)
        raise AcquisitionAttention('Не получен Pokédex')

    def companion(self):
        p=self.player
        self.town('ViridianCity',encounters='catch')
        if len(p.state()['party'])<2:
            p.go((24,39));p.transition('DOWN','Route1')
            grid=read_map(self.game)
            from pokemon_red.navigation import safe_grass_pair
            s=p.state();pair=safe_grass_pair(grid,(s['position']['x'],s['position']['y']))['pair']
            for _ in range(100):
                if len(p.state()['party'])>=2:break
                p.go(pair[_%2],encounters='catch')
            else:raise AcquisitionAttention('Не найден второй Pokémon для обмена')
            self.town('ViridianCity')
        self.door('ViridianCity_PokemonCenter_1F');p.heal()

    def train(self):
        p=self.player;target=self.config.target_level
        from pokemon_red.learning import LearningRuntime
        from pokemon_red.move_plan import default_moves,compile_plan
        mon=next(m for m in p.state()['party'] if m['uid']==self.uid)
        if mon['level']>=target:return
        plan=compile_plan(mon,target,default_moves(mon,target,self.game.root,mode='stay'),self.game.root,mode='stay')
        write_json(self.job/'training-plan.json',plan)
        p.learning=LearningRuntime(plan,event=self.event,checkpoint=lambda name:p.checkpoint('learning-'+__import__('uuid').uuid4().hex),suspend=lambda:None)
        for _ in range(100000):
            s=p.state();mon=next(m for m in s['party'] if m['uid']==self.uid)
            if mon['level']>=target:break
            if s['map']['name']=='ViridianCity_PokemonCenter_1F':
                p.heal();self.milestone(5);self.town('ViridianCity');p.go((24,39));p.transition('DOWN','Route1')
            from pokemon_red.navigation import safe_grass_pair
            s=p.state();pair=safe_grass_pair(read_map(self.game),(s['position']['x'],s['position']['y']))['pair']
            for turn in range(3000):
                s=p.state();mon=next(m for m in s['party'] if m['uid']==self.uid)
                if mon['level']>=target or mon['hp']*100<mon['max_hp']*65 or mon.get('status_code') or not any(a.get('power') and a['current_pp'] for a in mon['moves']):break
                p.go(pair[turn%2],encounters='fight')
            self.town('ViridianCity');self.door('ViridianCity_PokemonCenter_1F');p.heal();p.persist();self.safe_point()
        else:raise AcquisitionAttention('Превышен лимит тренировки')
        p.learning=None

    def run(self):
        lock=(self.job/'Data/.session.lock').open('a')
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return 2
        signal.signal(signal.SIGTERM,lambda *_:setattr(self,'pause_requested',True))
        signal.signal(signal.SIGINT,lambda *_:setattr(self,'pause_requested',True))
        try:
            game=Game(self.job)
            self.game=game;self.player=Player(game,self)
            if (self.recovered_found or self.status.get('resume_from',self.status.get('status')) in ('attention','error')) and self.uid:
                checkpoint=self.job/'checkpoints'/('milestone-'+str(self.progress['milestone']))/'FireRed.state'
                if not checkpoint.is_file():
                    checkpoint=self.job/'checkpoints/found/FireRed.state'
                    self.progress['milestone']=0
                if checkpoint.is_file():
                    game.load_state(checkpoint);self.player.persist()
                    write_json(self.job/'progress.json',self.progress)
                    self.event('recovered_last_safe_stage',dict(checkpoint=str(checkpoint)))
            self.update(status='preparing',stage='Загружаем отдельную сессию')
            if self.config.source=='wild':
                from pokemon_red.wild_acquisition import run_wild
                run_wild(self);return 0
            from pokemon_red.game_layout import hoenn
            if hoenn(game):
                from pokemon_red.hoenn_acquisition import run
                run(self);return 0
            if not self.uid:self.search()
            stages=[('Завершаем получение Pokémon',self.finish_gift),('Проходим первый бой с GARY',self.rival),('Получаем посылку Оука',self.parcel),('Получаем Pokédex и покеболы',self.dex),('Готовим второго Pokémon и Center',self.companion)]
            for number,(title,operation) in enumerate(stages,1):
                if self.progress['milestone']>=number:continue
                self.update(status='preparing',stage=title);operation();self.milestone(number)
            if self.config.train:
                self.update(status='training',stage='Прокачиваем до уровня '+str(self.config.target_level));self.train();self.milestone(6)
            if self.player.state()['map']['name']!='ViridianCity_PokemonCenter_1F':
                self.town('ViridianCity');self.door('ViridianCity_PokemonCenter_1F')
            self.player.heal();self.player.save_game()
            s=self.player.state();mon=next(m for m in s['party'] if m['uid']==self.uid)
            if not self.player.flag(0x829) or len(s['party'])<2 or mon['species_id']!=self.config.species_id or self.config.shiny and not mon['shiny']:
                raise AcquisitionAttention('Не выполнены условия готовности к переносу')
            folder=self.player.checkpoint('ready-for-transfer',permanent=True)
            result=read_json(self.job/'result.json');result.update(pokemon=mon,transfer_ready=True,ready_checkpoint=str(folder),ready_at=time.time());write_json(self.job/'result.json',result)
            self.update(status='ready',stage='Готов к переносу · Viridian Center',pokemon=mon,transfer_ready=True,ready_checkpoint=str(folder))
            self.heartbeat()
        except JobPaused:
            self.player.persist();self.update(status='cancelled' if self.cancel_requested else 'paused',stage='Задание отменено · сохранения оставлены' if self.cancel_requested else 'На паузе · прогресс сохранён',pause_pending=False)
        except Exception as error:
            traceback.print_exc()
            if self.player:
                self.player.persist();self.player.checkpoint('attention-'+str(time.time_ns()))
            self.update(status='attention',stage=str(error),error_type=type(error).__name__)
        finally:
            if self.game:self.game.close()
            self.db.close();lock.close()
        return 0

if __name__=='__main__':
    from pokemon_red.installation_versions import validate_worker
    validate_worker(Path(sys.argv[1]))
    raise SystemExit(Worker(Path(sys.argv[1])).run())
