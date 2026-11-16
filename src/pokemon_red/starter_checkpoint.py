"""Verified pre-gift snapshots survive manual play between search sessions."""
import hashlib,time
from .acquisition import read_json,write_json
from .persistence import SaveSnapshot,atomic_bytes
from .telemetry import symbols,decode_text
from .i18n import t
IDENTITY=('player_name','rival_name','player_gender','species_id')
def valid_frontier(game):
    sy=symbols(game.root)
    return not game.read8(sy['gPlayerPartyCount']) and 'energetic' in decode_text(game.read_bytes(sy['gStringVar4'],700)).lower()
def store(root,snapshot,config):
    atomic_bytes(root/'Data/starter-frontier.state',snapshot.state,durable=True);atomic_bytes(root/'Data/starter-frontier.sav',snapshot.sram,durable=True)
    write_json(root/'Data/starter-frontier.json',dict(config=config,frame=snapshot.frame,main_hashes={'FireRed.state':hashlib.sha256(snapshot.state).hexdigest(),'FireRed.sav':hashlib.sha256(snapshot.sram).hexdigest()}))
def recover(root,config):
    marker=read_json(root/'Data/starter-frontier.json',{});sources=[]
    if marker:sources.append((marker,root/'Data','starter-frontier.state','starter-frontier.sav'))
    jobs=sorted((root/'Sessions/operations').glob('*/result.json'),key=lambda p:p.stat().st_mtime,reverse=True)
    for p in jobs:
        result=read_json(p,{});spec=read_json(p.parent/'operation.json',{})
        if spec.get('kind')=='prologue' and result.get('prologue',{}).get('phase')=='search':sources.append((dict(config=spec['config'],main_hashes=result.get('main_hashes',{})),p.parent/'main/Data','FireRed.state','FireRed.sav'))
    for marker,folder,state,save in sources:
        if any(marker.get('config',{}).get(k)!=config.get(k) for k in IDENTITY):continue
        try:a=(folder/state).read_bytes();b=(folder/save).read_bytes()
        except OSError:continue
        if marker.get('main_hashes')=={'FireRed.state':hashlib.sha256(a).hexdigest(),'FireRed.sav':hashlib.sha256(b).hexdigest()}:return SaveSnapshot(a,b,marker.get('frame',0),time.time())
    raise ValueError(t('search.no_frontier'))
