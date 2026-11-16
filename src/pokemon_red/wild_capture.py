"""Resumable, button-only capture with a permanent encounter and one retry point."""
import hashlib,time
from .acquisition import read_json,write_json
from .acquisition_play import AcquisitionAttention
from .capture import VenusaurPolicy,SLEEP_MOVES
from .catalog import species
from .player_inventory import read_player_inventory

class CaptureBattle:
    def __init__(self,player,*,policy=None):
        self.p=player;self.g=player.g;self.w=player.w;self.journal=self.g.root/'capture-session.json'
        self.data=read_json(self.journal,{})
        self.pending=None;self.before=None;self.chosen=None;self.saved_signature=None;self.policy=policy or VenusaurPolicy()

    def save_step(self,enemy):
        signature=(enemy['uid'],enemy['hp'],enemy['status_code'],enemy.get('status3',0))
        if signature==self.saved_signature:return
        folder=self.g.root/'checkpoints/capture-current'
        (folder/'manifest.json').unlink(missing_ok=True)
        self.p.checkpoint('capture-current')
        write_json(folder/'manifest.json',{f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in folder.iterdir() if f.is_file() and f.name!='manifest.json'})
        self.data.update(step='checkpoints/capture-current',uid=enemy['uid']);write_json(self.journal,self.data)
        self.saved_signature=signature

    def rollback(self,reason):
        self.data['retries']=self.data.get('retries',0)+1;write_json(self.journal,self.data)
        if self.data['retries']>2000:raise AcquisitionAttention('Ловля на паузе после 2000 повторов; встреча сохранена')
        self.g.restore_checkpoint(self.before)
        self.pending=None;self.chosen=None
        self.p.advance(1+(self.data['retries']*37)%997)
        self.w.event('capture_retry',dict(reason=reason,retry=self.data['retries'],uid=self.data['uid']))
        self.w.safe_point()

    def throw_failed(self,state):return False

    def run(self):
        caught=False;target=None
        for _ in range(50000):
            s=self.p.state();c=s['controls'];b=s.get('battle')or{};enemies=b.get('enemies',[]);enemy=enemies[0] if enemies else None
            if b.get('outcome')==7:caught=True
            if self.pending and not caught and self.throw_failed(s):self.rollback('Pokémon вырвался');continue
            if self.pending and not caught and (b.get('outcome',0) not in (0,7) or enemy and enemy['hp']<=0):
                self.rollback('Цель потеряна или бой завершился');continue
            if not s['in_battle']:
                if c['callback']=='CB2_Overworld' and not c['field_locked']:
                    if not caught:raise AcquisitionAttention('Поимка не подтверждена; встреча сохранена')
                    self.p.checkpoint('capture-caught',permanent=True);self.p.persist()
                    self.data['caught']=True;write_json(self.journal,self.data);return True
                self.p.tap('B');continue
            if b.get('flags',0)&(1|8|128):raise AcquisitionAttention('Ловля поддерживает обычный одиночный дикий бой')
            tasks=self.p.tasks(s);controller=c['controllers'][0]
            current_balls={r['id']:r['quantity'] for r in read_player_inventory(self.g)['items'] if r['pocket']=='balls'} if self.pending and self.pending['action']=='throw' else {}
            ally=next(iter(b.get('allies',[])),{})
            executed=self.pending and (current_balls.get(self.pending.get('ball_id'),0)<self.pending.get('ball_count_before',0) if self.pending['action']=='throw' else any(m['id']==self.pending['move_id'] and m['current_pp']<self.pending['move_pp_before'] for m in ally.get('moves',[])))
            if self.pending and executed and controller=='HandleInputChooseAction' and c['callback']=='BattleMainCB2' and enemy:
                previous=self.pending;self.pending=None
                if previous['action']=='throw':self.rollback('Pokémon вырвался');continue
                success=bool(enemy['status_code']&7) if previous.get('move_id') in SLEEP_MOVES else bool(enemy.get('status3',0)&4)
                if not success:self.rollback('Приём не подействовал');continue
                self.w.event('capture_status_confirmed',dict(move_id=previous['move_id'],hp=enemy['hp'],status=enemy['status_code'],status3=enemy.get('status3',0)))
                self.saved_signature=None
            if c['callback'] in ('CB2_BagMenuRun','CB2_BagMenu') or any('BagMenu' in t or 'ItemContextMenu' in t for t in tasks):
                self.p.bag(self.chosen['ball_id']);continue
            if self.pending and controller in ('HandleInputChooseAction','HandleInputChooseMove'):
                # The controller name can outlive its input screen while a
                # transition animates. Do not replace the pre-action checkpoint.
                if self.g.frame-self.pending.get('started_frame',self.g.frame)>180 and controller=='HandleInputChooseAction':
                    self.rollback('Ход не подтвердился · повторяем с безопасной точки')
                else:self.p.advance(6)
                continue
            if controller=='HandleInputChooseAction' and enemy:
                if not enemy.get('identity_valid'):self.p.advance();continue
                if target is None:
                    target=enemy['uid'];name='encounter-'+target.replace(':','-')
                    self.p.checkpoint(name,permanent=True)
                    if self.data.get('uid')!=target:self.data=dict(uid=target,encounter='checkpoints/'+name,retries=0)
                    write_json(self.journal,self.data)
                    self.w.update(status='capturing',stage='Встреча сохранена · подбираем способ поимки',encounter_uid=target)
                if enemy['uid']!=target:raise AcquisitionAttention('Изменилась цель поимки')
                ally=next(iter(b.get('allies',[])),None)
                if not ally or ally['uid']!=self.p.capture_hunter:raise AcquisitionAttention('На поле должен быть выбранный охотник; встреча сохранена')
                self.save_step(enemy);self.w.safe_point();self.before=self.g.capture_save(metadata=False).state
                balls={r['id']:r['quantity'] for r in read_player_inventory(self.g)['items'] if r['pocket']=='balls'}
                decision=self.policy.decide(enemy,ally,balls,species(enemy['species_id'],self.g.root)['catch_rate'])
                if decision['action']=='attention':raise AcquisitionAttention(decision['reason'])
                self.chosen=decision
                self.w.event('capture_decision',dict(decision,enemy_uid=target,hp=enemy['hp'],status=enemy['status_code'],retry=self.data.get('retries',0)))
                self.w.update(status='capturing',stage=decision['reason'],capture_probability=decision.get('probability'))
                old_cursor=c['action_cursor'][0];desired=1 if decision['action']=='throw' else 0
                self.p.grid(old_cursor,desired)
                # grid() can first move the cursor; arm only once A was pressed.
                if old_cursor==desired and decision['action']=='throw':self.pending=dict(decision,ball_count_before=balls[decision['ball_id']],started_frame=self.g.frame)
                continue
            if controller=='HandleInputChooseMove':
                if not self.chosen or self.chosen['action']!='move':self.p.tap('B');continue
                ally=next(iter(b.get('allies',[])),{})
                index=next((i for i,m in enumerate(ally.get('moves',[])) if m['id']==self.chosen['move_id'] and m.get('current_pp',0)>0),None)
                if index is None:raise AcquisitionAttention('Нет PP выбранного приёма; встреча сохранена')
                old_cursor=c['move_cursor'][0];self.p.grid(old_cursor,index)
                if old_cursor==index:self.pending=dict(self.chosen,move_pp_before=ally['moves'][index]['current_pp'],started_frame=self.g.frame)
                continue
            self.p.tap('B',wait=18)
        raise AcquisitionAttention('Ловля приостановлена по лимиту действий; встреча сохранена')

