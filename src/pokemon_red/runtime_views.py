"""UI read models. Methods return cached data or asynchronous command futures."""

from .paths import resource
from concurrent.futures import Future, CancelledError
from copy import deepcopy
from pathlib import Path
import ctypes


class NativeInput:
    """AppKit current-event queries stay on the Cocoa UI thread, without a core."""
    def __init__(self,root):
        self.lib=ctypes.CDLL(str(resource(root,'native/libpokemon.dylib')))
        self.lib.pokemon_current_keycode.argtypes=[ctypes.c_int];self.lib.pokemon_current_keycode.restype=ctypes.c_int
        self.lib.pokemon_current_scroll.argtypes=[ctypes.POINTER(ctypes.c_double),ctypes.POINTER(ctypes.c_double),ctypes.POINTER(ctypes.c_int)]
        self.lib.pokemon_current_scroll.restype=ctypes.c_int
    def current_keycode(self,pressed=True):return self.lib.pokemon_current_keycode(int(pressed))
    def current_scroll_delta(self):
        x,y,precise=ctypes.c_double(),ctypes.c_double(),ctypes.c_int()
        return (x.value,y.value,bool(precise.value)) if self.lib.pokemon_current_scroll(ctypes.byref(x),ctypes.byref(y),ctypes.byref(precise)) else None


class AutomationView:
    def __init__(self,monitor):self.monitor=monitor
    def info(self):
        if self.monitor.pending_takeover:
            return dict(running=False,controller='manual',status='idle',reason='Возвращаем управление',script=None,action=None,stage=None)
        return self.monitor.status.get('automation',dict(running=False,controller='manual',status='idle',reason='Ручное управление',script=None,action=None,stage=None))
    @property
    def running(self):return self.info()['running']
    @property
    def reason(self):return self.info()['reason']
    @property
    def logs(self):return self.monitor.status.get('logs',[])
    @property
    def log_revision(self):return self.monitor.status.get('log_revision',0)
    def scripts(self):return sorted((resource(self.monitor.folder,'Bots')).glob('*.py'),key=lambda p:p.name.lower())
    def stop(self,*_,**__):return self.monitor.take_control(focus=False)
    def acknowledge(self):return self.monitor.recover_input()


class HistoryView:
    def __init__(self,monitor):self.monitor=monitor;self.cache={};self.inflight={};self.completed=Future();self.completed.set_result(None);self.local_revision=0;self.generation=None
    @property
    def meta(self):return self.monitor.model.history if self.monitor.model else {}
    @property
    def run(self):return self.meta.get('run')
    @property
    def cycle(self):return self.meta.get('cycle')
    @property
    def revision(self):return (self.meta.get('revision',0),self.local_revision)
    @property
    def stats_revision(self):return self.meta.get('stats_revision',0)
    @property
    def completed_revision(self):return self.meta.get('completed_revision',0)
    @property
    def completed_write(self):
        pending=self.meta.get('completed_pending',False)
        if pending and self.completed.done():self.completed=Future()
        elif not pending and not self.completed.done():self.completed.set_result(None)
        return self.completed
    def read(self,name,*args):
        generation=getattr(self.monitor,'generation',0)
        if generation!=self.generation:
            self.cache.clear();self.inflight.clear();self.generation=generation
        key=(name,args);version=self.completed_revision if name in ('comparisons','forecast_results') else self.stats_revision if name=='cycles' else self.meta.get('revision',0)
        pending=self.inflight.get(key)
        if pending is not None and pending.done():
            try:cancelled=isinstance(pending.exception(),CancelledError)
            except CancelledError:cancelled=True
            if cancelled:self.inflight.pop(key,None)
        previous=self.cache.get(key)
        if (previous is None or previous[0]!=version) and key not in self.inflight and self.monitor.ready:
            future=self.monitor.runtime.submit('history_read',name,args);self.inflight[key]=future
            def done(value):
                if generation!=getattr(self.monitor,'generation',0) or self.inflight.get(key) is not future:return
                self.inflight.pop(key,None);self.cache[key]=(version,value);self.local_revision+=1
            def failed(error):
                if generation!=getattr(self.monitor,'generation',0) or self.inflight.get(key) is not future:return
                self.inflight.pop(key,None);self.monitor.error('Ошибка чтения истории',error,modal=False)
            self.monitor.watch(future,done,failed)
        return previous[1] if previous else []
    def comparisons(self):return self.read('comparisons')
    def rows(self,limit=200):return self.read('rows',limit)
    def events(self,limit=200):return self.read('events',limit)
    def cycles(self,limit=200):return self.read('cycles',limit)
    def forecast_results(self,target_uid,limit=8):return self.read('forecast_results',target_uid,limit)
    def export(self,path):return self.monitor.command('history_export',Path(path))


class OperationView:
    def __init__(self,monitor):self.monitor=monitor;self.pending=False
    @property
    def data(self):return self.monitor.model.operation if self.monitor.model else {}
    @property
    def active(self):return self.pending or self.data.get('active',False)
    @property
    def job(self):return self.data.get('job')
    @property
    def kind(self):return self.data.get('kind')
    @property
    def result(self):return self.data.get('result')
    def begin(self,kind,config):
        if self.active:raise ValueError('Основная игра уже занята')
        self.pending=True;future=self.monitor.runtime.submit('operation_begin',kind,deepcopy(config))
        def done(_):self.pending=False
        def failed(error):self.pending=False;self.monitor.error('Не удалось начать действие',error)
        self.monitor.watch(future,done,failed);return future
    def command(self,command):return self.monitor.command('operation_command',command)


class DeliveryView:
    def __init__(self,monitor):self.monitor=monitor
    @property
    def data(self):return self.monitor.model.delivery if self.monitor.model else {}
    @property
    def current(self):return self.data.get('current')
    def jobs(self):return self.data.get('rows',[])
    def get(self,job_id):return next((r for r in self.jobs() if r['id']==job_id),{})
    def enqueue(self,*args):return self.monitor.command('delivery_enqueue',*args)
    def start(self,*args):return self.monitor.command('delivery_start',*args)
    def pause(self,job_id,cancel=False):return self.monitor.command('delivery_pause',job_id,cancel)
    def interrupt(self):return self.monitor.take_control(focus=False)
