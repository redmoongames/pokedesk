"""Native GUI/actor benchmark on disposable Data. No input reaches the main game."""
from pathlib import Path
from collections import defaultdict,deque
import argparse,hashlib,json,queue,shutil,sqlite3,statistics,sys,tempfile,time,tkinter as tk
PROJECT=Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project',type=Path,default=PROJECT);p.add_argument('--state',type=Path,required=True)
    p.add_argument('--history',type=Path);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--seconds',type=float,default=40);p.add_argument('--speed',type=float,default=8)
    p.add_argument('--panel',choices=('none','team','automation'),default='automation')
    p.add_argument('--grind',action='store_true');p.add_argument('--cycle',action='store_true')
    p.add_argument('--training-config',type=Path);p.add_argument('--no-autosave',action='store_true')
    p.add_argument('--auto-speed',action='store_true');p.add_argument('--visible',action='store_true')
    args=p.parse_args();project=args.project.resolve()
    with tempfile.TemporaryDirectory(prefix='Pokemon benchmark ') as td:
        root=Path(td);(root/'Data').mkdir()
        for n in ('native','vendor','assets','runtime','templates'):
            source=project/n if (project/n).exists() else PROJECT/n
            if source.exists():(root/n).symlink_to(source)
        shutil.copytree(project/'src',root/'src',ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copytree(project/'Bots',root/'Bots')
        (root/'Data/FireRed.gba').symlink_to(project/'Data/FireRed.gba')
        shutil.copy2(args.state,root/'Data/FireRed.state')
        (root/'Data/settings.json').write_text(json.dumps(dict(panel_on_start=False,sound_enabled=False,auto_focus_game=False,
            autosave_enabled=not args.no_autosave,autosave_seconds=5,speed=args.speed,scale=2)))
        if args.history:
            a=sqlite3.connect(args.history.resolve().as_uri()+'?mode=ro',uri=True);b=sqlite3.connect(root/'Data/history.sqlite3');a.backup(b);a.close();b.close()
        sys.path.insert(0,str(root/'src'))
        from pokemon_red.gui import Monitor
        from pokemon_red.engine import Game
        from pokemon_red.telemetry import read_state
        if args.training_config and not (args.grind or args.cycle):(root/'Data/training.json').write_text(args.training_config.read_text())
        if args.grind or args.cycle:
            from pokemon_red.move_plan import compile_plan
            from pokemon_red.models import read_inventory
            with Game(root) as g:
                inv=read_inventory(g);party=inv['party']
                cfg=json.loads(args.training_config.read_text()) if args.training_config else dict(auto_team=True,route='Auto',strategy='adaptive',trainee=party[0]['uid'],target=min(100,party[0]['level']+3),heal_percent=40,final_moves=[m['id'] for m in party[0]['moves']],evolution_mode='natural')
                target=next(m for m in inv['party']+inv['boxes'] if m['uid']==cfg['trainee'])
                cfg['auto_speed']=args.auto_speed;cfg['approved_plan_id']=compile_plan(target,cfg['target'],cfg['final_moves'],root,cfg.get('evolution_mode','natural'))['id']
            (root/'Data/training.json').write_text(json.dumps(cfg))
        events=queue.SimpleQueue();records=[];timings=defaultdict(lambda:deque(maxlen=50000));errors=[];heartbeat=[];measuring=False;stopping=False;result=None;plan_at=None
        def measure(obj,names,prefix=''):
            for name in names:
                fn=getattr(obj,name)
                def wrapped(*a,_fn=fn,_name=prefix+name,**kw):
                    at=time.perf_counter()
                    try:return _fn(*a,**kw)
                    finally:
                        if measuring:timings[_name].append((time.perf_counter()-at)*1000)
                setattr(obj,name,wrapped)
        def instrument(c):
            measure(c,['tick','session_state','save','check_training_decision','check_shiny_encounter'],'owner.')
            measure(c.game,['advance'],'core.')
            old=c.automation.event_sink
            def event(code,message,detail):
                ack=old(code,message,detail)
                if code!='bot_input':events.put(dict(code=code,message=message,details=detail,frame=c.game.frame,clock=time.perf_counter()))
                return ack
            c.automation.event_sink=event
        factory=None
        if (root/'src/pokemon_red/engine_runtime.py').exists():
            from pokemon_red.engine_runtime import EngineRuntime
            from pokemon_red.session_controller import SessionController
            class InstrumentedSession(SessionController):
                def __init__(self,*a,**kw):super().__init__(*a,**kw);instrument(self)
            factory=lambda *a,**kw:EngineRuntime(*a,controller_factory=InstrumentedSession,**kw)
        if not args.visible:
            Top=tk.Toplevel
            class Hidden(Top):
                def __init__(self,*a,**kw):super().__init__(*a,**kw);self.withdraw()
                def deiconify(self):pass
            tk.Toplevel=Hidden
        window=tk.Tk()
        if not args.visible:window.withdraw()
        m=Monitor(window,root,paused=True,**({'runtime_factory':factory} if factory else {}));m.show_battle_panel=lambda:None
        window.title('FireRed · проверочная копия');window.report_callback_exception=lambda _,e,t:errors.append(str(e))
        if not factory:instrument(m)
        measure(m,['tick','render','refresh_state','update_panel'],'ui.')
        def frame():return m.frame if factory else m.game.frame
        def drain():
            while True:
                try:records.append(events.get_nowait())
                except queue.Empty:return
        def stats(values):
            ordered=sorted(values);n=len(ordered)
            return dict(n=n,p50_ms=statistics.median(ordered),p95_ms=ordered[min(n-1,int(.95*n))],p99_ms=ordered[min(n-1,int(.99*n))],max_ms=ordered[-1]) if n else None
        def finish():
            nonlocal stopping,measuring
            if stopping:return
            stopping=True;measuring=False
            if factory:
                epoch=m.runtime.take_control(pause=True)
                def collect():
                    if m.runtime.latest.epoch<epoch:window.after(2,collect);return
                    future=m.runtime.submit('history_read','cycles',(200,))
                    def ready():
                        if not future.done():window.after(2,ready);return
                        finalize(future.result())
                    window.after(2,ready)
                collect()
            else:m.take_control(focus=False);m.pause(save=False);finalize(m.history.cycles())
        def finalize(cycles):
            nonlocal result
            drain();elapsed=time.perf_counter()-started
            result=dict(project=str(project),input_state_sha256=hashlib.sha256(args.state.read_bytes()).hexdigest(),seconds=elapsed,speed=args.speed,
                actor=bool(factory),plan_ready_seconds=plan_at,hidden_windows=not args.visible,frames=frame()-start_frame,speed_achieved=(frame()-start_frame)/elapsed/59.7275,
                timings={k:stats(v) for k,v in timings.items()},heartbeat_lateness=stats(heartbeat),errors=errors,automation=m.automation.info(),events=records,cycles=cycles,
                final=m.bot_snapshot(),performance=m.status.get('performance',{}) if factory else m.diagnostics.performance())
            m.close()
        def beat(expected):
            if measuring:heartbeat.append(max(0,(time.perf_counter()-expected)*1000))
            if not stopping:window.after(10,beat,time.perf_counter()+.01)
        def poll():
            nonlocal plan_at
            drain()
            tools=getattr(getattr(m,'panel',None),'automation_windows',None)
            view=tools.tools.get('training',{}).get('view') if tools else None
            if view and view.plan and plan_at is None:plan_at=time.perf_counter()-started
            if not stopping and args.cycle and any(r['code']=='script_started' for r in records) and not m.automation.running and m.automation.info().get('script')==bot.name and m.automation.info().get('status') in ('finished','attention','error','stopped'):finish()
            if not stopping:window.after(20,poll)
        def begin():
            nonlocal measuring,started,start_frame
            started=time.perf_counter();start_frame=frame();measuring=True
            if args.grind or args.cycle:m.start_bot(bot)
            else:m.set_speed(args.speed)
            window.after(int(args.seconds*1000),finish);window.after(20,poll)
        bot=root/'Bots/train_xp.py'
        if args.cycle:
            bot=root/'Bots/benchmark_cycle.py'
            bot.write_text("from pokemon_red.grind import GrindTrainer\nimport json\nclass Done(Exception):pass\ndef run(bot):\n t=GrindTrainer(bot,json.loads((bot.project_dir/'Data/training.json').read_text()))\n original=t.begin_cycle\n def begin():\n  if t.cycle_number>=1:raise Done()\n  return original()\n t.begin_cycle=begin\n try:t.run()\n except Done:bot.log('Benchmark: complete cycle')\n")
        def prepare():
            if factory and not m.ready:window.after(10,prepare);return
            if args.panel!='none':m.show_panel('overview' if args.panel=='team' else 'automation')
            window.after(600,begin)
        started=0.;start_frame=0;window.after(100,prepare);window.after(10,beat,time.perf_counter()+.01);window.mainloop()
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2))
        print(json.dumps({k:result[k] for k in ('actor','seconds','speed_achieved','heartbeat_lateness','errors')},ensure_ascii=False))
if __name__=='__main__':main()
