"""Session-owned journal projection with one ordered, durable SQLite writer.

The projection answers snapshot queries without disk locks. The disk remains the
source across launches; recent events, battles and cycles are projected. The
complete history remains on disk for process analytics and export.
"""
from pathlib import Path
from .paths import session_paths
import sqlite3
import json,time
from .file_writer import FileWriter

TABLES=('battles','events','training_runs','training_cycles','timelines','owned_pokemon')

class JournalStore:
    def __init__(self,disk,root,*,notify=None,active_timeline=None):
        self.memory=sqlite3.connect(':memory:');self.commands=[];self.pending=[];self.commits=0;self.disk=None;self.error=None;self.error_reported=False;self.recovery=[];self.last_write=None
        self.active_timeline=active_timeline
        for table in TABLES:
            schema=disk.execute('SELECT sql FROM sqlite_master WHERE type=\'table\' AND name=?',(table,)).fetchone()[0]
            self.memory.execute(schema)
            query='SELECT * FROM '+table
            parameters=()
            if table in ('events','battles','training_cycles'):query+=' ORDER BY id DESC LIMIT 2000'
            elif table=='training_runs':
                query+=' WHERE ended_at IS NULL OR id IN (SELECT run_id FROM training_cycles ORDER BY id DESC LIMIT 2000) OR id IN (SELECT id FROM training_runs ORDER BY started_at DESC LIMIT 200)'
            elif table=='timelines':
                query+=' WHERE id=? OR id IN (SELECT id FROM timelines ORDER BY started_at DESC LIMIT 2000)';parameters=(self.active_timeline or '',)
            rows=disk.execute(query,parameters).fetchall()
            if rows:self.memory.executemany('INSERT INTO '+table+' VALUES('+','.join('?' for _ in rows[0])+')',rows)
        self.memory.commit();disk.close()
        self.path=session_paths(root).profile.journal;self.writer=FileWriter(notify or (lambda:None),capacity=256)
    def ready_work(self):
        return any(future.done() for future,_ in self.pending) or bool(self.error and not self.error_reported)

    def check_health(self):
        remaining=[]
        for future,batch in self.pending:
            if future.done():
                try:future.result()
                except Exception as error:self.error=error;self.recovery.append(batch)
            else:remaining.append((future,batch))
        self.pending=remaining
        if self.error and not self.error_reported:
            self.error_reported=True
            raise RuntimeError('Ошибка журнала SQLite; игра остановлена, незаписанные события сохранены в памяти: '+str(self.error)) from self.error
    def execute(self,sql,parameters=()):
        self.check_health();parameters=tuple(parameters)
        cursor=self.memory.execute(sql,parameters)
        if not sql.lstrip().upper().startswith(('SELECT','PRAGMA','EXPLAIN')):
            self.commands.append((sql,(parameters,),cursor.lastrowid if sql.lstrip().upper().startswith('INSERT INTO training_cycles'.upper()) else None))
        return cursor
    def executemany(self,sql,parameters):
        self.check_health();rows=tuple(tuple(r) for r in parameters)
        cursor=self.memory.executemany(sql,rows);self.commands.append((sql,rows,None));return cursor
    def commit(self):
        self.memory.commit();self.commits+=1
        if self.commits%100==0:
            for table in ('events','battles','training_cycles'):
                self.memory.execute('DELETE FROM '+table+' WHERE id < COALESCE((SELECT id FROM '+table+' ORDER BY id DESC LIMIT 1 OFFSET 1999),0)')
            self.memory.execute('DELETE FROM training_runs WHERE ended_at IS NOT NULL AND id NOT IN (SELECT run_id FROM training_cycles) AND id NOT IN (SELECT id FROM training_runs ORDER BY started_at DESC LIMIT 200)')
            self.memory.execute('DELETE FROM timelines WHERE id!=? AND id NOT IN (SELECT id FROM timelines ORDER BY started_at DESC LIMIT 2000)',(self.active_timeline or '',))
            self.memory.commit()
        if not self.commands:return
        batch=tuple(self.commands);self.commands=[]
        if self.error:
            self.recovery.append(batch);return
        def persist():
            if self.error:raise RuntimeError('Писатель журнала остановлен после ошибки')
            if self.disk is None:
                self.disk=sqlite3.connect(self.path,timeout=5)
                self.disk.execute('PRAGMA synchronous=FULL')
            try:
                with self.disk:
                    for sql,rows,expected_id in batch:
                        if expected_id is None:self.disk.executemany(sql,rows)
                        else:
                            cursor=self.disk.execute(sql,rows[0])
                            if cursor.lastrowid!=expected_id:raise RuntimeError('Журнал изменён другим писателем')
            except Exception as error:self.error=error;raise
        try:
            self.last_write=self.writer.submit(persist);self.pending.append((self.last_write,batch));return self.last_write
        except Exception as error:
            self.error=error;self.recovery.append(batch)
    def close(self):
        self.commit()
        def close_disk():
            if self.disk:self.disk.close();self.disk=None
        future=self.writer.submit(close_disk);self.writer.close();future.result()
        try:self.check_health()
        finally:
            self.memory.close()
            if self.recovery:
                # Failure handling never sends recursive journal events. Preserve
                # failed SQL batches for explicit recovery, without replaying IDs.
                from .persistence import atomic_bytes
                path=self.path.with_name('journal-recovery-'+str(time.time_ns())+'.json')
                atomic_bytes(path,json.dumps(dict(error=str(self.error),batches=self.recovery),ensure_ascii=False).encode())
