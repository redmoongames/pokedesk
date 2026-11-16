"""One real runtime/UI per process, private Data, owner-only instrumentation."""
from pathlib import Path
from copy import deepcopy
import argparse
import json
import queue
import shutil
import sys
import tempfile
import threading
import time
import traceback

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from regression.model import require,signature,atomic_json,sha,terminal_snapshot,user_revocation


def execute(args):
    project=args.project.resolve();spec=json.loads(args.spec.read_text());events=queue.SimpleQueue();records=[]
    result=dict(case=spec['id'],speed=args.speed,status='error',errors=[],fixture_sha256=sha(args.fixture))
    with tempfile.TemporaryDirectory(prefix='Pokemon check ') as directory:
        root=Path(directory);(root/'Data').mkdir()
        for name in ('native','vendor','assets','runtime','templates'):
            (root/name).symlink_to(project/name)
        for name in ('src','Bots'):
            shutil.copytree(project/name,root/name,ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copytree(project/'tools/regression',root/'tools/regression',ignore=shutil.ignore_patterns('__pycache__'))
        (root/'Data/FireRed.gba').symlink_to(project/'Data/FireRed.gba')
        shutil.copy2(args.fixture,root/'Data/FireRed.state')
        atomic_json(root/'Data/settings.json',dict(panel_on_start=False,sound_enabled=False,auto_focus_game=False,
            autosave_enabled=True,autosave_seconds=5,speed=args.speed,scale=2))
        atomic_json(root/'Data/check-case.json',spec)
        atomic_json(args.output,dict(status='running',case=spec['id'],private_root=str(root)))
        script=root/'Bots/check_case.py'
        script.write_text("def run(bot):\n import sys\n sys.path.insert(0,str(bot.project_dir/'tools'))\n from regression.scenarios import run as check\n check(bot)\n")
        sys.path.insert(0,str(root/'src'))
        from pokemon_red.gui import Monitor
        from pokemon_red.engine import Game,BUTTONS
        from pokemon_red.engine_runtime import EngineRuntime
        from pokemon_red.session_controller import SessionController
        from pokemon_red.telemetry import read_state,read_controls,symbols
        state=dict(stopping=False,begin=None,accepted=False,initial=None,manual=False,old=False,captures=[],native_A=0,owner_ids=set(),probe=None,repeat_inputs=0,repeats=False)
        heartbeat=[];last_video=[None]

        class CheckedController(SessionController):
            def __init__(self,*a,**kw):
                super().__init__(*a,**kw)
                state['initial']=deepcopy(self.session_state());sy=symbols(self.folder)
                def capture(name):
                    if not args.capture_dir or name in state['captures']:return
                    args.capture_dir.mkdir(parents=True,exist_ok=True)
                    (args.capture_dir/(name+'.state')).write_bytes(self.game.capture_save(metadata=False).state)
                    atomic_json(args.capture_dir/(name+'.json'),read_state(self.game));state['captures'].append(name)
                original=self.game.advance
                def advance(frames=1,keys=0):
                    if frames:
                        state['owner_ids'].add(threading.get_ident())
                        if keys&BUTTONS['A']:state['native_A']+=1
                        if state['repeats'] and keys:state['repeat_inputs']+=1
                        epoch=state.get('epoch')
                        if epoch and self.transport.applied_epoch>=epoch:
                            state['old']|=bool(keys&BUTTONS['B']);state['manual']|=bool(keys&BUTTONS['LEFT'])
                    returned=original(frames,keys)
                    if frames and args.capture_dir and 'arena-trap' in state['captures'] and 'battle-faint' not in state['captures']:
                        c=read_controls(self.game)
                        if c.get('player_fainted') and (c.get('yes_no_state')==1 or any(t['name']=='Task_HandleChooseMonInput' for t in c['tasks'])):
                            s=read_state(self.game)
                            if any(m['uid']=='ee83a314:25de551a' and m['hp']==0 for m in s['party']):capture('battle-faint')
                    return returned
                self.game.advance=advance
                sink=self.automation.event_sink
                def event(code,message,details):
                    value=sink(code,message,details)
                    if spec['kind'] in ('trap','faint') and code=='party_action_confirmed':
                        live=self.session_state()
                        details=dict(details,target_fainted=any(m['uid']=='ee83a314:25de551a' and m['hp']==0 for m in live['party']))
                    now=time.perf_counter()
                    if code=='check_start':state['begin']=now
                    if code=='check_repeats_start':state['repeats']=True
                    if code=='battle_recovery' and 'arena_trap' in details.get('reasons',[]):capture('arena-trap')
                    if code=='healing_started' and 'battle-faint' in state['captures']:capture('heal')
                    if code!='bot_input':events.put(dict(code=code,message=message,details=deepcopy(details),clock=now,frame=self.game.frame))
                    return value
                self.automation.event_sink=event
                observe=self.history.observe
                def observed(s,*a,**kw):
                    value=observe(s,*a,**kw)
                    if spec['kind']=='battle' and state['begin'] and not state['accepted'] and s.get('in_battle'):
                        controller=s['controls']['controllers'][0]
                        if controller not in ('HandleInputChooseAction','HandleInputChooseMove') and self.game.read16(sy['gChosenMove'])==64:
                            state['accepted']=True;events.put(dict(code='check_move_accepted',clock=time.perf_counter(),frame=self.game.frame,details=dict(move_id=64)))
                    return value
                self.history.observe=observed
                start=self.automation.start
                def started(path,**options):
                    start(path,**options)
                    if spec.get('learning_plan'):
                        self.automation.safety_profile='training'
                        self.install_move_plan(spec['learning_plan'])
                        self.automation.record_event('check_start','Approved learning starts before the first guarded frame',dict(case=spec['id']))
                self.automation.start=started

        class CheckedRuntime(EngineRuntime):
            def take_control(self,**kw):
                frames=traceback.extract_stack(limit=12);stack=traceback.format_list(frames)
                user=user_revocation(frames)
                events.put(dict(code='check_control_source',clock=time.perf_counter(),frame=self.latest.frame if self.latest else 0,details=dict(user_requested=user,stack=stack,arguments=kw)))
                return super().take_control(**kw)
            def _dispatch(self,c,method,arguments):
                if method=='check_final':return deepcopy(c.session_state())
                return super()._dispatch(c,method,arguments)

        def factory(*a,**kw):return CheckedRuntime(*a,controller_factory=CheckedController,**kw)
        import tkinter as tk
        if not args.visible:
            Base=tk.Toplevel
            class HiddenTop(Base):
                def __init__(self,*a,**kw):super().__init__(*a,**kw);self.withdraw()
                def deiconify(self):pass
            tk.Toplevel=HiddenTop
        window=tk.Tk();window.title(f"Проверка · {spec['id']} · {args.speed:g}×")
        if not args.visible:window.withdraw()
        monitor=Monitor(window,root,paused=True,runtime_factory=factory)
        window.report_callback_exception=lambda typ,error,tb:result['errors'].append(''.join(traceback.format_exception(typ,error,tb)))
        launched=[False];started_at=time.perf_counter()

        def drain():
            while True:
                try:records.append(events.get_nowait())
                except queue.Empty:break

        def stop():
            if state['stopping']:return
            state['stopping']=True;result['automation_before_takeover']=deepcopy(monitor.runtime.latest.status['automation'])
            requested=time.perf_counter();epoch=monitor.runtime.take_control(pause=True)
            def paused():
                if monitor.runtime.latest.epoch<epoch:window.after(1,paused);return
                result['finish_ack_ms']=(time.perf_counter()-requested)*1000
                future=monitor.runtime.submit('check_final')
                def ready():
                    if not future.done():window.after(1,ready);return
                    result['final']=future.result();last_video[0]=monitor.runtime.latest.video
                    monitor.close()
                ready()
            paused()

        def poll():
            drain()
            if monitor.runtime.ready.done() and monitor.runtime.ready.exception():
                result['errors'].append(str(monitor.runtime.ready.exception()));state['stopping']=True;window.destroy();return
            if time.perf_counter()-started_at>spec.get('timeout',60):
                result['errors'].append('case timeout');stop();return
            if not monitor.ready:window.after(5,poll);return
            if not launched[0]:
                launched[0]=True;monitor.show_panel('overview');window.after(200,lambda:monitor.start_bot(script))
            if spec['kind']=='takeover' and monitor.automation.running and monitor.automation.info().get('action') and not state['probe']:
                state['probe']=time.perf_counter();state['epoch']=monitor.runtime.take_control(pause=True)
                def ack():
                    if monitor.runtime.latest.epoch<state['epoch']:window.after(1,ack);return
                    result['takeover_ack_ms']=(time.perf_counter()-state['probe'])*1000
                    require(not monitor.runtime.latest.status['automation']['running'],'bot survived takeover')
                    monitor.runtime.submit('set_speed',args.speed);monitor.runtime.submit('manual','LEFT',True)
                    window.after(35,release)
                def release():
                    monitor.runtime.submit('manual','LEFT',False);stop()
                ack()
            if not state['stopping'] and any(e['code']=='script_started' for e in records) and terminal_snapshot(monitor.runtime.latest.status['automation'],script.name):
                if spec['kind']!='takeover':stop()
            if not state['stopping']:window.after(5,poll)

        def beat(expected):
            if state['begin'] and not state['stopping']:heartbeat.append(max(0,time.perf_counter()-expected))
            if not state['stopping']:window.after(10,beat,time.perf_counter()+.01)
        window.after(10,poll);window.after(10,beat,time.perf_counter()+.01);window.mainloop();drain()
        result.update(events=records,initial=state['initial'],captures=state['captures'],native_A_frames=state['native_A'],
            owner_threads=list(state['owner_ids']),ui_lateness=sorted(heartbeat),old_bot_input_after_ack=state['old'],manual_input_applied=state['manual'])
        try:
            require(not result['errors'],'UI/runtime errors: '+str(result['errors']))
            expected=spec.get('expected_status','finished');actual=result['automation_before_takeover']['status']
            require(actual==expected,f"expected {expected}, got {actual}: {result['automation_before_takeover']}")
            require(state['owner_ids']<= {monitor.runtime.thread.ident},'native core used outside owner')
            if spec['kind']=='takeover':
                require(state['manual'] and not state['old'],'manual input or stale bot input failed')
                require(result['takeover_ack_ms']<100,'takeover exceeded 100 ms')
            elif expected=='attention':
                require(any(e['code']=='move_choice_required' for e in records),'wrong attention reason')
                require(state['native_A']==0,'unapproved learning sent A')
                require(signature(result['final'])==signature(state['initial']),'unapproved learning changed party')
            else:
                begins=[e for e in records if e['code']=='check_start'];ends=[e for e in records if e['code']=='check_complete']
                require(len(begins)==len(ends)==1,'missing or repeated measurement markers')
                result['seconds']=ends[0]['clock']-begins[0]['clock'];result['frames']=ends[0]['frame']-begins[0]['frame']
                if spec['kind']=='battle':
                    mark=next(e for e in records if e['code']=='check_move_accepted');result['move_accept_seconds']=mark['clock']-begins[0]['clock']
                if spec['kind']=='heal':
                    require(sum(e['code']=='healing_started' for e in records)==1,'repeated healing')
                    require(sum(e['code']=='healing_completed' for e in records)==1,'healing never completed')
                    repeat=next(e for e in records if e['code']=='check_repeats_start')
                    require(not any(e['code'] in ('walk_segment_started','healing_started') and e['clock']>repeat['clock'] for e in records),'healthy repeat moved or healed')
                    require(state['repeat_inputs']==0,'healthy repeat sent native input')
                if spec['kind']=='walk':
                    legs=[e for e in records if e['code']=='walk_segment_finished']
                    require(len(legs)==20 and all(e['details']['reason']=='reached' and e['details']['tiles']==10 for e in legs),'walk workload differed from 200 tiles')
                if spec['kind']=='menu':
                    leads=[e['details']['pokemon_uid'] for e in records if e['code']=='party_lead']
                    require(leads==['ee83a314:67042a97','ee83a314:df868df5']*6,'wrong menu workload')
                if spec['kind']=='trap':require(any(e['code']=='battle_recovery' and 'arena_trap' in e['details'].get('reasons',[]) for e in records),'Arena Trap was not exercised')
                if spec['kind'] in ('trap','faint'):
                    selected=[e for e in records if e['code']=='party_action_confirmed']
                    require(bool(selected) and all(e['details'].get('target_fainted') and e['details'].get('pokemon_uid')!='ee83a314:25de551a' for e in selected),'forced replacement was not verified after faint')
                if spec['kind']=='poison_faint':require(any(e['code']=='field_recovery_complete' for e in records),'poison faint notification not handled')
                if spec['kind']=='learning':require(sum(e['code']=='move_plan_applied' for e in records)>=2,'approved curriculum not applied')
            with Game(root) as restored:
                require(not getattr(restored,'recovered_from',None),'close checkpoint required fallback')
                require(signature(read_state(restored))==signature(result['final']),'saved state did not round-trip')
            result['save_roundtrip']=True;result['status']='passed'
        except Exception as error:
            result['errors'].append(str(error));result['traceback']=traceback.format_exc()
            if any(e['code']=='check_control_source' and e['details']['user_requested'] for e in records):result['status']='interrupted'
        try:
            if (root/'Data/check-rpc.json').exists():result['rpc_seconds']=json.loads((root/'Data/check-rpc.json').read_text())
            if spec['kind']=='rpc':require(len(result.get('rpc_seconds',{}).get('state',[]))>=4000,'RPC sample batch was not published')
        except Exception as error:
            result['status']='error';result['errors'].append('RPC diagnostics: '+str(error));result['traceback']=traceback.format_exc()
        if result['status']!='passed' or args.keep_data:
            shutil.copytree(root/'Data',args.output.parent/(args.output.stem+'.Data'),symlinks=True)
            if last_video[0]:(args.output.parent/(args.output.stem+'.ppm')).write_bytes(last_video[0])
    atomic_json(args.output,result)
    return result['status']=='passed'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('project','spec','fixture','output'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--speed',type=float,default=12);parser.add_argument('--capture-dir',type=Path);parser.add_argument('--keep-data',action='store_true')
    parser.add_argument('--visible',action='store_true')
    args=parser.parse_args();args.output.parent.mkdir(parents=True,exist_ok=True)
    try:ok=execute(args)
    except BaseException as error:
        atomic_json(args.output,dict(status='error',error=str(error),traceback=traceback.format_exc()));ok=False
    raise SystemExit(0 if ok else 1)


if __name__=='__main__':main()
