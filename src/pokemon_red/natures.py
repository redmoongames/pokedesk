"""Nature IDs and effects for Gen III; decoded nature is personality % 25.

Names: pret/pokefirered at ce6406d8c2eaf46d543c8a2606de0c3cb1951982,
src/data/text/nature_names.h; modifiers: src/pokemon.c, ModifyStatByNature.
"""
from .models import STAT_KEYS

NATURE_NAMES=('HARDY','LONELY','BRAVE','ADAMANT','NAUGHTY',
              'BOLD','DOCILE','RELAXED','IMPISH','LAX',
              'TIMID','HASTY','SERIOUS','JOLLY','NAIVE',
              'MODEST','MILD','QUIET','BASHFUL','RASH',
              'CALM','GENTLE','SASSY','CAREFUL','QUIRKY')

def nature_effect(value):
    if type(value) is not int or not 0<=value<len(NATURE_NAMES):return None
    raised,lowered=divmod(value,5)
    modifiers={} if raised==lowered else {STAT_KEYS[raised+1]:10,STAT_KEYS[lowered+1]:-10}
    return dict(name=NATURE_NAMES[value],modifiers=modifiers)
