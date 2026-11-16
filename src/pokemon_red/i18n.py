"""Offline localization. Game data and persisted identifiers are never translated.

New UI uses t('settings.language') and named placeholders. render() is the
presentation adapter for the existing, Russian-source interface during migration.
"""
from collections import OrderedDict
from functools import lru_cache
import atexit
from datetime import datetime,timezone
import hashlib
import sys
import json
import logging
from logging.handlers import QueueHandler, QueueListener, RotatingFileHandler
from pathlib import Path
import queue
import re
from string import Formatter
import threading
import unicodedata
import weakref

DEFAULT_LOCALE = 'en'
SUPPORTED_LOCALES = ('en', 'ru')
LOCALE_NAMES = {'en': 'English', 'ru': 'Русский'}
LOCALES = Path(__file__).with_name('locales')
_locale = DEFAULT_LOCALE
_listeners = weakref.WeakSet()
_missing = OrderedDict()
_lock = threading.RLock()
_logger = logging.getLogger('pokemon_red.i18n')
_logger.addHandler(logging.NullHandler())
_logger.propagate = False
_log_listener = None
_log_path = None


def normalize_locale(value):
    language = str(value or '').replace('_', '-').split('-')[0].lower()
    return language if language in SUPPORTED_LOCALES else DEFAULT_LOCALE


def get_locale():
    return _locale


def set_locale(value):
    global _locale
    language = normalize_locale(value)
    if language == _locale:
        return
    _locale = language
    for listener in list(_listeners):
        try:listener.locale_changed()
        except Exception as error:
            # A view can outlive its Tcl interpreter through a traceback or an
            # inspector reference. Drop only this specific lifecycle condition.
            if type(error).__name__=='TclError' and 'application has been destroyed' in str(error):
                _listeners.discard(listener)
            else:raise


def unsubscribe(listener):
    _listeners.discard(listener)


def subscribe(listener):
    """Weakly held UI objects; dispatch only from the UI thread."""
    _listeners.add(listener)


def shutdown_diagnostics():
    global _log_listener,_log_path
    if _log_listener:
        _log_listener.stop()
        for handler in _log_listener.handlers:handler.close()
        _log_listener=None
    _logger.handlers=[logging.NullHandler()]
    _log_path=None


atexit.register(shutdown_diagnostics)


class _DroppingQueueHandler(QueueHandler):
    def enqueue(self,record):
        try:self.queue.put_nowait(record)
        except queue.Full:pass


def configure(root, language=DEFAULT_LOCALE):
    """Install bounded, asynchronous diagnostics; no translated text is logged."""
    global _log_listener, _log_path
    path = Path(root) / 'Data/logs/i18n.jsonl'
    if path != _log_path:
        if _log_listener:
            shutdown_diagnostics()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            handler = RotatingFileHandler(path, maxBytes=1_048_576, backupCount=1, encoding='utf-8')
            handler.setFormatter(logging.Formatter('%(message)s'))
            incoming = queue.Queue(maxsize=2048)
            _logger.handlers = [_DroppingQueueHandler(incoming)]
            _logger.setLevel(logging.WARNING)
            _log_listener = QueueListener(incoming, handler)
            _log_listener.start()
            _log_path = path
        except OSError:
            _logger.handlers = [logging.NullHandler()]
    set_locale(language)


def report_missing(key, *, language=None, reason='missing_translation'):
    language = normalize_locale(language or get_locale())
    identity = (language, key, reason)
    with _lock:
        if identity in _missing:
            return
        # Keep both memory and logs bounded even for malformed dynamic keys.
        if len(_missing) >= 2048:
            return
        event = dict(time=datetime.now(timezone.utc).isoformat(),code=reason,locale=language,key=key)
        frame=sys._getframe(1)
        while frame:
            filename=Path(frame.f_code.co_filename)
            if filename.parent.name=='pokemon_red' and filename.name not in ('i18n.py','entity_names.py','localized_tk.py','ui.py'):
                event['source']=filename.name+':'+str(frame.f_lineno);break
            frame=frame.f_back
        _missing[identity] = event
    _logger.warning(json.dumps(event, ensure_ascii=False))


def missing_translations():
    with _lock:
        return [dict(event) for event in _missing.values()]


