"""Explicit units for estimated filter odds and the exact Gen III throw model.

IV/PID products are a planning estimate: the game's deterministic RNG introduces
correlations. Encounter shares are conditional on an encounter, never per step.
"""
from math import prod,log1p,ceil,isfinite
from .capture import catch_probability
from .i18n import t,format_number

def nature_ids(values=(),legacy=None):
    if not isinstance(values,(list,tuple)) or any(type(n) is not int or not 0<=n<25 for n in values):raise ValueError(t('odds.invalid_natures'))
    if legacy is not None and (type(legacy) is not int or not 0<=legacy<25):raise ValueError(t('odds.invalid_natures'))
    return tuple(sorted(set(values))) if values else (() if legacy is None else (legacy,))

def gender_chance(gender,ratio):
    if gender=='any':return 1.
    if ratio==255:return float(gender=='genderless')
    if ratio==254:return float(gender=='female')
    if ratio==0:return float(gender=='male')
    return ratio/256 if gender=='female' else (256-ratio)/256 if gender=='male' else 0.

def estimate(min_ivs,*,gender='any',ratio=31,natures=(),shiny=False,exclude_shiny=False,encounter=1.,throw=1.):
    iv=prod((32-v)/32 for v in min_ivs);sex=gender_chance(gender,ratio)
    nature=len(set(natures))/25 if natures else 1.
    rare=1/8192 if shiny else 8191/8192 if exclude_shiny else 1.
    filters=iv*sex*nature*rare;target=encounter*filters;captured=target*throw
    return dict(iv=iv,gender=sex,nature=nature,shiny=rare,filters=filters,encounter=encounter,throw=throw,target=target,captured=captured,
        expected_candidates=1/filters if filters else None,expected_encounters=1/target if target else None)

def starter_odds(config):return estimate(config.min_ivs,gender=config.gender,ratio=31,natures=nature_ids(config.natures,config.nature),shiny=config.shiny)

def wild_odds(target,root,*,encounter=1.,ball_id=4):
    from .capture_target import hunt_atlas
    from .catalog import species
    ratio=hunt_atlas(root)['species'][str(target.species_id)]['gender_ratio'];info=species(target.species_id,root)
    throw=catch_probability(info['catch_rate'],100,100,ball_id=ball_id)['probability']
    return estimate(target.required_ivs,gender=target.gender,ratio=ratio,natures=target.natures,shiny=target.shiny,exclude_shiny=not target.shiny,encounter=encounter,throw=throw)

def percent(value):
    if value and value<1e-8:return f'{value*100:.3g}%'
    decimals=2 if value>=.01 else 4 if value>=.000001 else 6
    return format_number(value*100,decimals=decimals)+'%'

def summary(odds,*,starter=False,location=False):
    factors=t('odds.factors',ivs=percent(odds['iv']),gender=percent(odds['gender']),nature=percent(odds['nature']),shiny=percent(odds['shiny']))
    if starter:
        text=t('odds.starter',chance=percent(odds['filters']),count=format_number(round(odds['expected_candidates'] or 0)))
    elif location:
        text=t('odds.wild',encounter=percent(odds['encounter']),filters=percent(odds['filters']),target=percent(odds['target']),throw=percent(odds['throw']),combined=percent(odds['captured']))
    else:text=t('odds.filters_only',chance=percent(odds['filters']))
    return text+'\n'+factors+'\n'+t('odds.approximation')


def trial_estimate(chance):
    """Geometric estimate for independent attempts; not a guaranteed deadline."""
    if not isinstance(chance,(int,float)) or not isfinite(chance) or not 0<=chance<=1:raise ValueError('Invalid attempt probability')
    if chance==0:return dict(mean=None,median=None,p90=None,p95=None)
    def quantile(q):return 1 if chance==1 else max(1,ceil(log1p(-q)/log1p(-chance)))
    return dict(mean=1/chance,median=quantile(.5),p90=quantile(.9),p95=quantile(.95))

def count_label(value):
    return '—' if value is None else format_number(round(value))

def hunt_estimates(odds):
    encounters=trial_estimate(odds['target']);throws=trial_estimate(odds['throw'])
    return dict(encounters=encounters,throws=throws,text=t('capture.estimates',mean=count_label(encounters['mean']),p90=count_label(encounters['p90']),throws='—' if throws['mean'] is None else format_number(throws['mean'],decimals=1)))
