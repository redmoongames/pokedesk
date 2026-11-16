"""Stable configuration and provenance for reproducible training measurements."""
from dataclasses import dataclass,asdict
from functools import lru_cache
from pathlib import Path
import hashlib
import json
import re
from .i18n import t

CONTEXT_SCHEMA=2
POLICY_VERSION='survival-training-tactics-v4'

def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()[:24]

@dataclass(frozen=True)
class RunConfig:
    route:str='Route1'
    strategy:str='adaptive'
    trainee:str=''
    target:int=15
    heal_percent:int=40
    target_ohko_threshold:float=.9
    final_moves:tuple|None=None
    evolution_mode:str='natural'
    approved_plan_id:str|None=None
    allow_two_hits:bool=True
    auto_speed:bool=False
    max_auto_speed:int=12
    training_policy:str='coverage'
    training_approach:str='legacy'
    equip_lucky_egg:bool=True
    main_coverage:float=.9
    minimum_coverage:float=.5

    @classmethod
    def parse(cls,data):
        moves=data.get('final_moves')
        if moves is not None and (not isinstance(moves,(list,tuple)) or not 1<=len(moves)<=4 or any(type(n) is not int or not 1<=n<=354 for n in moves) or len(set(moves))!=len(moves)):raise ValueError('Выбери до четырёх разных приёмов')
        value=cls(route=str(data.get('route','Route1')),strategy=str(data.get('strategy','adaptive')),trainee=str(data.get('trainee','')),target=int(data.get('target',15)),heal_percent=int(data.get('heal_percent',40)),target_ohko_threshold=float(data.get('target_ohko_threshold',.9)),final_moves=tuple(moves) if moves is not None else None,evolution_mode=str(data.get('evolution_mode','natural')),approved_plan_id=data.get('approved_plan_id'),allow_two_hits=data.get('allow_two_hits',True),auto_speed=data.get('auto_speed',False),max_auto_speed=data.get('max_auto_speed',12),training_policy=str(data.get('training_policy','coverage')),training_approach=str(data.get('training_approach','legacy')),equip_lucky_egg=data.get('equip_lucky_egg',True),main_coverage=float(data.get('main_coverage',.9)),minimum_coverage=float(data.get('minimum_coverage',.5)))
        if value.training_approach not in ('legacy','auto','careful','mentor','fast','local') or type(value.equip_lucky_egg) is not bool:raise ValueError(t('training.invalid_approach'))
        if type(value.allow_two_hits) is not bool:raise ValueError('Два удара: требуется галочка')
        from .automatic_speed import speed_cap
        speed_cap(value.max_auto_speed)
        if type(value.auto_speed) is not bool:raise ValueError('Управлять скоростью: требуется галочка')
        if not 2<=value.target<=100:raise ValueError('Целевой уровень: 2–100')
        if not 20<=value.heal_percent<=80:raise ValueError('Порог лечения: 20–80% HP')
        if not 0<=value.target_ohko_threshold<=1:raise ValueError('Шанс KO должен быть от 0 до 1')
        if value.strategy not in ('adaptive','switch','solo'):raise ValueError('Неизвестная стратегия')
        if value.evolution_mode not in ('natural','stay') and not re.fullmatch(r'stop_at:[1-9][0-9]{0,2}',value.evolution_mode):raise ValueError('Неизвестный режим эволюции')
        if value.approved_plan_id is not None and (not isinstance(value.approved_plan_id,str) or not re.fullmatch('[0-9a-f]{24}',value.approved_plan_id)):raise ValueError('Некорректное подтверждение плана')
        if value.training_policy not in ('coverage','eta'):raise ValueError('Неизвестная политика маршрута')
        if not 0<=value.minimum_coverage<=value.main_coverage<=1:raise ValueError('Некорректные пороги покрытия встреч')
        return value

    def as_dict(self):return asdict(self)
    def rules(self):return dict(training_approach=self.training_approach,equip_lucky_egg=self.equip_lucky_egg,learner_coverage=.8,allow_two_hits=self.allow_two_hits,auto_speed=self.auto_speed,max_auto_speed=self.max_auto_speed,strategy=self.strategy,heal_percent=self.heal_percent,target_ohko_threshold=self.target_ohko_threshold,final_moves=list(self.final_moves) if self.final_moves else None,evolution_mode=self.evolution_mode,training_policy=self.training_policy,main_coverage=self.main_coverage,minimum_coverage=self.minimum_coverage)

