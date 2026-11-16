"""Owner scheduler audit on disposable Data: full cycles, RPC timing and F9.

Use --cycle --probe --visible for real game/menu/UI checks. --rpc-count 1000
is a separate latency control, not an XP/min benchmark. No live Data is written.
"""
from pathlib import Path
from collections import defaultdict,deque
import argparse,hashlib,json,queue,shutil,sqlite3,statistics,sys,tempfile,time,tkinter as tk,os,threading
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
    p.add_argument('--deep',action='store_true');p.add_argument('--rpc-count',type=int,default=0);p.add_argument('--probe',action='store_true');p.add_argument('--quiet-ui',action='store_true')
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
        events=queue.SimpleQueue();records=[];totals=defaultdict(lambda:dict(n=0,total_ms=0.));frame_counts=defaultdict(int);request_counts=defaultdict(int);probes={};cpu_start=None;takeover_on_finish={};timings=defaultdict(lambda:deque(maxlen=50000));errors=[];heartbeat=[];measuring=False;stopping=False;result=None;plan_at=None
        def measure(obj,names,prefix=''):
            for name in names:
                fn=getattr(obj,name)
                def wrapped(*a,_fn=fn,_name=prefix+name,**kw):
                    at=time.perf_counter()
                    try:return _fn(*a,**kw)
                    finally:
                        if measuring:
                            dt=(time.perf_counter()-at)*1000;timings[_name].append(dt);totals[_name]['n']+=1;totals[_name]['total_ms']+=dt
                setattr(obj,name,wrapped)
        def instrument(c):
            measure(c,['tick','session_state','save','check_training_decision','check_shiny_encounter','update_automatic_speed','refresh_state','capture_video','inventory_snapshot','pump_background','bot_snapshot','record_automation_event'],'owner.')
            measure(c.automation,['poll','_dispatch','next_mask','after_frame'],'automation.')
            measure(c.game,['capture_save','rgb'],'core.')
            original_advance=c.game.advance
            def count_advance(frames=1,keys=0):
                if measuring:frame_counts['frames']+=frames;frame_counts['advance_calls']+=1
                if probes.get('epoch') and frames:
                    if c.transport.applied_epoch>=probes['epoch'] and keys&2:probes['old_bot_B_after_ack']=True
                    if c.transport.applied_epoch>=probes['epoch'] and keys&32:probes['manual_left_applied']=True
                return original_advance(frames,keys)
            c.game.advance=count_advance
            next_mask=c.automation.next_mask
            def mask(manual=0):
                if measuring:
                    frame_counts['bot_frames']+=1
                    if c.automation.action is None and not (c.automation.field_runtime or c.automation.recovery_runtime or (c.automation.move_runtime and c.automation.move_runtime.owns_input)):frame_counts['bot_no_action_frames']+=1
                return next_mask(manual)
            c.automation.next_mask=mask
            dispatch=c.automation._dispatch
            def request(r):
                if measuring:request_counts[r.method]+=1
                return dispatch(r)
            c.automation._dispatch=request
            measure(c.game,['advance'],'core.')
            if args.deep:
                from pokemon_red import telemetry,models,mechanics,move_plan,field_recovery,engine_runtime,session_controller
                measure(c.game,['read8','read16','read32','read_bytes'],'ram.')
                measure(telemetry,['read_state','read_controls','read_decision','read_training_alert','read_walk_state','read_learning_control','read_party_mon'],'telemetry.')
                measure(models,['decode_mon'],'model.')
                measure(session_controller,['read_state','read_decision','read_training_alert','read_walk_state'],'session_telemetry.')
                measure(engine_runtime,['deepcopy'],'snapshot.')
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
            class AuditRuntime(EngineRuntime):
                def _dispatch(self,c,method,args):
                    if method=='audit_probe':return dict(frame=c.game.frame,keys=sorted(c.keys),running=c.automation.running,paused=c.paused,action=c.automation.info()['action'])
                    return super()._dispatch(c,method,args)
            def factory(*a,**kw):
                runtime=AuditRuntime(*a,controller_factory=InstrumentedSession,**kw)
                measure(runtime,['publish','_commands'],'runtime.');return runtime
        if not args.visible:
            Top=tk.Toplevel
            class Hidden(Top):
                def __init__(self,*a,**kw):super().__init__(*a,**kw);self.withdraw()
                def deiconify(self):pass
            tk.Toplevel=Hidden
        window=tk.Tk()
        if not args.visible:window.withdraw()
        m=Monitor(window,root,paused=True,**({'runtime_factory':factory} if factory else {}))
        if args.quiet_ui:m.show_battle_panel=lambda:None
        window.title(f'Аудит · {args.speed:g}× · копия');window.report_callback_exception=lambda _,e,t:errors.append(str(e))
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
                takeover_on_finish.update(was_running=m.automation.running,stage=m.automation.info().get('stage'),action=m.automation.info().get('action'));requested=time.perf_counter();epoch=m.runtime.take_control(pause=True)
                def collect():
                    if m.runtime.latest.epoch<epoch:window.after(2,collect);return
                    takeover_on_finish.update(ack_ms=(time.perf_counter()-requested)*1000,bot_stopped=not m.runtime.latest.status['automation']['running'])
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
            cpu=os.times();cpu_seconds=cpu.user+cpu.system-cpu_start
            result=dict(takeover_on_finish=takeover_on_finish,cpu_seconds=cpu_seconds,cpu_percent_one_core=cpu_seconds/elapsed*100,totals=dict(totals),frame_counts=dict(frame_counts),request_counts=dict(request_counts),rpc_stats=json.loads((root/'Data/audit-rpc.json').read_text()) if (root/'Data/audit-rpc.json').exists() else {},project=str(project),input_state_sha256=hashlib.sha256(args.state.read_bytes()).hexdigest(),seconds=elapsed,speed=args.speed,
                actor=bool(factory),plan_ready_seconds=plan_at,hidden_windows=not args.visible,frames=frame()-start_frame,speed_achieved=(frame()-start_frame)/elapsed/59.7275,
                timings={k:stats(v) for k,v in timings.items()},heartbeat_lateness=stats(heartbeat),errors=errors,automation=m.automation.info(),events=records,cycles=cycles,
                final=m.bot_snapshot(),performance=m.status.get('performance',{}) if factory else m.diagnostics.performance())
            if args.probe:takeover_probe()
            else:m.close()
        def takeover_probe():
            probe_script=root/'Bots/audit_takeover.py';probe_script.write_text("def run(bot):\n bot.safety_profile('training')\n while True:bot.press('B',3600)\n")
            m.start_bot(probe_script);deadline=time.perf_counter()+10
            def active():
                info=m.automation.info()
                if info['running'] and info.get('action'):
                    probes['requested_at']=time.perf_counter();probes['epoch']=m.runtime.take_control(pause=True);probes['submit_ms']=(time.perf_counter()-probes['requested_at'])*1000;ack();return
                if time.perf_counter()>deadline:probes['error']='Probe bot did not start';probes['status']=info;probes['notice']=m.notice;end_probe();return
                window.after(2,active)
            def ack():
                if m.runtime.latest.epoch<probes['epoch']:window.after(1,ack);return
                probes['ack_ms']=(time.perf_counter()-probes['requested_at'])*1000;probes['bot_stopped']=not m.runtime.latest.status['automation']['running'];probes['old_bot_B_after_ack']=False;probes['manual_left_applied']=False
                m.runtime.submit('set_speed',args.speed);m.runtime.submit('manual','LEFT',True);window.after(30,release)
            def release():
                m.runtime.submit('manual','LEFT',False);m.runtime.take_control(pause=True);window.after(30,end_probe)
            def end_probe():
                result['takeover']={k:v for k,v in probes.items() if k!='requested_at'};m.close()
            active()
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
            nonlocal measuring,started,start_frame,cpu_start
            started=time.perf_counter();start_frame=frame();cpu=os.times();cpu_start=cpu.user+cpu.system;measuring=True
            if args.grind or args.cycle:m.start_bot(bot)
            else:m.set_speed(args.speed)
            window.after(int(args.seconds*1000),finish);window.after(20,poll)
        bot=root/'Bots/train_xp.py'
        if args.cycle:
            bot=root/'Bots/benchmark_cycle.py'
            bot.write_text("from pokemon_red.grind import GrindTrainer\nimport json,time\nfrom collections import defaultdict\nclass Done(Exception):pass\ndef run(bot):\n stats=defaultdict(lambda:dict(n=0,total_ms=0.,max_ms=0.))\n call=bot._call\n def measured(method,**args):\n  at=time.perf_counter()\n  try:return call(method,**args)\n  finally:\n   dt=(time.perf_counter()-at)*1000;row=stats[method];row['n']+=1;row['total_ms']+=dt;row['max_ms']=max(row['max_ms'],dt)\n bot._call=measured\n t=GrindTrainer(bot,json.loads((bot.project_dir/'Data/training.json').read_text()))\n original=t.begin_cycle\n def begin():\n  if t.cycle_number>=1:raise Done()\n  return original()\n t.begin_cycle=begin\n try:t.run()\n except Done:bot.log('Benchmark: complete cycle')\n finally:(bot.project_dir/'Data/audit-rpc.json').write_text(json.dumps(stats))\n")
        if args.rpc_count:
            args.cycle=True;bot=root/'Bots/audit_rpc.py'
            bot.write_text("import json,time\ndef run(bot):\n bot.safety_profile('training')\n at=time.perf_counter()\n for _ in range("+str(args.rpc_count)+"):bot.state()\n (bot.project_dir/'Data/audit-rpc.json').write_text(json.dumps(dict(count="+str(args.rpc_count)+",wall_seconds=time.perf_counter()-at)))\n")
        def prepare():
            if factory and not m.ready:window.after(10,prepare);return
            if args.panel!='none':m.show_panel('overview' if args.panel=='team' else 'automation')
            window.after(600,begin)
        started=0.;start_frame=0;window.after(100,prepare);window.after(10,beat,time.perf_counter()+.01);window.mainloop()
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2))
        print(json.dumps({k:result[k] for k in ('actor','seconds','speed_achieved','heartbeat_lateness','errors','takeover') if k in result},ensure_ascii=False))
if __name__=='__main__':main()
