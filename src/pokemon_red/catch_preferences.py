"""Wild-catch priorities: IV utility, independent hard minima and nature policy.

Starter ranking deliberately keeps its existing capped-goal scoring. Here every
IV contributes to quality even after a requested minimum has been reached.
"""
from .models import STAT_KEYS
from .natures import nature_effect
from .i18n import t

ROLES=('positive','neutral','negative')
WEIGHTS={'positive':2,'neutral':1,'negative':.5}

def normalize_preferences(value):
    if isinstance(value,dict) and set(value)==set(STAT_KEYS):value=tuple(value[k] for k in STAT_KEYS)
    if not isinstance(value,(tuple,list)) or len(value)!=6 or any(type(v) is not str or v not in ROLES for v in value):
        raise ValueError(t('capture.invalid_stat_preferences'))
    return tuple(value)

def accepted_natures(preferences):
    roles=dict(zip(STAT_KEYS,normalize_preferences(preferences)))
    positive={k for k,v in roles.items() if k!='hp' and v=='positive'}
    negative={k for k,v in roles.items() if k!='hp' and v=='negative'}
    result=[];neutral=[]
    for number in range(25):
        effect=nature_effect(number)['modifiers']
        if not effect:neutral.append(number);continue
        boost=next(k for k,v in effect.items() if v>0);drop=next(k for k,v in effect.items() if v<0)
        if roles[boost]=='negative' or roles[drop]=='positive':continue
        if positive and boost not in positive or negative and drop not in negative:continue
        result.append(number)
    # All-neutral priorities accept all natures. If every change would hurt the
    # requested priorities, accept the five neutral natures instead of deadlock.
    return tuple(sorted(result+neutral if not positive and not negative else result or neutral))

def score(values,preferences,minimums,*,exact=False):
    if not isinstance(values,dict) or any(type(values.get(k)) is not int or not 0<=values[k]<=31 for k in STAT_KEYS):return None
    roles=normalize_preferences(preferences)
    missing=[dict(kind='iv',stat=k,actual=values[k],required=n) for k,n in zip(STAT_KEYS,minimums) if exact and values[k]<n]
    def number(value):return int(value) if value==int(value) else value
    points=number(sum(values[k]*WEIGHTS[r] for k,r in zip(STAT_KEYS,roles)))
    maximum=number(31*sum(WEIGHTS[r] for r in roles))
    return dict(rank=([int(not missing),points] if exact else [points]),score=points,target_score=maximum,
                iv_passed=6-len(missing),missing=missing,
                priority_ivs=[k for k,r in zip(STAT_KEYS,roles) if r=='positive'],
                negative_ivs=[k for k,r in zip(STAT_KEYS,roles) if r=='negative'],
                stat_preferences=dict(zip(STAT_KEYS,roles)))
