"""Cancellable one-shot travel planning; only immutable checkpoint bytes leave Tk."""
from concurrent.futures import ThreadPoolExecutor
from .paths import session_paths, bind_installation
from pathlib import Path
import json,subprocess,tempfile,threading

class TravelService:
    worker='travel_worker.py'
    def arguments(self,allow):return ['1' if allow else '0']
    def __init__(self):self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='travel-preview');self.future=None;self.process=None;self.serial=0;self.closed=False;self.lock=threading.Lock()
    def request(self,root,state_bytes,allow):
        self.serial+=1;serial=self.serial
        with self.lock:
            if self.process and self.process.poll() is None:self.process.terminate()
        if self.future:self.future.cancel()
        self.future=self.pool.submit(self.compute,Path(root),state_bytes,allow,serial)
    def compute(self,root,state_bytes,allow,serial):
        with tempfile.TemporaryDirectory(prefix='Pokemon travel preview ') as name:
            folder=Path(name);(folder/'Data').mkdir();(folder/'Data/FireRed.state').write_bytes(state_bytes)
            bind_installation(folder,root)
            (folder/'Data/FireRed.gba').symlink_to(root/'Data/FireRed.gba')
            if (root/'Data/game.json').exists():
                (folder/'Data/game.json').write_bytes((root/'Data/game.json').read_bytes())
            with self.lock:
                if serial!=self.serial or self.closed:return None
                self.process=subprocess.Popen([str(session_paths(root).installation.python),'-I','-B',str(Path(__file__).with_name(self.worker)),str(folder),*self.arguments(allow)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                process=self.process
            try:out,error=process.communicate(timeout=90)
            except subprocess.TimeoutExpired:process.kill();process.communicate();raise RuntimeError('Расчёт пути превысил 90 секунд. Обновите список.')
            if serial!=self.serial or self.closed:return None
            if process.returncode:raise RuntimeError((error.strip().splitlines() or ['Расчёт пути прерван'])[-1])
            from .installation_versions import unwrap_response
            return unwrap_response(json.loads(out))
    def poll(self):
        if self.future and self.future.done():
            future=self.future;self.future=None
            try:return future.result(),None
            except Exception as error:return None,str(error)
        return None
    def close(self):
        self.closed=True;self.serial+=1
        with self.lock:
            if self.process and self.process.poll() is None:self.process.terminate()
        if self.future:self.future.cancel()
        self.pool.shutdown(wait=False,cancel_futures=True)
