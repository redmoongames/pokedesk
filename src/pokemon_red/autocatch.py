"""Filtered local capture using ordinary movement, durable encounters and retries."""
from .capture_target import CaptureTarget
from .hunt_planning import HuntPlanner
from .hunt_spots import hunting_spot
from .telemetry import read_map,read_field_badges
from .field_tools import party_cut
from .models import read_inventory
from .acquisition_play import AcquisitionAttention
from .player_inventory import read_player_inventory
from .acquisition import read_json,write_json


def verified_enemy(state):
    battle=state.get('battle')or{}
    if battle.get('flags',0)&(1|2|8|0x40|0x80|0x200):raise AcquisitionAttention('Автопоимка поддерживает обычные одиночные дикие бои')
    live=next(iter(battle.get('enemies',[])),None)
    if not live or not live.get('identity_valid'):return None
    canonical=next((m for m in battle.get('enemy_party',[]) if m.get('checksum_valid') and m.get('uid')==live.get('uid') and m.get('slot')==live.get('party_slot')),None)
    return canonical


def prepare_hunt(player,config):
    p=player;g=p.g;w=p.w;root=g.root;target=CaptureTarget.parse(config,root);inventory=read_inventory(g);inventory['field_badges']=read_field_badges(g);inventory['bag']=read_player_inventory(g)
    if not any(r['id'] in (2,3,4) and r['quantity']>0 for r in read_player_inventory(g)['items']):raise AcquisitionAttention('Нужны Poké Ball, Great Ball или Ultra Ball. Master Ball автоматически не используется.')
    initial={m['uid'] for m in inventory['party']+inventory['boxes']};planner=HuntPlanner(p,inventory);selected=planner.choose(target)
    hunter=selected['hunter_uid'];p.capture_policy='venusaur';p.capture_hunter=hunter
    from .move_plan import compile_plan
    from .learning import LearningRuntime
    hunter_mon=next(m for m in inventory['party']+inventory['boxes'] if m['uid']==hunter)
    kit=compile_plan(hunter_mon,100,[m['id'] for m in hunter_mon['moves']],root,mode='stay')
    p.learning=LearningRuntime(kit,event=w.event,checkpoint=lambda _:p.checkpoint('hunter-learning'),suspend=lambda:None)
    w.event('autocatch_plan',dict(target=target.as_dict(),map=selected['map'],pair=selected['farm']['pair'],hunter_uid=hunter,clinic=selected['clinic']))
    w.update(stage='Подготовка автопоимки · '+selected['label'],target=target.as_dict(),route=selected['map'])
    if not p.state()['in_battle']:
        if not selected['local']:
            p.nav.configure_tools(inventory);p.nav.travel_prepared(selected['map'],pinned=selected['pinned'],preferred=selected['preferred'])
        p.lead(hunter)
    return dict(selected=selected,initial=list(initial),hunter=hunter)


