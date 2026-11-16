"""Guarded encounter sampling from an immutable, all-grass frontier.

This is speculative search on private cores. Rejected branches are restored,
never merged into the player's session. RNG and Pokémon memory are read-only.
Ordinary walking generates each opponent; only battle presentation is skipped.
"""
from .acquisition_play import AcquisitionAttention
from .movement import WalkSegment,straight_path,safe_segment,movement_mode
from .telemetry import read_walk_state,symbols,read_controls
from .models import decode_mon
from .i18n import t


def grass_corridor(grid,pair):
    a,b=map(tuple,pair);line=straight_path(a,b)
    if not line or any(not grid['tiles'][y][x][3] for x,y in [a,*line]):return False
    if len(line)==1:
        from .movement import safe_step,corridor_hazards
        return a not in corridor_hazards(grid) and b not in corridor_hazards(grid) and safe_step(grid,a,b) and safe_step(grid,b,a)
    return safe_segment(grid,a,line,search=True)==line and safe_segment(grid,b,straight_path(b,a),search=True)==straight_path(b,a)


def prepare_grass(player,selected,*,movement="auto",expected_encounters=None,workers=1):
    """Enter and settle inside the verified strip before any worker is forked."""
    from .hunt_spots import hunting_spot
    from .telemetry import read_map
    from .field_tools import party_cut
    state=player.state();hunter=next((m for m in state['party'] if m['uid']==player.capture_hunter),None)
    if hunter and (hunter['hp']<hunter['max_hp']*.65 or hunter.get('status_code') or any(m['id']==79 and m['current_pp']<3 for m in hunter['moves'])):
        if selected.get('manual_heal'):raise AcquisitionAttention(t('capture.search_frontier_changed'))
        player.center();player.lead(hunter['uid']);player.nav.travel(selected['map'])
    farm=None
    for _ in range(64):
        walk=read_walk_state(player.g)
        if walk['in_battle'] or walk['battle_pending']:
            # The normal executor protects unexpected shinies and trainer fights.
            from .autocatch import verified_enemy
            settle_encounter(player)
            enemy=verified_enemy(player.state())
            if not enemy:raise AcquisitionAttention(t('capture.search_approach_encounter'))
            player.battle('escape');continue
        if walk['map']!=selected['map'] or not walk['open']:raise AcquisitionAttention(t('capture.search_approach_event'))
        grid=party_cut(read_map(player.g),player.state()['party'])
        if farm is None:farm=hunting_spot(player.g.root,grid,tuple(walk['position']))
        if not grass_corridor(grid,farm['pair']):
            from .navigation import safe_grass_pair
            farm=safe_grass_pair(grid,tuple(walk['position']),terrain=farm.get('terrain','grass'))
        if not grass_corridor(grid,farm['pair']):raise AcquisitionAttention(t('capture.search_no_grass_strip'))
        a,b=map(tuple,farm['pair'])
        if tuple(walk['position'])==a and not walk['moving']:
            from .search_transport import capabilities,choose_transport,set_bicycle
            available=capabilities(player.g);mode=choose_transport(available,len(straight_path(a,b)),movement,expected_encounters=expected_encounters,workers=workers)
            set_bicycle(player,mode=='bike')
            player.w.update(search_transport=mode)
            player.w.event('wild_search_frontier',dict(map=selected['map'],pair=[a,b],all_encounter_tiles=True,position=a,movement=mode,capabilities=available,expected_encounters=expected_encounters,workers=workers))
            return dict(farm,pair=[list(a),list(b)],movement=mode)
        player.go(a,encounters='local')
    raise AcquisitionAttention(t('capture.search_grass_entry_failed'))


def generated_enemy(game,walk,previous):
    """Only a newly generated canonical opponent in a fresh battle transition.

    gEnemyPartyCount stays zero in FireRed wild battles. Never interpret that
    counter or stale gBattleMons as a new encounter. The ordinary battle task
    appears after CreateWildMon has populated the canonical enemy party.
    """
    if not (walk.get('battle_pending') or walk.get('in_battle')):return None
    s=symbols(game.root)
    if game.read32(s['gBattleTypeFlags']) & ~0x24:raise AcquisitionAttention(t('capture.search_unsupported_battle'))
    raw=game.read_bytes(s['gEnemyParty'],100)
    if raw==previous:return None
    mon=decode_mon(raw,game.root)
    if not mon['checksum_valid'] or not mon['species_id'] or mon['is_egg'] or not 1<=mon['level']<=100:return None
    return mon


