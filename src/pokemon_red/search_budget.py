"""One coordinator-owned real-time budget, shared by all speculative lanes."""
import math,time
from .acquisition_play import JobPaused
from .i18n import t

class SearchDeadline(JobPaused):pass

def seconds(value):
    if value is not None and (type(value) is not int or not 1<=value<=86400):raise ValueError(t('capture.invalid_search_time'))
    return value

class SearchBudget:
    def __init__(self,duration,*,remaining=None,clock=time.monotonic):
        self.duration=seconds(duration);self.clock=clock;self.deadline=None;self.frozen=None
        self.allowance=duration
        if duration is not None and type(remaining) in (int,float) and math.isfinite(remaining) and 0<remaining<=duration:self.allowance=remaining
    def start(self):
        if self.duration is not None and self.deadline is None:self.deadline=self.clock()+self.allowance
    def remaining(self):
        if self.duration is None:return None
        if self.frozen is not None:return self.frozen
        return max(0,self.deadline-self.clock()) if self.deadline is not None else self.allowance
    def expired(self):return self.deadline is not None and self.remaining()<=0
    def freeze(self):self.frozen=self.remaining()
