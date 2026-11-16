"""Wall-clock ceiling for an isolated local operation; no core or UI access."""
import time
from .automatic_speed import speed_cap

class FramePacer:
    def __init__(self,maximum,*,clock=time.monotonic,sleep=time.sleep):
        self.maximum=speed_cap(maximum);self.clock=clock;self.sleep=sleep;self.origin=None;self.frame=None;self.last_frame=None;self.generation=None
    def step(self,frame,*,generation=None):
        now=self.clock()
        reset=self.last_frame is None or frame<self.last_frame or generation is not None and generation!=self.generation
        self.last_frame=frame;self.generation=generation
        if reset:self.frame=frame;self.origin=now;return
        # Do not accumulate an unbounded catch-up burst after an OS stall.
        elapsed=(frame-self.frame)/(59.7275*self.maximum)
        if now-self.origin-elapsed>.1:self.origin=now-elapsed
        delay=self.origin+elapsed-now
        while delay>0:
            self.sleep(min(.008,delay));delay=self.origin+elapsed-self.clock()