def team_snapshot(team):
    return [dict(uid=m['uid'],nickname=m.get('nickname',''),species_id=m['species_id'],level=m['level'],max_hp=m.get('max_hp'),ability_id=m.get('ability_id'),held_item=m.get('held_item',0),friendship=m.get('friendship',70),traded=bool(m.get('traded',False)),nature=m.get('nature'),stats=m.get('stats'),ivs=m.get('ivs'),evs=m.get('evs'),moves=[{k:a.get(k) for k in ('id','name','max_pp','pp')} for a in m.get('moves',[])]) for m in sorted(team,key=lambda m:m['uid'])]

def team_fingerprint(team):
    # Nicknames and translations do not affect a battle or XP split.
    rows=team_snapshot(team)
    for m in rows:
        m.pop('nickname',None)
        # Keep full EV/IV/nature in the snapshot, but compare effective stats.
        # EV gain on every battle must not split otherwise identical cycles.
        for key in ('evs','ivs','nature'):m.pop(key,None)
        if not any(a['id'] in (216,218) for a in m['moves']):m.pop('friendship',None)
        for a in m['moves']:a.pop('name',None)
    return digest(rows)

def planning_key(inventory,config):
    owned=inventory.get('party',[])+inventory.get('boxes',[])
    from .optimizer import world_key
    return digest([RunConfig.parse(config).as_dict(),team_fingerprint(owned),[(m['uid'],m.get('location'),m.get('box'),m.get('box_slot'),m.get('checksum_valid'),m.get('is_egg')) for m in owned],world_key(inventory['_planning']) if '_planning' in inventory else None,inventory.get('field_badges',[])])

