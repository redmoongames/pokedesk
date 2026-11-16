"""Actual mGBA SIO cable between two isolated emulator cores."""
import ctypes
from pathlib import Path
class Cable:
    def __init__(self,a,b):
        a._check();b._check()
        if Path(a.lib._name).resolve()!=Path(b.lib._name).resolve():raise ValueError('Обе стороны обмена должны использовать одно ядро')
        self.a=a;self.b=b;self.lib=a.lib
        self.lib.pokemon_link_open.argtypes=[ctypes.c_void_p,ctypes.c_void_p];self.lib.pokemon_link_open.restype=ctypes.c_void_p
        self.lib.pokemon_link_step.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_uint,ctypes.c_uint];self.lib.pokemon_link_step.restype=ctypes.c_int
        self.lib.pokemon_link_close.argtypes=[ctypes.c_void_p];self.lib.pokemon_link_close.restype=None
        self.handle=self.lib.pokemon_link_open(a.handle,b.handle)
        if not self.handle:raise RuntimeError('Не удалось подключить GBA link cable')
    def advance(self,frames=1,a=0,b=0):
        self.a._check();self.b._check()
        if not self.handle or type(frames) is not int or not 0<=frames<=3600:raise ValueError('Некорректный шаг link cable')
        if not self.lib.pokemon_link_step(self.handle,a,b,frames):raise RuntimeError('Нарушена синхронизация GBA link cable; оригинальные сохранения не изменены')
    def close(self):
        if self.handle:self.lib.pokemon_link_close(self.handle);self.handle=None
    def __enter__(self):return self
    def __exit__(self,*_):self.close()
