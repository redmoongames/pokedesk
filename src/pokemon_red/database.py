"""Mutable profile journal. Legacy reference tables are retained but never used."""
import json
import sqlite3
import uuid
from pathlib import Path
from .paths import session_paths

SCHEMA='''
CREATE TABLE IF NOT EXISTS owned_pokemon (uid TEXT PRIMARY KEY,seen_at TEXT,location TEXT,present INTEGER NOT NULL,body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS training_runs (id TEXT PRIMARY KEY,started_at TEXT,ended_at TEXT,route TEXT,strategy TEXT,target_uid TEXT,target_level INTEGER,status TEXT,team_fingerprint TEXT,body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS training_cycles (id INTEGER PRIMARY KEY,run_id TEXT,number INTEGER,started_at TEXT,ended_at TEXT,status TEXT,start_frame INTEGER,end_frame INTEGER,game_seconds REAL,wall_seconds REAL,active_seconds REAL,target_xp INTEGER,team_xp INTEGER,battles INTEGER,team_fingerprint TEXT,body TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS cycles_run_idx ON training_cycles(run_id,number);
CREATE INDEX IF NOT EXISTS cycles_comparison_idx ON training_cycles(status,team_fingerprint);
CREATE TABLE IF NOT EXISTS timelines (id TEXT PRIMARY KEY,parent_id TEXT,started_at TEXT,reason TEXT,last_frame INTEGER,body TEXT NOT NULL);
'''

SCHEMA_VERSION=1

def connect(root):
    profile=session_paths(root).profile
    profile.data.mkdir(parents=True,exist_ok=True)
    path=profile.journal;existing=path.exists() and path.stat().st_size>0
    db=sqlite3.connect(path,timeout=5)
    db.execute('PRAGMA busy_timeout=5000')
    version=db.execute('PRAGMA user_version').fetchone()[0]
    if version>SCHEMA_VERSION:
        db.close();raise RuntimeError('База создана более новой версией приложения')
    if version<1:
        if existing:
            folder=profile.data/'backups/database';folder.mkdir(parents=True,exist_ok=True)
            with sqlite3.connect(folder/f'history-v{version}-{uuid.uuid4().hex[:12]}.sqlite3') as backup:db.backup(backup)
        db.executescript('BEGIN IMMEDIATE;\n'+SCHEMA+'\nPRAGMA user_version=1;\nCOMMIT;')
    return db

def load_reference(root):
    """Compatibility facade: reference reads never open the profile journal."""
    from .reference_pack import load_reference as read_pack
    return read_pack(root)
