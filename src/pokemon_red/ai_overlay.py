"""Small canvas indicator; no core access, animation, timers or extra windows."""
from .speeds import speed_text
from .i18n import t

PPM_HEADER=b'P6\n240 160\n255\n'
GLASS=bytes(round(value*.45) for value in range(256))
PANELS=((7,6,233,23),(25,64,215,99))
WHITE_5_PERCENT=bytes(round(value*.95+255*.05) for value in range(256))

def tint_video(video):
    """Translate only the native RGB payload, before Tk scales the image."""
    if not video.startswith(PPM_HEADER):return video
    pixels=bytearray(video[len(PPM_HEADER):].translate(WHITE_5_PERCENT))
    # Translucent backing for the text, composed at 240×160 rather than in a
    # separate OS window. Each row uses the C-level byte translation table.
    for x1,y1,x2,y2 in PANELS:
        for y in range(y1,y2):
            start=(y*240+x1)*3;end=(y*240+x2)*3
            pixels[start:end]=pixels[start:end].translate(GLASS)
    return PPM_HEADER+pixels

class AIOverlay:
    def __init__(self,canvas):
        self.canvas=canvas;self._key=None
        self.badge=canvas.create_rectangle(0,0,0,0,fill='',outline='#526975',state='hidden')
        self.title=canvas.create_text(0,0,text='●  Под управлением ИИ',fill='#a8e6cf',anchor='w',state='hidden')
        self.speed=canvas.create_text(0,0,text='',fill='#eaf4fa',anchor='e',state='hidden')
        self.plate=canvas.create_rectangle(0,0,0,0,fill='',outline='#526975',state='hidden')
        self.hint=canvas.create_text(0,0,text='Чтобы забрать управление,\nнажмите любую клавишу',fill='#eaf4fa',justify='center',state='hidden')
        self.items=(self.badge,self.title,self.speed,self.plate,self.hint)
    def update(self,visible,scale,speed,*,returning=False,limited=False,capture_mode=None):
        key=(visible,scale,speed,returning,limited,capture_mode)
        if key==self._key:return
        self._key=key;c=self.canvas
        for item in self.items:c.itemconfigure(item,state='normal' if visible else 'hidden')
        if not visible:return
        c.coords(self.badge,7*scale,6*scale,233*scale,23*scale)
        c.coords(self.title,12*scale,14.5*scale);c.coords(self.speed,228*scale,14.5*scale)
        c.coords(self.plate,25*scale,64*scale,215*scale,99*scale)
        c.coords(self.hint,120*scale,81.5*scale)
        c.itemconfigure(self.title,font=('Helvetica',max(8,scale*4),'bold'))
        c.itemconfigure(self.title,text=t('capture.overlay_title') if capture_mode else '●  Под управлением ИИ')
        caption='Без лимита' if speed is None else ('до ' if limited else '')+speed_text(speed)+'×'
        c.itemconfigure(self.speed,text=caption,font=('Helvetica',max(8,scale*4),'bold'))
        hint=t('capture.overlay_candidate') if capture_mode=='candidate' else t('capture.overlay_search') if capture_mode else 'Чтобы забрать управление,\nнажмите любую клавишу'
        c.itemconfigure(self.hint,text='Возвращаем управление…' if returning else hint,font=('Helvetica',max(9,scale*4)),width=178*scale)