def settle_encounter(player,uid=None):
    """Reach a verified battle menu without answering choices or taking a turn."""
    from .autocatch import verified_enemy
    s=symbols(player.g.root)
    for frame in range(2400):
        player.w.safe_point()
        if player.g.read32(s['gBattleTypeFlags']) & ~0x24:raise AcquisitionAttention(t('capture.search_battle_changed'))
        c=read_controls(player.g)
        if c['callback']=='BattleMainCB2' and c['controllers'][0]=='HandleInputChooseAction':
            enemy=verified_enemy(player.state())
            if enemy and (uid is None or enemy['uid']==uid):return enemy
            raise AcquisitionAttention(t('capture.search_enemy_changed'))
        # Only the battle intro may acknowledge text. Re-sample before every
        # frame and stop before ChooseAction can receive the next held A.
        if c['callback']=='BattleMainCB2':
            if c['controllers'][0] in ('HandleInputChooseMove','HandleInputChooseItem','HandleInputChoosePokemon'):
                raise AcquisitionAttention(t('capture.search_battle_menu_changed'))
            from .engine import BUTTONS
            mask=BUTTONS['A'] if frame%20<2 else 0
        else:mask=0
        player.advance(1,mask)
    raise AcquisitionAttention(t('capture.search_battle_menu_timeout'))


def sample_grass(player,config,prepared):
    """Rolling idle frontier, disjoint frame residues per lane, guarded walking."""
    from .capture_target import CaptureTarget
    from .autocatch import run_autocatch
    g=player.g;w=player.w;target=CaptureTarget.parse(config,g.root)
    farm=prepared['grass_frontier'];a,b=map(tuple,farm['pair']);name=prepared['selected']['map']
    walk=read_walk_state(g)
    if walk['map']!=name or tuple(walk['position'])!=a or not walk['open'] or walk['moving']:raise AcquisitionAttention(t('capture.search_frontier_changed'))
    # Navigation/capture remain paced. Only private speculative sampling is free.
    w.searching=True;player.learning=None
    stride=17*target.search_workers;lane=w.request['lane']
    player.advance(17*(lane+1));w.resume_snapshot=g.capture_save(metadata=False);frontier=w.resume_snapshot.state
    for _ in range(1000000):
        w.safe_point();walk=read_walk_state(g);previous=g.read_bytes(symbols(g.root)['gEnemyParty'],100);enemy=None
        # A low-rate map may need several traversals. Input is released at every
        # endpoint, not every tile, with the same per-frame movement guards.
        for _ in range(64):
            start=tuple(walk['position']);goal=b if start==a else a
            segment=WalkSegment(name,start,goal,g.frame,mode=farm.get('movement') or movement_mode(walk,len(straight_path(start,goal))),precision=len(straight_path(start,goal))==1)
            for _ in range(len(segment.path)*40+121):
                walk=read_walk_state(g);mask,result=segment.next(walk)
                enemy=generated_enemy(g,walk,previous)
                if enemy:break
                if result:
                    if result['reason']=='reached':break
                    if result['reason']=='battle':
                        player.advance(1);continue
                    raise AcquisitionAttention(t('capture.search_corridor_interrupted',reason=result['reason']))
                player.advance(1,mask)
            else:raise AcquisitionAttention(t('capture.search_corridor_timeout'))
            g.advance(0,0)
            if enemy:break
            walk=read_walk_state(g)
        if enemy is None:raise AcquisitionAttention(t('capture.search_no_encounter'))
        w.candidate(target,enemy);w.current_encounter_uid=enemy['uid']
        wanted=target.should_capture(enemy,g.root)
        if wanted:
            w.searching=False;w.reset_pacing();settle_encounter(player,enemy['uid'])
            return run_autocatch(player,config,prepared=prepared)
        # A neutral idle stride changes normal game RNG. It never edits RNG,
        # species, IVs or encounter tables and does not accumulate replay work.
        w.safe_point();g.restore_checkpoint(frontier);player.advance(stride)
        walk=read_walk_state(g)
        if not walk['open'] or walk['moving'] or walk['map']!=name or tuple(walk['position'])!=a:raise AcquisitionAttention(t('capture.search_idle_interrupted'))
        w.resume_snapshot=g.capture_save(metadata=False);frontier=w.resume_snapshot.state
    raise AcquisitionAttention(t('capture.search_attempt_limit'))
