"""Hard identity filters; IV score is capped at each requested threshold."""
from .iv_preferences import score_ivs
from .new_game_config import mon_gender
from .search_odds import nature_ids

def assess(config,mon):
    if not mon or not mon.get('checksum_valid') or mon.get('species_id')!=config.species_id:return None
    if config.gender!='any' and mon_gender(mon)!=config.gender:return None
    choices=nature_ids(config.natures,config.nature)
    if choices and mon['nature'] not in choices:return None
    if config.shiny and not mon.get('shiny'):return None
    rated=score_ivs(mon.get('ivs'),config.min_ivs,getattr(config,'priority_ivs',()))
    if rated is None or mon.get('is_egg'):return None
    return dict(rated,pokemon={k:mon[k] for k in ('uid','species_id','personality','nature','ivs','shiny','checksum_valid','level')})

def load(root,config):
    from .search_candidates import CandidateStore
    return CandidateStore(root,'starter').load(lambda mon:assess(config,mon))

def record(root,history,candidate,data):
    from .search_candidates import CandidateStore
    return CandidateStore(root,'starter').record(history,candidate,data)

def copy_saved(source,destination):
    from .search_candidates import CandidateStore
    CandidateStore(source,'starter').copy_to(destination)