def restore_capture(player):
    """Recover even if a process died between throwing and publishing Data."""
    data=read_json(player.g.root/'capture-session.json',{})
    if not data:
        config=getattr(player.w,'config',None)
        # A process may die after publishing the permanent encounter but before
        # its tiny journal. Discover that checkpoint rather than resume walking.
        for folder in sorted((player.g.root/'checkpoints').glob('encounter-*'),reverse=True):
            meta=read_json(folder/'metadata.json',{});enemies=(meta.get('state',{}).get('battle')or{}).get('enemies',[])
            enemy=next((m for m in enemies if config and m['species_id']==config.species_id and (not config.shiny or m['shiny'])),None)
            if enemy:
                data=dict(uid=enemy['uid'],encounter=str(folder.relative_to(player.g.root)),retries=0)
                write_json(player.g.root/'capture-session.json',data);break
    if not data or data.get('caught'):return
    candidates=['checkpoints/capture-current',data.get('encounter','')]
    for relative in candidates:
        if not relative or relative.startswith('/') or '..' in relative.split('/'):continue
        folder=player.g.root/relative;manifest=read_json(folder/'manifest.json',{})
        if not {'FireRed.state','FireRed.sav'}<=manifest.keys():continue
        try:
            valid=all('/' not in n and n not in ('.','..') and hashlib.sha256((folder/n).read_bytes()).hexdigest()==h for n,h in manifest.items())
        except OSError:valid=False
        if valid:
            player.g.load_state(folder/'FireRed.state');player.persist();return
    raise AcquisitionAttention('Не удалось проверить сохранённую встречу; файлы оставлены')
