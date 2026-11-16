"""Pure IV preferences shared by starter and ordinary wild search."""
from .models import STAT_KEYS
from .i18n import t


def priorities(values=()):
    if not isinstance(values,(tuple,list)) or any(not isinstance(k,str) or k not in STAT_KEYS for k in values) or len(set(values))!=len(values):
        raise ValueError(t('capture.invalid_priorities'))
    return tuple(k for k in STAT_KEYS if k in values)


def score_ivs(values,minimums,preferred=()):
    """Cap at requested goals; surplus in one stat never hides another deficit."""
    if not isinstance(values,dict) or any(type(values.get(k)) is not int or not 0<=values[k]<=31 for k in STAT_KEYS):return None
    preferred=priorities(preferred);weights=tuple(2 if k in preferred else 1 for k in STAT_KEYS)
    missing=[dict(kind='iv',stat=k,actual=values[k],required=n) for k,n in zip(STAT_KEYS,minimums) if values[k]<n]
    score=sum(min(values[k],n)*weight for k,n,weight in zip(STAT_KEYS,minimums,weights))
    target=sum(n*weight for n,weight in zip(minimums,weights))
    return dict(rank=[score],score=score,target_score=target,iv_passed=6-len(missing),missing=missing,priority_ivs=list(preferred))
