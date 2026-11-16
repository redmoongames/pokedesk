"""Portable SQLite journal. Actual XP is measured from stable Pokémon identities."""
import json
import time
import uuid
import hashlib
from datetime import datetime,timezone
from .database import connect
from .planning import fingerprint
from .run_context import team_snapshot,comparison_key,context_complete

FPS=59.727500569606

def now():return datetime.now(timezone.utc).isoformat()
def dump(value):return json.dumps(value,ensure_ascii=False,separators=(',',':'))
def cycle_context(team,clinic,area):return hashlib.sha256(dump([team,clinic,area]).encode()).hexdigest()[:20] if clinic else team

class History:
    def __init__(self,root,*,async_writer=False,notify=None):
        self.db=connect(root)
        self.db.execute('CREATE TABLE IF NOT EXISTS battles (id INTEGER PRIMARY KEY,time TEXT,map TEXT,outcome TEXT,xp INTEGER,frames INTEGER,detail TEXT)')
        self.db.execute('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY,time TEXT,code TEXT,message TEXT,detail TEXT)')
        self.db.execute('CREATE INDEX IF NOT EXISTS events_code_idx ON events(code,id)')
        self.completed_write=None;self.completed_revision=0;self.stats_revision=0;self._comparisons_cache=None;self.root=root;self.active=None;self.revision=0;self.last=None;self.run=None;self.cycle=None;self.active_seconds=0;self.last_clock=time.monotonic();self.last_commit=self.last_clock;self.last_inventory=None;self.pending_events=[];self.speed=1
        # A prior power-off must not leave a run looking alive.
        self.db.execute("UPDATE training_runs SET status='interrupted',ended_at=? WHERE ended_at IS NULL",(now(),))
        self.db.execute("UPDATE training_cycles SET status='interrupted',ended_at=? WHERE ended_at IS NULL",(now(),));self.db.commit()
        self.timeline_id=uuid.uuid4().hex
        self.db.execute('INSERT INTO timelines VALUES(?,?,?,?,?,?)',(self.timeline_id,None,now(),'app_started',0,'{}'));self.db.commit()
        if async_writer:
            from .journal_store import JournalStore
            self.db=JournalStore(self.db,root,notify=notify,active_timeline=self.timeline_id)

    def ready_work(self):
        ready=getattr(self.db,'ready_work',None)
        return bool(ready and ready())

    def check_health(self):
        check=getattr(self.db,'check_health',None)
        if check:check()

    def observed_state(self):
        if not self.last:return dict(frame=0,party=[])
        return dict(frame=self.last['frame'],party=[dict(mon,uid=uid) for uid,mon in self.last['party'].items()])

    def change_timeline(self,reason,source=None):
        """Call before accepting a replacement Game, irrespective of frame order."""
        previous=self.timeline_id;state=self.observed_state()
        self.end_run('timeline_loaded',state)
        if self.active:
            record=self.active;gains=[]
            for mon in state['party']:
                before=record['before'].get(mon['uid'])
                if before:gains.append(dict(uid=mon['uid'],name=mon.get('nickname',before['name']),xp=max(0,mon['experience']-before['xp']),from_level=before['level'],level=mon.get('level',before['level'])))
            record.update(gains=gains,frames=max(0,state['frame']-record['start']),interrupted=True,reason=reason)
            self.db.execute('INSERT INTO battles(time,map,outcome,xp,frames,detail) VALUES(?,?,?,?,?,?)',(record['time'],record['map'],'Прерван: загрузка сохранения',sum(g['xp'] for g in gains),record['frames'],dump(record)))
        self.timeline_id=uuid.uuid4().hex;self.last=None;self.active=None;self.last_inventory=None
        if hasattr(self.db,'active_timeline'):self.db.active_timeline=self.timeline_id
        self.db.execute('INSERT INTO timelines VALUES(?,?,?,?,?,?)',(self.timeline_id,previous,now(),str(reason),0,dump(dict(source=source))))
        self.db.commit();self.event('timeline_loaded','Загружена другая ветка сохранения',dict(parent_id=previous,reason=reason,source=source));self.revision+=1

    def observe(self,state,controller='manual',paused=False,speed=None):
        clock=time.monotonic();self.active_seconds+=0 if paused else max(0,clock-self.last_clock);self.last_clock=clock
        if clock-self.last_commit>=1:self.flush()
        if not state.get('ready') or not state.get('telemetry_valid',True):return
        frame=state['frame'];party=state.get('party',[])
        if self.last and frame<self.last['frame']:
            self.change_timeline('frame_rewind')
        if speed is not None:self.speed=float(speed)
        if self.cycle and not paused:
            intervals=self.cycle['speed_intervals']
            if not intervals or intervals[-1]['speed']!=self.speed:intervals.append(dict(frame=frame,speed=self.speed))
        current=dict(frame=frame,map=(state.get('map') or {}).get('name'),position=state.get('position'),money=state.get('money'),party={m['uid']:{k:m.get(k) for k in ('nickname','species_id','level','experience','hp','max_hp','status','held_item')} for m in party})
        if self.cycle and clock-self.cycle.get('synced_at',0)>=1:self.sync_cycle(state)
        if self.last:
            if current['map']!=self.last['map']:self.event('location_changed','Локация: '+str(current['map']),dict(controller=controller,before=self.last['map'],after=current['map'],frame=frame))
            if current['money']!=self.last['money']:self.event('money_changed','Баланс изменился',dict(controller=controller,before=self.last['money'],after=current['money'],frame=frame))
            if set(current['party'])!=set(self.last['party']):self.event('party_changed','Изменился состав команды',dict(controller=controller,uids=list(current['party']),frame=frame))
            changes={u:dict(before=self.last['party'].get(u),after=m) for u,m in current['party'].items() if u in self.last['party'] and m!=self.last['party'][u]}
            if changes:self.event('pokemon_changed','Изменились XP, HP, статус или характеристики Pokémon',dict(controller=controller,changes=changes,frame=frame),durable=False)
            if current['position']!=self.last['position']:self.event('movement','Перемещение',dict(controller=controller,map=current['map'],position=current['position'],frame=frame),durable=False)
        self.last=current
        battle=state.get('battle')
        if battle and self.active is None:
            self.active=dict(time=now(),timeline_id=self.timeline_id,map=current['map'],start=frame,before={m['uid']:dict(name=m['nickname'],xp=m['experience'],level=m['level']) for m in party},enemies={},outcome=0,controller=controller,controllers=[controller],run_id=self.run['id'] if self.run else None,cycle=self.cycle['number'] if self.cycle else None)
            self.event('battle_started','Начался бой',dict(controller=controller,frame=frame,map=current['map']))
        if self.active is None:return
        record=self.active
        if record['controllers'][-1]!=controller:record['controllers'].append(controller);record['controller']=' → '.join(record['controllers'])
        if frame<record['start']:self.active=None;return
        if battle:
            record['outcome']=battle['outcome'] or record['outcome']
            for mon in battle['enemies']:
                if mon['species_id']:record['enemies'][str(mon['battler'])]=dict(species=mon['species'],species_id=mon['species_id'],level=mon['level'])
            return
        gains=[]
        for mon in party:
            before=record['before'].get(mon['uid'])
            if before:gains.append(dict(uid=mon['uid'],name=mon['nickname'],xp=max(0,mon['experience']-before['xp']),from_level=before['level'],level=mon['level']))
        record.update(gains=gains,frames=frame-record['start'])
        outcome={1:'Победа',2:'Поражение',3:'Ничья',4:'Отступление',5:'Телепортация',6:'Противник убежал',7:'Пойман',8:'Закончились Safari Balls',9:'Сдача',10:'Противник телепортировался'}.get(record['outcome'],'Завершён')
        self.db.execute('INSERT INTO battles(time,map,outcome,xp,frames,detail) VALUES(?,?,?,?,?,?)',(record['time'],record['map'],outcome,sum(g['xp'] for g in gains),record['frames'],dump(record)))
        self.db.commit();self.active=None;self.revision+=1
        if self.cycle:self.cycle['battles']+=1

    def inventory(self,inventory):
        if not inventory.get('ready'):return
        mons=inventory.get('party',[])+inventory.get('boxes',[])
        if any(not m.get('checksum_valid') for m in mons):return
        signature=tuple((m['uid'],m['location'],m.get('box'),m.get('box_slot'),m['level'],m.get('experience'),m.get('hp'),m.get('status'),m.get('held_item'),tuple((a['id'],a.get('current_pp')) for a in m['moves'])) for m in mons)
        if signature==self.last_inventory:return
        self.db.execute('UPDATE owned_pokemon SET present=0')
        self.db.executemany('INSERT OR REPLACE INTO owned_pokemon VALUES(?,?,?,?,?)',[(m['uid'],now(),m['location'],1,dump(m)) for m in mons]);self.db.commit();self.last_inventory=signature;self.revision+=1

    def training_event(self,code,details,state):
        if code=='training_run_start':
            if self.run:self.end_run('route_changed' if details.get('parent_run_id') else 'replaced',state)
            details=json.loads(dump(details))
            run=dict(details,id=details.get('run_id') or uuid.uuid4().hex,started_at=now(),status='preparing',timeline_id=self.timeline_id,start_frame=state['frame'],start_active=self.active_seconds,start_xp=next((m['experience'] for m in state.get('party',[]) if m['uid']==details['trainee']),None));self.run=run
            self.db.execute('INSERT INTO training_runs VALUES(?,?,?,?,?,?,?,?,?,?)',(run['id'],run['started_at'],None,run['route'],run['strategy'],run['trainee'],run['target'],'preparing',run.get('team_fingerprint'),dump(run)));self.db.commit()
        elif code=='preparation_complete' and self.run:
            self.run.update(status='running',prepared_at=now(),clinic=details.get('clinic'),area=details.get('area'));self.db.execute('UPDATE training_runs SET status=?,body=? WHERE id=?',('running',dump(self.run),self.run['id']));self.db.commit()
        elif code=='cycle_start' and self.run:
            if self.cycle:self.end_cycle('interrupted',state)
            team=state['party'];number=int(details['number']);self.cycle=dict(number=number,started_at=now(),clock=time.monotonic(),active=self.active_seconds,start_frame=state['frame'],before={m['uid']:m['experience'] for m in team},team_fingerprint=fingerprint(team),team=team_snapshot(team),battles=0,timeline_id=self.timeline_id,context=self.run.get('context'),speed_intervals=[dict(frame=state['frame'],speed=self.speed)])
            self.cycle.update(clinic=details.get('clinic'),area=details.get('area'),forecast=json.loads(dump(details.get('forecast'))),team_base_fingerprint=self.cycle['team_fingerprint']);self.cycle['team_fingerprint']=comparison_key(self.cycle['team_base_fingerprint'],self.cycle['context'],self.cycle['clinic'],self.cycle['area'],self.run['id'])
            row=self.db.execute('INSERT INTO training_cycles(run_id,number,started_at,status,start_frame,team_fingerprint,body) VALUES(?,?,?,?,?,?,?)',(self.run['id'],number,self.cycle['started_at'],'running',state['frame'],self.cycle['team_fingerprint'],dump(self.cycle)));self.cycle['id']=row.lastrowid;self.db.commit();self.stats_revision+=1
        elif code=='cycle_complete':self.end_cycle('completed',state)
        elif code=='return_to_clinic' and self.cycle:
            self.cycle.update(return_method=details.get('method'),return_reason=details.get('reason'));self.sync_cycle(state)
        elif code=='grind_area_selected' and self.cycle:
            self.cycle['area']=details.get('tiles');self.cycle['team_fingerprint']=comparison_key(self.cycle['team_base_fingerprint'],self.cycle['context'],self.cycle['clinic'],self.cycle['area'],self.run['id']);self.db.execute('UPDATE training_cycles SET team_fingerprint=? WHERE id=?',(self.cycle['team_fingerprint'],self.cycle['id']));self.sync_cycle(state)
        elif code in ('target_reached','move_choice_required','move_plan_mismatch','shiny_encounter','battle_lost','script_stopped','script_finished','script_attention','script_failed','script_error','training_blocked','training_timeout','party_changed','escape_failed','unexpected_battle','unexpected_dialog','unexpected_scene'):
            self.end_run(code,state)

    def end_cycle(self,status,state):
        if not self.cycle:return
        if not state.get('telemetry_valid',True) and self.last:
            state=dict(state,party=[dict(uid=uid,experience=mon['experience']) for uid,mon in self.last['party'].items()])
        self.sync_cycle(state,status)
        self.cycle=None;self.revision+=1

    def sync_cycle(self,state,status='running'):
        c=self.cycle;after={m['uid']:m['experience'] for m in state.get('party',[])};gains={u:max(0,after.get(u,xp)-xp) for u,xp in c['before'].items()};target=self.run['trainee'] if self.run else ''
        end=state.get('frame',c['start_frame']);duration=max(0,end-c['start_frame'])/FPS
        body=dict(c,gains=gains,reason=status)
        forecast=c.get('forecast')
        if status!='running' and forecast:
            actual_xp=gains.get(target,0);actual_rate=actual_xp*60/max(1,duration)
            body['evaluation']=dict(kind='complete' if status=='completed' else 'partial',reason=status,actual_game_seconds=duration,actual_active_seconds=max(0,self.active_seconds-c['active']),actual_target_xp=actual_xp,actual_battles=c['battles'],actual_xp_game_minute=actual_rate)
            if status=='completed':
                body['evaluation'].update(time_error_seconds=duration-forecast['game_seconds'],time_error_percent=100*(duration/max(1,forecast['game_seconds'])-1),xp_error=actual_xp-forecast['target_xp'],rate_error=actual_rate-forecast['xp_game_minute'])
            self.event('forecast_evaluated','Сравнение прогноза и результата цикла',dict(run_id=self.run['id'] if self.run else None,cycle=c['number'],forecast=forecast,evaluation=body['evaluation']))
        self.db.execute('UPDATE training_cycles SET ended_at=?,status=?,end_frame=?,game_seconds=?,wall_seconds=?,active_seconds=?,target_xp=?,team_xp=?,battles=?,body=? WHERE id=?',(None if status=='running' else now(),status,end,duration,time.monotonic()-c['clock'],max(0,self.active_seconds-c['active']),gains.get(target,0),sum(gains.values()),c['battles'],dump(body),c['id']));write=self.db.commit();c['synced_at']=time.monotonic();self.revision+=1;self.stats_revision+=1
        if status!='running':self.completed_revision+=1;self.completed_write=write

    def end_run(self,reason,state):
        self.end_cycle('partial:'+reason,state)
        if self.run:
            run=self.run;forecast=run.get('forecast')
            if forecast:
                elapsed=max(0,state['frame']-run.get('start_frame',state['frame']))/FPS
                mon=next((m for m in state.get('party',[]) if m['uid']==run['trainee']),None)
                start=run.get('start_xp') if run.get('start_xp') is not None else forecast.get('start_xp');run['session_evaluation']=dict(reason=reason,goal_reached=reason=='target_reached',game_seconds=elapsed,active_seconds=max(0,self.active_seconds-run.get('start_active',self.active_seconds)),target_xp=max(0,mon['experience']-start) if mon and start is not None else None,predicted_game_seconds=forecast.get('eta_game_seconds'))
                if reason=='target_reached' and forecast.get('eta_game_seconds'):run['session_evaluation']['time_error_percent']=100*(elapsed/forecast['eta_game_seconds']-1)
            self.db.execute('UPDATE training_runs SET ended_at=?,status=?,body=? WHERE id=?',(now(),reason,dump(run),run['id']));self.db.commit();self.run=None;self.revision+=1

    def query_barrier(self):
        """Publish pending journal data; waiting belongs to the analytics dispatcher."""
        self.check_health();self.flush()
        # check_health reports a writer fault only once to avoid recursive error
        # logging. Analytics must still fail on later requests instead of using
        # an older successful write future and silently reading stale disk data.
        error=getattr(self.db,'error',None)
        if error is not None:
            from concurrent.futures import Future
            failed=Future();failed.set_exception(error);return failed
        return getattr(self.db,'last_write',None)

    def forecast_results(self,target_uid,limit=8):
        from .history_queries import query
        return query(self.db,'forecast_results',(target_uid,limit))

    def cycles(self,limit=200):
        from .history_queries import query
        return query(self.db,'cycles',(limit,))

    def comparisons(self):
        if self._comparisons_cache and self._comparisons_cache[0]==self.completed_revision:return self._comparisons_cache[1]
        from .history_queries import query
        rows=query(self.db,'comparisons');self._comparisons_cache=(self.completed_revision,rows)
        return rows

    def export(self,path):
        from .history_queries import query
        from .persistence import atomic_bytes
        payload=query(self.db,'export')
        atomic_bytes(path,(json.dumps(payload,ensure_ascii=False,indent=2)+'\n').encode(),durable=True)

    def rows(self,limit=200):
        from .history_queries import query
        return query(self.db,'rows',(limit,))

    def event(self,code,message,details=None,durable=True):
        self.pending_events.append((now(),str(code),str(message),dump(dict(details or {},timeline_id=self.timeline_id))));self.revision+=1
        clock=time.monotonic()
        if durable or clock-self.last_commit>=1:self.flush()
    def flush(self):
        if self.pending_events:
            self.db.executemany('INSERT INTO events(time,code,message,detail) VALUES(?,?,?,?)',self.pending_events);self.db.commit();self.pending_events.clear()
        if self.last:
            self.db.execute('UPDATE timelines SET last_frame=? WHERE id=?',(self.last['frame'],self.timeline_id));self.db.commit()
        self.last_commit=time.monotonic()
    def events(self,limit=200):
        from .history_queries import query
        self.flush();return query(self.db,'events',(limit,))
    def close(self):
        self.flush()
        self.end_run('app_closed',dict(frame=self.last['frame'] if self.last else 0,party=[dict(uid=u,experience=m['experience']) for u,m in (self.last['party'] if self.last else {}).items()]))
        self.db.commit();self.db.close()