@lru_cache(maxsize=16)
def messages(language):
    try:
        value = json.loads((LOCALES / (language + '.json')).read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        report_missing('catalog.' + language, language=language, reason='invalid_catalog')
        return {}


def plural_category(count, language=None):
    language = normalize_locale(language or get_locale())
    if language == 'ru' and float(count).is_integer():
        number = abs(int(count))
        if number % 10 == 1 and number % 100 != 11:
            return 'one'
        if 2 <= number % 10 <= 4 and not 12 <= number % 100 <= 14:
            return 'few'
        return 'many'
    return 'one' if count == 1 else 'other'


def _valid_message(value):
    if isinstance(value,str):return bool(value.strip())
    return isinstance(value,dict) and isinstance(value.get('other'),str) and bool(value['other'].strip()) and all(isinstance(item,str) and bool(item.strip()) for item in value.values())


def _lookup(key, language):
    value=messages(language).get(key)
    if not _valid_message(value):
        report_missing(key,language=language)
        value=messages(DEFAULT_LOCALE).get(key)
    if not _valid_message(value):
        report_missing(key,language=DEFAULT_LOCALE)
        return key.rsplit('.',1)[-1].replace('_',' ').replace('-',' ').capitalize()
    return value


def _format(template, parameters, key, language):
    class Values(dict):
        def __missing__(self, field):
            report_missing(key, reason='missing_parameter')
            return '{' + field + '}'
    try:
        fields = [name for _, name, _, _ in Formatter().parse(template) if name is not None]
        if any(not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*', field) for field in fields):
            raise ValueError('Only named interpolation is supported')
        from .entity_names import EntityLabel
        values={name:render(value,locale=language) if isinstance(value,(Message,EntityLabel)) else value for name,value in parameters.items()}
        return template.format_map(Values(values))
    except (ValueError, TypeError, KeyError, AttributeError):
        report_missing(key, reason='invalid_interpolation')
        return template


class Message(str):
    def __new__(cls,value,key,parameters,locale,count):
        instance=super().__new__(cls,value)
        instance.key=key;instance.parameters=parameters;instance.locale=locale;instance.count=count
        return instance

    def __reduce_ex__(self,protocol):
        return (type(self),(str(self),self.key,self.parameters,self.locale,self.count))


def t(key, *, locale=None, count=None, **parameters):
    language = normalize_locale(locale or get_locale())
    value = _lookup(key, language)
    if isinstance(value, dict):
        if count is None:
            report_missing(key, reason='missing_count')
            count = 0
        value = value.get(plural_category(count, language), value['other'])
    if count is not None:
        parameters['count'] = count
    return Message(_format(value, parameters, key, language),key,parameters,locale,count)


class Verbatim(str):
    """User nicknames, save names and typed text must retain their spelling."""


def literal(value):
    return Verbatim(str(value))


def normalize_search(value):
    value = unicodedata.normalize('NFKC', str(value)).casefold().replace('ё', 'е')
    return ' '.join(re.sub(r'[^\w♀♂]+', ' ', value, flags=re.UNICODE).split())


def search_matches(query, *values):
    haystack = normalize_search(' '.join(str(v) for v in values if v is not None))
    return all(word in haystack for word in normalize_search(query).split())


@lru_cache(maxsize=1)
def _legacy_index():
    russian=messages('ru');english=messages('en')
    try:manifest=json.loads((LOCALES/'manifest.json').read_text(encoding='utf-8'))
    except (OSError,ValueError):manifest={}
    exact={};originals={}
    for key,value in russian.items():
        if not key.startswith('legacy.') or not isinstance(value,str):continue
        source=manifest.get(key,{}).get('source',value)
        originals[source]=key;exact[source]=key
    # Canonical source strings stay independent of editable translations.
    # Both translated versions can also be refreshed after a locale change.
    for language,catalog in (('ru',russian),('en',english)):
        for key,value in catalog.items():
            if key.startswith('legacy.') and isinstance(value,str):exact.setdefault(value,key)
    templates=[]
    for source_text,key in exact.items():
        if not re.search(r'\{p\d+\}',source_text):continue
        parts=re.split(r'(\{p\d+\})',source_text)
        literals=tuple(part.replace('{{','{').replace('}}','}') for part in parts[::2])
        expression=''.join('(?P<'+part[1:-1]+'>.*?)' if re.fullmatch(r'\{p\d+\}',part) else re.escape(part.replace('{{','{').replace('}}','}')) for part in parts)
        templates.append((re.compile(expression,re.DOTALL),key,len(re.sub(r'\{p\d+\}','',source_text)),literals))
    templates.sort(key=lambda row:-row[2])
    fragments={}
    for language in SUPPORTED_LOCALES:
        candidates={source:key for source,key in exact.items() if not re.search(r'\{p\d+\}',source) and source and (re.search('[А-Яа-яЁё]',source) if language=='en' else re.search('[A-Za-z]',source))}
        # Keep generic English matching conservative; brands and data IDs are
        # handled explicitly, and typed/user-provided text bypasses rendering.
        if language=='ru':candidates={source:key for source,key in candidates.items() if len(source.strip())>=4 and source.strip() not in ('Pokémon','FireRed','LeafGreen','Ruby','Sapphire','App Nap')}
        order=sorted(candidates,key=len,reverse=True)
        pattern=_fragment_pattern(order)
        fragments[language]=(pattern,candidates)
    return exact,fragments,templates


def _fragment_pattern(sources):
    """Share literal prefixes instead of trying thousands of alternatives per char.

    Children precede terminals so a longer source wins at the same offset,
    exactly as in the former length-sorted alternation. Word boundaries stay
    attached to each source, including punctuation-only captions.
    """
    roots={True:{},False:{}}
    for source in sources:
        node=roots[source[0].isalnum()]
        for char in source:node=node.setdefault(char,{})
        node[None]=r'(?!\w)' if source[-1].isalnum() else ''
    def expression(node):
        options=[]
        for char,child in node.items():
            if char is None:continue
            prefix=char
            while None not in child and len(child)==1:
                char,child=next(iter(child.items()));prefix+=char
            options.append(re.escape(prefix)+expression(child))
        if None in node:options.append(node[None])
        return options[0] if len(options)==1 else '(?:'+'|'.join(options)+')'
    options=[(r'(?<!\w)' if boundary else '')+expression(node) for boundary,node in roots.items() if node]
    return re.compile('|'.join(options) if options else r'(?!)')


@lru_cache(maxsize=8192)
def _render_cached(text, language):
    exact,fragment_indexes,templates=_legacy_index()
    if text in exact:return t(exact[text],locale=language)
    from .entity_names import display_entity_names
    # Translating an entity must never short-circuit the surrounding sentence.
    # Match templates against the original text before resolving their values.
    for pattern,key,_,literals in templates:
        # These are necessary conditions, not a different matching policy.
        # In particular, don't run backtracking .*? templates on long route
        # summaries which cannot contain the template's fixed words.
        if not text.startswith(literals[0]) or not text.endswith(literals[-1]) or any(part not in text for part in literals):continue
        match=pattern.fullmatch(text)
        if match:return t(key,locale=language,**{k:_render_fragment(v,language) for k,v in match.groupdict().items()})
    entity_text=display_entity_names(text,locale=language)
    fragments,candidates=fragment_indexes[language]
    result=fragments.sub(lambda match:t(candidates[match.group()],locale=language),entity_text)
    if language=='en' and re.search('[А-Яа-яЁё]',result):
        report_missing('unregistered.'+hashlib.sha256(text.encode()).hexdigest()[:16],language=language,reason='unregistered_text')
        return text
    return result


def _render_fragment(value, language):
    # Nested backend messages sometimes interpolate another message.
    return _render_cached(value,language)


def render(value, *, locale=None):
    if not str(value):return ''
    if re.fullmatch(r'[^\n]+\.py(?:  ⌄)?',str(value)):return str(value)
    if str(value).removesuffix('  ⌄') in LOCALE_NAMES.values():return str(value)
    if isinstance(value, Message):
        return t(value.key,locale=locale or value.locale,count=value.count,**{k:v for k,v in value.parameters.items() if k!='count'})
    if isinstance(value, Verbatim):
        return value
    from .entity_names import display_entity_names,EntityLabel,entity_name
    if isinstance(value,EntityLabel):return entity_name(value.kind,value.identifier,value.fallback,locale=locale or get_locale())
    language=normalize_locale(locale or get_locale())
    text=_render_cached(str(value), language)
    return display_entity_names(text,locale=language)


def format_number(number, *, locale=None, decimals=0):
    text = f'{number:,.{decimals}f}'
    return text.replace(',', '\u00a0').replace('.', ',') if normalize_locale(locale or get_locale()) == 'ru' else text


def format_datetime(value, *, locale=None):
    if isinstance(value,str):value=datetime.fromisoformat(value)
    if not isinstance(value,datetime):value=datetime.fromtimestamp(value,timezone.utc)
    pattern='%d.%m.%Y · %H:%M:%S' if normalize_locale(locale or get_locale())=='ru' else '%Y-%m-%d · %H:%M:%S'
    return value.astimezone().strftime(pattern)
