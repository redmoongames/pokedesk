"""Localized map labels. Raw map IDs always remain the navigation identity."""
import re
from .entity_names import entity_name,entities
from .i18n import t,get_locale,normalize_locale,report_missing

# Compatibility for consumers importing the historical town-name table.
NAMES={key:value['ru'] for key,value in entities()['locations'].items() if '_' not in key}

def location_name(raw, *, locale=None):
    language=normalize_locale(locale or get_locale())
    if not raw:return t('location.start',locale=language)
    if re.fullmatch(r'Route\d+',raw):return entity_name('locations',raw,t('location.route',locale=language,number=raw[5:]),locale=locale)
    return entity_name('locations',raw,re.sub(r'(?<=[a-z])(?=[A-Z0-9])',' ',raw).replace('_',' · '),locale=language)
