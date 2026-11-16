"""Integer-pixel game centered on its display, with independent side windows."""
from dataclasses import dataclass
import ctypes,sys

@dataclass(frozen=True)
class Rect:
    x:int;y:int;width:int;height:int
    @property
    def geometry(self):return f'{self.width}x{self.height}{self.x:+d}{self.y:+d}'

@dataclass(frozen=True)
class Layout:
    scale:int;game:Rect;battle:Rect;trainer:Rect

def display_bounds(window):
    """Quartz uses desktop points, like Tk; retain negative monitor origins."""
    anchor=getattr(window,'master',None) or window
    cx=anchor.winfo_rootx()+anchor.winfo_width()/2;cy=anchor.winfo_rooty()+anchor.winfo_height()/2
    if sys.platform=='darwin':
        try:
            class Point(ctypes.Structure):_fields_=[('x',ctypes.c_double),('y',ctypes.c_double)]
            class Size(ctypes.Structure):_fields_=[('width',ctypes.c_double),('height',ctypes.c_double)]
            class Bounds(ctypes.Structure):_fields_=[('origin',Point),('size',Size)]
            lib=ctypes.CDLL('/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics')
            lib.CGGetActiveDisplayList.argtypes=[ctypes.c_uint32,ctypes.POINTER(ctypes.c_uint32),ctypes.POINTER(ctypes.c_uint32)]
            lib.CGDisplayBounds.argtypes=[ctypes.c_uint32];lib.CGDisplayBounds.restype=Bounds
            ids=(ctypes.c_uint32*32)();count=ctypes.c_uint32()
            if lib.CGGetActiveDisplayList(32,ids,ctypes.byref(count))==0:
                screens=[]
                for number in ids[:count.value]:
                    b=lib.CGDisplayBounds(number);screens.append(Rect(round(b.origin.x),round(b.origin.y),round(b.size.width),round(b.size.height)))
                return next((r for r in screens if r.x<=cx<r.x+r.width and r.y<=cy<r.y+r.height),screens[0])
        except (OSError,AttributeError,IndexError):pass
    return Rect(0,0,window.winfo_screenwidth(),window.winfo_screenheight())

def layout(display,preferred_scale):
    """The game stays at the display center, even in overlapping-tool fallback.

    Keep integer scale and usable native trainer width. At smaller desktops
    lower the game scale until both side columns fit; genuinely narrow displays
    use independently focusable overlapping tools, never shift the game.
    """
    gap=12;edge=12
    maximum=max(1,min(5,int(preferred_scale),max(1,(display.height-100)//160)))
    choices=[s for s in range(1,maximum+1) if (display.width-240*s)//2>=480+gap+edge]
    scale=max(choices,default=min(maximum,max(1,(display.width-2*edge)//240)))
    width,height=240*scale,160*scale
    gx=display.x+(display.width-width)//2;gy=display.y+(display.height-height)//2-32
    ph=max(1,min(820,display.height-80));py=display.y+(display.height-ph-32)//2
    side=(display.width-width)//2-gap-edge
    if side>=480:
        trainer=Rect(gx+width+gap,py,min(580,side),ph)
        battle=Rect(gx-gap-min(350,side),py,min(350,side),ph)
    else:
        tw=min(580,max(1,display.width-2*edge));bw=min(350,max(1,display.width-2*edge))
        trainer=Rect(display.x+display.width-edge-tw,py,tw,ph)
        battle=Rect(display.x+edge,py,bw,ph)
    return Layout(scale,Rect(gx,gy,width,height),battle,trainer)

def place(window,rect):
    # A leading negative Tk offset means distance from the far edge, unlike a
    # signed global desktop coordinate. Explicit + before it keeps global x/y.
    window.geometry(f'{rect.width}x{rect.height}+{rect.x}+{rect.y}')
