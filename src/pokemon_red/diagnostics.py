"""Small bounded input log; no typed text, screenshots or global keyboard hooks."""
from datetime import datetime,timezone
from collections import defaultdict, deque
import json

class Diagnostics:
    def __init__(self,root):
        self.path=root/'Data/logs/input.jsonl';self.path.parent.mkdir(parents=True,exist_ok=True)
        self.last_input=None
        self.timings=defaultdict(lambda:deque(maxlen=512))
        self.slow_operations=deque(maxlen=32)

    def measure(self,name,milliseconds,**context):
        if name not in self.timings and len(self.timings)>=128:
            name='other'
        self.timings[name].append(milliseconds)
        if milliseconds>=30:
            self.slow_operations.append(dict(operation=name,milliseconds=round(milliseconds,3),**context))

    def performance(self):
        def summary(samples):
            ordered=sorted(samples);n=len(ordered)
            return dict(samples=n,p50_ms=round(ordered[n//2],3),p95_ms=round(ordered[min(n-1,int(n*.95))],3),max_ms=round(ordered[-1],3))
        return dict(timings={name:summary(values) for name,values in self.timings.items() if values},slow_operations=list(self.slow_operations))

    def record(self,code,**details):
        event=dict(time=datetime.now(timezone.utc).isoformat(),code=code,**details)
        if code=='key_down':self.last_input=event
        try:
            if self.path.exists() and self.path.stat().st_size>1024*1024:self.path.replace(self.path.with_suffix('.previous.jsonl'))
            with self.path.open('a') as f:f.write(json.dumps(event,ensure_ascii=False)+'\n')
        except OSError:pass  # Debug logging must never disable input.
