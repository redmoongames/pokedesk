"""Locale-independent entity identity, localized labels and bilingual aliases."""
from functools import lru_cache
import json
import re
from .i18n import LOCALES, DEFAULT_LOCALE, get_locale, normalize_locale, report_missing, search_matches, literal


class EntityLabel(str):
    def __new__(cls,value,kind,identifier,fallback,locale):
        instance=super().__new__(cls,value)
        instance.kind=kind;instance.identifier=identifier;instance.fallback=fallback;instance.locale=locale
        return instance

    def __reduce_ex__(self,protocol):
        return (type(self),(str(self),self.kind,self.identifier,self.fallback,self.locale))


@lru_cache(maxsize=1)
def entities():
    empty={kind:{} for kind in ('species','moves','abilities','items','locations','natures')}
    try:
        data=json.loads((LOCALES/'entities.json').read_text(encoding='utf-8'))
        if not isinstance(data,dict):raise ValueError('Invalid entity catalog')
        return {kind:entries if isinstance(entries,dict) else {} for kind,entries in dict(empty,**data).items()}
    except (OSError,ValueError):
        report_missing('catalog.entities',reason='invalid_catalog');return empty


def entity_name(kind, identifier, fallback='', *, locale=None):
    language = normalize_locale(locale or get_locale())
    entry = entities().get(kind, {}).get(str(identifier), {})
    entry=entry if isinstance(entry,dict) else {}
    value = entry.get(language)
    if not isinstance(value,str) or not value:
        report_missing(f'entities.{kind}.{identifier}', language=language)
        value = entry.get(DEFAULT_LOCALE) or fallback
    if not value:
        value = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', str(identifier)).replace('_', ' ')
    return EntityLabel(value,kind,identifier,fallback,locale)


def entity_aliases(kind, identifier, fallback=''):
    entry = entities().get(kind, {}).get(str(identifier), {})
    number=str(entry.get('national_id','')) if kind=='species' else str(identifier) if kind=='locations' else ''
    return ' '.join(dict.fromkeys([number, entry.get('en', ''), entry.get('ru', ''), *entry.get('aliases', []), fallback]))


def species_name(number, fallback='', *, locale=None):
    return entity_name('species', number, fallback, locale=locale)


def move_name(number, fallback='', *, locale=None):
    return entity_name('moves', number, fallback, locale=locale)


def ability_name(number, fallback='', *, locale=None):
    return entity_name('abilities', number, fallback, locale=locale)


def nature_name(number, *, locale=None):
    return entity_name('natures',number,locale=locale)


def item_name(number, fallback='', *, locale=None):
    return entity_name('items', number, fallback, locale=locale)


def pokemon_name(mon, *, locale=None):
    nickname = mon.get('nickname', '')
    canonical = mon.get('species', '')
    if nickname and nickname.casefold() != canonical.casefold():
        return literal(nickname)
    return species_name(mon.get('species_id'), canonical or nickname, locale=locale)


def display_entity_names(text, *, locale=None):
    """Translate exact canonical entity labels at the presentation boundary.

    Only complete labels are recognized. Text inside user nicknames or prose is
    never replaced. ID-based helpers are preferable for new screens.
    """
    value=str(text);whole=_english_index().get(value.casefold())
    if whole:return entity_name(*whole,fallback=value,locale=locale)
    pieces=re.split(r'( · | → |\n| ↗|: |, |  ⌄)',value)
    for index,piece in enumerate(pieces):
        match=re.fullmatch(r'(\s*(?:[✓✦★○✧]+\s*|#\d+\s+)?)(.*?)((?: Lv \d+)?\s*[◀↗.]?)',piece)
        if not match:continue
        prefix,name,suffix=match.groups();entry=_english_index().get(name.casefold()) if name else None
        if entry:pieces[index]=prefix+entity_name(*entry,fallback=name,locale=locale)+suffix
    return ''.join(pieces)



@lru_cache(maxsize=1)
def _english_index():
    result = {}
    for kind in ('locations', 'items', 'abilities', 'moves', 'species', 'natures'):
        for key, entry in entities()[kind].items():
            for name in (entry['en'],entry['ru'],*entry.get('aliases',[]),key if kind=='locations' else ''):
                if name:result[name.casefold()] = (kind, key)
    return result


def location_aliases(raw):
    return entity_aliases('locations', raw, re.sub(r'(?<=\D)(?=\d)', ' ', raw))


def location_matches(query, raw, *labels):
    return search_matches(query, location_aliases(raw), *labels)
