"""Wild job lifecycle: independent hunt, verified capture, clinic, transfer."""
import hashlib,shutil,time
from .acquisition import read_json,write_json,WILD_TEMPLATE,template_for
from .acquisition_play import AcquisitionAttention
from .hunting_template import choose_route
from .journey import Journey
from .models import read_inventory
from .wild_capture import restore_capture

def run_wild(worker):
    w=worker;p=Journey(w.game,w);w.player=p
    project=w.game.root.parent.parent.parent
    template=read_json(project/template_for(project,WILD_TEMPLATE)/'metadata.json',{})
    hunter=template['hunter_uid'];config=w.config
    route=w.progress.get('route') or choose_route(project,config.species_id)
    w.progress['route']=route;write_json(w.job/'progress.json',w.progress)
    result=read_json(w.job/'result.json',{})
    caught=w.job/'checkpoints/capture-caught'
    def load_caught():
        manifest=read_json(caught/'manifest.json',{})
        if not {'FireRed.state','FireRed.sav','metadata.json'}<=manifest.keys() or any('/' in n or n in ('.','..') or hashlib.sha256((caught/n).read_bytes()).hexdigest()!=h for n,h in manifest.items()):raise AcquisitionAttention('Повреждён checkpoint поимки')
        p.g.load_state(caught/'FireRed.state');p.persist()
    if result.get('uid') and w.status.get('resume_from') in ('attention','error'):
        load_caught()
    if not result.get('uid') and (caught/'manifest.json').exists():
        load_caught()
        journal=read_json(w.job/'capture-session.json',{})
        mon=next((m for m in read_inventory(p.g)['party']+read_inventory(p.g)['boxes'] if m['uid']==journal.get('uid')),None)
        if mon:result=dict(uid=mon['uid'],found=mon,found_at=time.time(),transfer_ready=False);write_json(w.job/'result.json',result)
    if not result.get('uid'):
        restore_capture(p)
        # Trapping foes can force incidental battles during a long shiny hunt.
        # Keep the hunter's capture kit when those battles cause level-ups.
        from .move_plan import compile_plan
        from .learning import LearningRuntime
        hunter_mon=next(m for m in p.state()['party'] if m['uid']==hunter)
        kit=compile_plan(hunter_mon,100,[m['id'] for m in hunter_mon['moves']],p.g.root,mode='stay')
        p.learning=LearningRuntime(kit,event=w.event,checkpoint=lambda _:p.checkpoint('hunter-learning'),suspend=lambda:None)
        if not w.progress.get('search_offset_applied') and not p.state()['in_battle']:
            p.advance(1+int(w.job.name[:8],16)%4096);p.persist()
            w.progress['search_offset_applied']=True;write_json(w.job/'progress.json',w.progress)
        w.update(status='searching',stage='Охота · '+route,route=route)
        mon=p.hunt(config.species_id,config.shiny,route,hunter_uid=hunter)
        result=dict(uid=mon['uid'],found=mon,found_at=time.time(),attempts=w.attempts,transfer_ready=False)
        write_json(w.job/'result.json',result)
    w.uid=result['uid']
    inv=read_inventory(p.g);mon=next((m for m in inv['party']+inv['boxes'] if m['uid']==w.uid),None)
    if mon is None:
        load_caught()
    w.update(status='preparing',stage='Pokémon пойман · готовим реальный обмен',pokemon=result['found'])
    p.center();p.ensure_party(w.uid);p.heal();p.save_game()
    inv=read_inventory(p.g);mon=next(m for m in inv['party'] if m['uid']==w.uid)
    if mon['species_id']!=config.species_id or config.shiny and not mon['shiny'] or not mon['checksum_valid']:raise AcquisitionAttention('Не совпал результат поимки')
    folder=p.checkpoint('ready-for-transfer',permanent=True)
    result.update(pokemon=mon,transfer_ready=True,ready_checkpoint=str(folder),ready_at=time.time());write_json(w.job/'result.json',result)
    w.update(status='ready',stage='Пойман · готов к переносу',pokemon=mon,transfer_ready=True,ready_checkpoint=str(folder))
    # Only replaceable retry checkpoints are disposable. The encounter, caught
    # Pokémon, ordinary flash save and transfer checkpoint remain durable.
    temporary=w.job/'checkpoints/capture-current'
    if temporary.exists():shutil.rmtree(temporary)
    p.advance(2);w.last_ui=0;w.next_heartbeat=0;w.heartbeat()
