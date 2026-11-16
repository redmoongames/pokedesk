"""Bounded, optional disk cache shared by preview workers and training processes.

Each directed path belongs to one exact map geometry and walking policy. Live
navigation uses live obstacles; previews use their conservative NPC envelopes.
Cache failures, locks or corrupt entries always fall back to ordinary search.
"""
from collections import OrderedDict
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
import hashlib
import json
import sqlite3
import threading
import time

from .editions import rom_sha1,reference_path
from .run_context import digest

SCHEMA=1


@lru_cache(maxsize=16)
def policy_key(root):
    h=hashlib.sha256(rom_sha1(root).encode());folder=Path(__file__).parent
    for name in ('path_cache.py','navigation.py','training.py','walking_route.py','portal_graph.py','movement.py','field_tools.py','hunt_spots.py','telemetry.py'):
        h.update((folder/name).read_bytes())
    h.update(reference_path(root,'grind_zones.json').read_bytes())
    return h.hexdigest()


def map_key(grid):
    from .training import trainer_zones
    return digest([grid.get('static_geometry') or [grid.get('width'),grid.get('height'),grid.get('tiles')],
        sorted(map(tuple,grid.get('obstacles',[]))),sorted(trainer_zones(grid)),
        sorted(map(tuple,grid.get('script_triggers',[]))),grid.get('warps',[]),
        grid.get('objects',[]),grid.get('portal_points',[]),grid.get('signs',[]),grid.get('sign_approaches',[])])


def valid_entry(kind,value):
    if not isinstance(value,dict) or type(value.get('ok')) is not bool:return False
    if not value['ok']:
        return kind=='path' or all(isinstance(value.get(k),str) for k in ('code','message'))
    def points(items):
        return isinstance(items,list) and all(isinstance(p,(list,tuple)) and len(p)==2 and all(type(n) is int for n in p) for p in items)
    if kind=='path':return points(value.get('value'))
    farm=value.get('value')
    return isinstance(farm,dict) and all(points(farm.get(k)) for k in ('pair','strip','path')) and len(farm['pair'])==2 and all(k in farm for k in ('length','continuous','grass','steps'))


class PathCache:
    def __init__(self,root,*,limit=4096):
        self.root=Path(root);self.limit=max(1,limit);self.memory=OrderedDict()
        self.db=None;self.disabled=False;self.lock=threading.RLock()
        self.namespace=policy_key(self.root)

    def _database(self):
        if self.disabled:return None
        if self.db is None:
            try:
                folder=self.root/'Data';folder.mkdir(parents=True,exist_ok=True)
                db=sqlite3.connect(folder/'navigation-cache.sqlite3',timeout=.05,check_same_thread=False)
                db.execute('PRAGMA journal_mode=WAL');db.execute('PRAGMA synchronous=NORMAL')
                db.execute('CREATE TABLE IF NOT EXISTS entries (key TEXT PRIMARY KEY,body TEXT NOT NULL,checksum TEXT NOT NULL,written REAL NOT NULL)')
                db.execute('CREATE INDEX IF NOT EXISTS entries_written ON entries(written)')
                self.db=db
            except (OSError,sqlite3.Error):
                if 'db' in locals():db.close()
                self.disabled=True
        return self.db

    def _remember(self,key,value):
        self.memory[key]=deepcopy(value);self.memory.move_to_end(key)
        while len(self.memory)>self.limit:self.memory.popitem(last=False)

    def get(self,kind,geometry,*points):
        key=digest([SCHEMA,self.namespace,kind,geometry,points])
        with self.lock:
            if key in self.memory:
                self.memory.move_to_end(key);return deepcopy(self.memory[key])
            db=self._database()
            try:
                row=db.execute('SELECT body,checksum FROM entries WHERE key=?',(key,)).fetchone() if db else None
                if row and hashlib.sha256(row[0].encode()).hexdigest()==row[1]:
                    value=json.loads(row[0])
                    if valid_entry(kind,value):
                        self._remember(key,value);return value
            except (sqlite3.Error,ValueError,TypeError,AttributeError):pass
        return None

    def put(self,kind,geometry,points,value):
        key=digest([SCHEMA,self.namespace,kind,geometry,points])
        with self.lock:
            self._remember(key,value);db=self._database()
            try:
                if db:
                    body=json.dumps(value,separators=(',',':'))
                    with db:
                        db.execute('INSERT OR REPLACE INTO entries VALUES(?,?,?,?)',(key,body,hashlib.sha256(body.encode()).hexdigest(),time.time()))
                        # Keep the on-disk cache bounded across maps, saves and versions.
                        db.execute('DELETE FROM entries WHERE key IN (SELECT key FROM entries ORDER BY written DESC LIMIT -1 OFFSET ?)',(self.limit,))
            except sqlite3.Error:pass

    def close(self):
        with self.lock:
            if self.db is not None:self.db.close();self.db=None


@lru_cache(maxsize=8)
def shared_cache(root):return PathCache(Path(root).resolve())