def run_autocatch(player,config,*,prepared=None):
    p=player;g=p.g;w=p.w;root=g.root;target=CaptureTarget.parse(config,root)
    context=prepared or prepare_hunt(p,config);selected=context['selected'];initial=set(context['initial']);hunter=context['hunter']
    p.capture_policy='venusaur';p.capture_hunter=hunter
    if prepared:
        from .move_plan import compile_plan
        from .learning import LearningRuntime
        inventory=read_inventory(g);hunter_mon=next(m for m in inventory['party']+inventory['boxes'] if m['uid']==hunter)
        p.learning=LearningRuntime(compile_plan(hunter_mon,100,[m['id'] for m in hunter_mon['moves']],root,mode='stay'),event=w.event,checkpoint=lambda _:p.checkpoint('hunter-learning'),suspend=lambda:None)
    method=selected['method'];water=method!='land_mons'
    from .water_hunting import RODS,water_spot,surfing,leave_water,board,swim_step,water_path,face,cast,approach_shore
    attempts=0;checked=set();farm=None;casts=0
    for _ in range(250000):
        state=p.state();controls=state['controls']
        if state['in_battle']:
            if controls['controllers'][0]!='HandleInputChooseAction':
                p.tap('B' if controls['controllers'][0]=='HandleInputChooseMove' else 'A');continue
            enemy=verified_enemy(state)
            if enemy is None:p.advance(6);continue
            wanted=target.should_capture(enemy,root)
            if enemy['uid'] not in checked:
                attempts+=1
                if len(checked)>=64:checked.clear()
                checked.add(enemy['uid'])
                observer=getattr(w,'candidate',None)
                if observer:observer(target,enemy)
                w.update(encounters=attempts,stage=f'Ищем подходящего Pokémon · встреч {attempts}',last_candidate=dict(species_id=enemy['species_id'],level=enemy['level'],ivs=enemy['ivs'],shiny=enemy['shiny']))
            if wanted:
                p.checkpoint('encounter-'+enemy['uid'].replace(':','-'),permanent=True)
                w.update(stage='Подходящий Pokémon найден · встреча сохранена',status='capturing')
                p.battle('catch');after=read_inventory(g)
                mon=next((m for m in after['party']+after['boxes'] if m['uid']==enemy['uid'] and m['uid'] not in initial),None)
                if not mon or not target.matches(mon,root):raise AcquisitionAttention('Не подтверждены все параметры пойманного Pokémon; встреча сохранена')
                w.verified_catch=mon
                p.checkpoint('caught-'+mon['uid'].replace(':','-'),permanent=True);p.persist()
                w.event('autocatch_caught',dict(pokemon=mon,target=target.as_dict(),encounters=attempts));return mon
            p.battle('escape');w.safe_point();continue
        from .telemetry import read_walk_state
        if read_walk_state(g).get('battle_pending'):p.advance(1);continue
        if controls['field_locked'] or controls['callback']!='CB2_Overworld':raise AcquisitionAttention('На пути появился диалог или сюжетное событие')
        if state['map']['name']!=selected['map']:raise AcquisitionAttention('Изменилась карта охоты; остановитесь и выберите локацию заново')
        owned=next((m for m in state['party'] if m['uid']==hunter),None)
        if not owned:raise AcquisitionAttention('Выбранный Pokémon для ловли отсутствует в команде')
        sleep=next((m['current_pp'] for m in owned['moves'] if m['id']==79),None)
        if owned['hp']<owned['max_hp']*.65 or owned.get('status_code') or sleep is not None and sleep<3:
            if water and farm is not None:
                if not leave_water(p,farm):continue
            if selected.get('manual_heal'):
                p.save_game();raise AcquisitionAttention('Ресурсы охотника заканчиваются. Остановились на берегу; для этой локации лечение нужно выполнить вручную.')
            w.update(stage='Восстанавливаем HP и PP в Pokémon Center')
            p.center();p.lead(hunter);p.nav.travel(selected['map']);farm=None
        grid=party_cut(read_map(g),p.state()['party']);position=p.state()['position'];point=(position['x'],position['y'])
        # Do not re-plan a whole map per frame or per step. Revalidate the chosen
        # path in Journey.go(); rebuild the hunting area only after a heal/map trip.
        if farm is None:farm=water_spot(grid,point,method) if water else hunting_spot(root,grid,point)
        p.lead(hunter)
        if water:
            if method in RODS:
                if surfing(g):
                    if not leave_water(p,farm):continue
                if not approach_shore(p,farm):continue
                if not face(p,tuple(farm['shore']),tuple(farm['entry'])):continue
                casts+=1;w.update(stage='Рыбалка · '+{'old_rod':'Old Rod','good_rod':'Good Rod','super_rod':'Super Rod'}[method]+f' · заброс {casts}',casts=casts)
                cast(p,method)
            else:
                if not surfing(g):
                    if not approach_shore(p,farm):continue
                    board(p,farm)
                if p.state()['in_battle']:continue
                here=p.state()['position'];here=(here['x'],here['y']);a,b=map(tuple,farm['pair']);goal=b if here==a else a
                for step in water_path(read_map(g),here,goal):
                    if not swim_step(p,step):break
            w.safe_point();continue
        a,b=map(tuple,farm['pair']);p.go(b if point==a else a,encounters='local');w.safe_point()
    raise AcquisitionAttention('Поиск приостановлен по лимиту шагов. Прогресс сохранён.')