@lru_cache(maxsize=8)
def versions(root):
    root=Path(root)
    from .paths import installation_root
    base=installation_root(root)
    def files_hash(paths):
        h=hashlib.sha256()
        for path in paths:
            f=base/path;h.update(path.encode());h.update(f.read_bytes() if f.exists() else b'missing')
        return h.hexdigest()
    result=dict(runtime=files_hash(['src/pokemon_red/installation_versions.py','src/pokemon_red/cli.py','src/pokemon_red/bot_runner.py','src/pokemon_red/paths.py','src/pokemon_red/reference_pack.py','src/pokemon_red/database.py','src/pokemon_red/analytics.py','src/pokemon_red/analytics_worker.py','src/pokemon_red/history_queries.py','src/pokemon_red/runtime_data.py','src/pokemon_red/models.py','src/pokemon_red/healing.py','src/pokemon_red/acquisition_play.py','src/pokemon_red/journey.py','src/pokemon_red/party_management.py','src/pokemon_red/party_worker.py','src/pokemon_red/workspace.py','src/pokemon_red/trainer_navigation.py','src/pokemon_red/catch_preferences_ui.py','src/pokemon_red/catch_preferences.py','src/pokemon_red/search_budget.py','src/pokemon_red/catch_lifecycle.py','src/pokemon_red/wild_search_history.py','src/pokemon_red/iv_preferences.py','src/pokemon_red/iv_preferences_ui.py','src/pokemon_red/search_candidates.py','src/pokemon_red/search_processes.py','src/pokemon_red/wild_search.py','src/pokemon_red/grass_search.py','src/pokemon_red/search_transport.py','src/pokemon_red/field_item_menu.py','src/pokemon_red/wild_search_worker.py','src/pokemon_red/worker_pacing.py','src/pokemon_red/speeds.py','src/pokemon_red/automatic_speed.py','src/pokemon_red/run_context.py','src/pokemon_red/engine.py','src/pokemon_red/gui.py','src/pokemon_red/ai_overlay.py','src/pokemon_red/prologue.py','src/pokemon_red/new_game_config.py','src/pokemon_red/search_odds.py','src/pokemon_red/nature_preferences.py','src/pokemon_red/starter_checkpoint.py','src/pokemon_red/starter_candidates.py','src/pokemon_red/automation_context.py','src/pokemon_red/starter_search.py','src/pokemon_red/starter_search_worker.py','src/pokemon_red/capture_target.py','src/pokemon_red/operations.py','src/pokemon_red/operation_worker.py','src/pokemon_red/engine_runtime.py','src/pokemon_red/scheduling.py','src/pokemon_red/manual_battle.py','src/pokemon_red/telemetry.py','src/pokemon_red/battle_fighter.py','src/pokemon_red/battle_strategy.py','src/pokemon_red/history.py','src/pokemon_red/journal_store.py','src/pokemon_red/session_controller.py','src/pokemon_red/runtime_views.py','src/pokemon_red/encounter_safety.py','src/pokemon_red/event_loop.py','src/pokemon_red/file_writer.py','src/pokemon_red/persistence.py','src/pokemon_red/bot.py','src/pokemon_red/slots.py']),rom='dd5945db9b930750cb39d00c84da8571feebf417',core=files_hash(['native/mgba_libretro.dylib','native/libpokemon.dylib']),catalog=files_hash(['vendor/catalog/firered.json','vendor/reference/battle_move_effects.h']),encounters=files_hash(['vendor/reference/grind_routes.json']),navigation=files_hash(['vendor/reference/grind_zones.json','src/pokemon_red/navigation.py','src/pokemon_red/planning_state.py','src/pokemon_red/path_cache.py','src/pokemon_red/training_tactics.py','src/pokemon_red/training_item.py','src/pokemon_red/training.py','src/pokemon_red/walking_route.py','src/pokemon_red/portal_graph.py','src/pokemon_red/travel_plan.py','src/pokemon_red/travel.py','src/pokemon_red/travel_policy.py','src/pokemon_red/field_tools.py','src/pokemon_red/movement.py','src/pokemon_red/telemetry.py','src/pokemon_red/storage.py']),policy=files_hash(['src/pokemon_red/healing.py','src/pokemon_red/acquisition_play.py','src/pokemon_red/journey.py','src/pokemon_red/planning.py','src/pokemon_red/optimizer.py','src/pokemon_red/prepared_plan.py','src/pokemon_red/grind.py','src/pokemon_red/training_tactics.py','src/pokemon_red/training_item.py','src/pokemon_red/training.py','src/pokemon_red/mechanics.py','src/pokemon_red/rules.py','src/pokemon_red/automation.py','src/pokemon_red/move_plan.py','src/pokemon_red/learning.py','src/pokemon_red/field_tools.py','src/pokemon_red/field_actions.py','src/pokemon_red/coverage.py','src/pokemon_red/combat_policy.py','src/pokemon_red/battle_fighter.py','src/pokemon_red/battle_strategy.py','src/pokemon_red/route_profiles.py','src/pokemon_red/battle_conditions.py','src/pokemon_red/field_teleport.py','src/pokemon_red/field_recovery.py','vendor/reference/heal_locations.json']),policy_name=POLICY_VERSION)

    from .editions import edition,reference_path,catalog_path
    from .game_adapters import capability_summary
    result.update(rom=edition(root).sha1,game=edition(root).id,adapter=capability_summary(root),
        adapter_version=files_hash(['src/pokemon_red/game_adapters.py','src/pokemon_red/game_layout.py','src/pokemon_red/hoenn.py','src/pokemon_red/field_rules.py','src/pokemon_red/trade_adapters.py']),
        catalog=files_hash([str(catalog_path(root).relative_to(base)),'vendor/reference/battle_move_effects.h']),
        encounters=files_hash([str(reference_path(root,'grind_routes.json').relative_to(base))]))
    result['navigation']=digest([result['navigation'],files_hash([str(reference_path(root,'grind_zones.json').relative_to(base))])])
    from .installation_versions import loaded_id
    result['installation_version']=loaded_id() or 'development'
    return result


def build_context(root,config,plan):
    effective=dict(config)
    if effective.get('training_approach','legacy')!='legacy' and plan.get('effective_policy'):effective['training_policy']=plan['effective_policy']
    cfg=RunConfig.parse(effective)
    return dict(schema=CONTEXT_SCHEMA,complete=True,config=cfg.as_dict(),rules=cfg.rules(),versions=versions(root),roles=dict(trainee=plan['trainee'],runner=plan['runner'],fighters=sorted(plan['fighters']),utilities=sorted(plan.get('utility_uids',[])),field_tools=sorted(plan.get('field_tools',[])),training_mode=plan.get('training_mode'),primary_mentor=plan.get('primary_mentor'),learner_max_hits=plan.get('learner_max_hits')))

def context_complete(context):
    return isinstance(context,dict) and context.get('schema')==CONTEXT_SCHEMA and bool(context.get('complete')) and all(context.get(k) for k in ('config','rules','versions','roles'))

def comparison_key(team_hash,context,clinic,area,legacy_run=''):
    if context_complete(context):return digest([CONTEXT_SCHEMA,team_hash,context['rules'],context['versions'],context['roles'],clinic,area])
    return 'legacy:'+digest([legacy_run,team_hash,clinic,area])
