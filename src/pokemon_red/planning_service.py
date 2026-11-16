"""Coalesced planning actor; the UI supplies small, versioned map snapshots.

Only plain JSON snapshots cross the boundary. Tk and the emulator remain on their
owner thread. Hidden/closed setup windows revoke pending work immediately.
"""

from .paths import session_paths
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor,Future
from copy import deepcopy
from pathlib import Path
import json,queue,subprocess,threading,sys

class PlanningService:
    def __init__(self,compute=None,map_provider=None):
        self.compute=compute;self.map_provider=map_provider
        self.pool=ThreadPoolExecutor(max_workers=1) if compute else None
        self.active=None;self.pending=None;self.desired=None;self.cache=OrderedDict();self.availability={};self.closed=False;self.process=None;self.responses=queue.SimpleQueue();self.worker_log=None;self.map_pending=None
    def request(self,key,inventory,config,root):
        if self.closed or key==self.desired:return
        self.desired=key
        if key in self.cache and self.cache[key][1] is not None:self.cache.pop(key)
        if key in self.cache:self.cache.move_to_end(key)
        # The production input contains no tile world. Coalesce before copying.
        self.pending=(key,inventory,dict(config),root) if key not in self.cache else None
        self._start()
    def _launch(self,root):
        python=session_paths(root).installation.python
        if not python.exists():python=Path(sys.executable)
        log_dir=Path(root)/'Data/logs';log_dir.mkdir(parents=True,exist_ok=True);self.worker_log=(log_dir/'planning.log').open('a')
        self.process=subprocess.Popen([str(python),'-I','-B','-u',str(Path(__file__).with_name('planning_worker.py'))],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.worker_log,text=True)
        def read_lines(process,responses):
            try:
                for line in process.stdout:responses.put((process,line))
            except (OSError,ValueError):pass
            finally:responses.put((process,None))
        threading.Thread(target=read_lines,args=(self.process,self.responses),daemon=True,name='pokemon-plan-reader').start()
    def _send(self,packet):
        process=self.process;responses=self.responses
        payload=json.dumps(packet,ensure_ascii=False)+'\n'
        def send():
            try:process.stdin.write(payload);process.stdin.flush()
            except (OSError,ValueError) as error:responses.put((process,json.dumps(dict(plan=None,error=str(error)))))
        threading.Thread(target=send,daemon=True,name='pokemon-plan-send').start()
    def _start(self):
        if self.closed or self.active or not self.pending:return
        key,inventory,config,root=self.pending;self.pending=None
        if self.compute:
            self.active=(key,self.pool.submit(self.compute,deepcopy(inventory),config,root));return
        try:
            if self.process is not None and self.process.poll() is not None:self._retire()
            if self.process is None:self._launch(root)
            self.active=(key,None);self._send(dict(inventory=inventory,config=config,root=str(root)))
        except Exception as error:self.active=None;self.cache[key]=(None,str(error))
    def poll(self):
        if self.map_pending:
            process,name,future=self.map_pending
            superseded=self.active is not None and self.active[0]!=self.desired
            if superseded:
                future.cancel();self.map_pending=None
                if process is self.process:self._send(dict(name=name,cancelled=True))
            elif not future.done():return self.cache.get(self.desired)
            else:
                self.map_pending=None
                if process is self.process:
                    try:self._send(dict(name=name,grid=future.result()))
                    except Exception as error:self._send(dict(name=name,error=str(error)))
        if self.active:
            key,future=self.active;result=None
            if future is not None and future.done():
                try:result=(future.result(),None)
                except Exception as error:result=(None,str(error));self.availability[key]=getattr(error,'excluded',[])
            elif future is None:
                try:
                    while True:
                        process,raw=self.responses.get_nowait()
                        if process is self.process:break
                    if raw is None:result=(None,'Расчёт команды прерван; выбери цель заново')
                    else:
                        value=json.loads(raw)
                        from .installation_versions import require_response
                        try:require_response(value)
                        except ValueError as error:
                            self._retire();value=dict(plan=None,error=str(error))
                        if value.get('type')=='cancelled':
                            self.active=None;self._start();return self.cache.get(self.desired)
                        elif value.get('type')=='map_request':
                            name=value['name']
                            try:
                                if key!=self.desired:self._send(dict(name=name,cancelled=True))
                                else:
                                    if self.map_provider is None:raise RuntimeError('Не задан источник карт')
                                    grid=self.map_provider(name,revision=value.get('revision'))
                                    if isinstance(grid,Future):self.map_pending=(self.process,name,grid)
                                    else:self._send(dict(name=name,grid=grid))
                            except Exception as error:self._send(dict(name=name,error=str(error)))
                        else:result=(value['plan'],value['error']);self.availability[key]=value.get('availability',[])
                except queue.Empty:pass
            if result is not None:
                self.active=None;self.cache[key]=result;self.cache.move_to_end(key)
                while len(self.cache)>8:
                    old,_=self.cache.popitem(last=False);self.availability.pop(old,None)
                self._start()
        return self.cache.get(self.desired)
    def _retire(self):
        process=self.process;log=self.worker_log;self.process=None;self.worker_log=None
        if not process:return
        if process.poll() is None:process.terminate()
        def reap():
            try:process.wait(timeout=2)
            except subprocess.TimeoutExpired:process.kill();process.wait()
            for pipe in (process.stdin,process.stdout):
                try:pipe.close()
                except (OSError,ValueError):pass
            if log:log.close()
        threading.Thread(target=reap,daemon=True,name='pokemon-plan-close').start()
    def suspend(self):
        if self.map_pending:self.map_pending[2].cancel();self.map_pending=None
        self.pending=None;self.desired=None;self.active=None;self._retire()
    def close(self):
        if self.closed:return
        self.closed=True;self.suspend()
        if self.pool:self.pool.shutdown(wait=False,cancel_futures=True)
