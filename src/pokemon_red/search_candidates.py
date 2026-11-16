"""Bounded, hash-verified candidate checkpoints; no live core or UI access."""
import hashlib
from pathlib import Path
from .acquisition import read_json,write_json
from .persistence import atomic_bytes

def valid_hash(value):return isinstance(value,str) and len(value)==64 and all(c in '0123456789abcdef' for c in value)

class CandidateStore:
    def __init__(self,root,prefix,*,retention=3):
        if prefix not in ('starter','wild'):raise ValueError('Unknown candidate namespace')
        self.retention=max(3,min(32,retention))
        self.data=Path(root)/'Data';self.prefix=prefix;self.folder=self.data/(prefix+'-candidates');self.index=self.data/(prefix+'-candidates.json');self.best_state=self.data/(prefix+'-best.state');self.best_info=self.data/(prefix+'-best.json')
    def rows(self):
        rows=read_json(self.index,[])
        if not rows:
            old=read_json(self.best_info,{})
            if old:rows=[old]
        return rows[:3] if isinstance(rows,list) else []
    def checkpoint(self,sha):
        if not valid_hash(sha):raise ValueError('Invalid candidate checksum')
        path=self.folder/(sha+'.state')
        if not path.is_file():path=self.best_state
        data=path.read_bytes()
        if hashlib.sha256(data).hexdigest()!=sha:raise ValueError('Candidate checksum mismatch')
        return data
    def load(self,assess):
        result=[]
        for item in self.rows():
            try:
                rated=assess(item.get('pokemon'));sha=item.get('sha256','')
                if rated is None:continue
                self.checkpoint(sha)
            except (OSError,ValueError,KeyError,TypeError):continue
            result.append(dict(rated,sha256=sha))
        return sorted(result,key=lambda v:v['rank'],reverse=True)[:3]
    def record(self,history,candidate,data,*,top_k=False):
        if top_k:
            rows=rank_candidates([*history,candidate])
            if not any(v is candidate for v in rows):return history
        elif history and candidate['rank']<=history[0]['rank']:return history
        sha=candidate.get('sha256')
        if not valid_hash(sha) or hashlib.sha256(data).hexdigest()!=sha:return history
        self.folder.mkdir(parents=True,exist_ok=True);atomic_bytes(self.folder/(sha+'.state'),data,durable=True)
        history=rows if top_k else ([candidate]+[v for v in history if v['sha256']!=sha])[:3]
        self.publish(history);self.prune(history);return history
    def publish(self,history):
        write_json(self.index,history)
        if history:
            atomic_bytes(self.best_state,self.checkpoint(history[0]['sha256']),durable=True);write_json(self.best_info,history[0])
    def prune(self,history):
        retained={v['sha256']+'.state' for v in history}
        files=sorted(self.folder.glob('*.state'),key=lambda p:p.stat().st_mtime_ns,reverse=True)
        for path in files:
            if len(retained)>=self.retention:break
            retained.add(path.name)
        for path in files:
            if path.name not in retained:path.unlink()
    def copy_to(self,destination):
        target=CandidateStore(destination,self.prefix);valid=[]
        for candidate in self.rows():
            try:data=self.checkpoint(candidate.get('sha256'))
            except (OSError,ValueError,TypeError):continue
            target.folder.mkdir(parents=True,exist_ok=True);atomic_bytes(target.folder/(candidate['sha256']+'.state'),data,durable=True);valid.append(candidate)
        if valid:target.publish(valid);target.prune(valid)


def rank_candidates(rows,limit=3):
    """Stable top distinct Pokémon; checkpoint hashes are not identities."""
    result=[];seen=set()
    for row in sorted(rows,key=lambda r:r['rank'],reverse=True):
        uid=row.get('pokemon',{}).get('uid') or row.get('sha256')
        if uid in seen:continue
        seen.add(uid);result.append(row)
        if len(result)==limit:break
    return result
