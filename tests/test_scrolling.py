"""Preserve trackpad fractions, bound momentum and avoid wheel-sized row jumps."""
import sys
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.scrolling import wheel_pixels,Motion
from pokemon_red.engine import Game

class ScrollingTests(unittest.TestCase):
    def test_precise_points_are_preserved(self):
        self.assertEqual(wheel_pixels(.125,True),-.125)
        self.assertEqual(wheel_pixels(-2.75,True),2.75)
        self.assertEqual(wheel_pixels(120),-36)
        self.assertEqual(wheel_pixels(1),-12)
    def test_fractional_gestures_accumulate(self):
        motion=Motion()
        for _ in range(24):motion.add(.125,0,100)
        self.assertEqual(motion.target,3)
        values=[]
        for _ in range(60):
            point=motion.step()
            if point is None:break
            values.append(point)
        self.assertEqual(values[-1],3);self.assertEqual(values,sorted(values))
    def test_fraction_survives_viewport_pixel_rounding(self):
        motion=Motion();actual=0
        for _ in range(80):
            motion.add(.25,actual,100)
            while motion.target is not None:motion.step()
            actual=round(motion.position)
        self.assertEqual(motion.position,20)
    def test_edges_clamp_and_direction_reverses_immediately(self):
        motion=Motion();motion.add(1000,90,100);self.assertEqual(motion.target,100)
        motion.step();motion.add(-200,95,100);self.assertEqual(motion.target,0)
        for _ in range(30):motion.step()
        self.assertEqual(motion.position,0)
    def test_native_reader_does_not_reuse_nonwheel_events(self):
        # No Game is opened and no save is accessed; the exported AppKit reader
        # must be inert in a headless process with no current scroll event.
        import ctypes
        lib=ctypes.CDLL(str(ROOT/'native/libpokemon.dylib'));fn=lib.pokemon_current_scroll
        fn.argtypes=[ctypes.POINTER(ctypes.c_double),ctypes.POINTER(ctypes.c_double),ctypes.POINTER(ctypes.c_int)];fn.restype=ctypes.c_int
        x,y,p=ctypes.c_double(),ctypes.c_double(),ctypes.c_int();self.assertEqual(fn(ctypes.byref(x),ctypes.byref(y),ctypes.byref(p)),0)

if __name__=='__main__':unittest.main()
