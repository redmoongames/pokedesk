"""Offline catalog validation. Exit nonzero for missing/invalid translations.

Run with the bundled Python: tools/check_localization.py --json report.json
New UI uses semantic t() keys; legacy literals are listed with source locations.
"""
import argparse
import ast
import json
from pathlib import Path
import re
from string import Formatter
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from pokemon_red.i18n import LOCALES, SUPPORTED_LOCALES


def fields(text):
    return {name for _, name, _, _ in Formatter().parse(text) if name is not None}


def audit():
    errors = []
    def load(name):
        def pairs(entries):
            value = {}
            for key, item in entries:
                if key in value:
                    errors.append(dict(file=name, key=key, reason='duplicate_key'))
                value[key] = item
            return value
        return json.loads((LOCALES / name).read_text(encoding='utf-8'), object_pairs_hook=pairs)
    catalogs = {language: load(language + '.json') for language in SUPPORTED_LOCALES}
    english = catalogs['en']
    for language, messages in catalogs.items():
        for key in sorted(set(english) | set(messages)):
            value = messages.get(key)
            source = english.get(key)
            if not source or not value:
                errors.append(dict(locale=language, key=key, reason='missing_translation'))
                continue
            source_forms = source.values() if isinstance(source, dict) else [source]
            expected = fields(next(iter(source_forms)))
            forms = value.values() if isinstance(value, dict) else [value]
            if isinstance(value, dict):
                required = {'one', 'few', 'many', 'other'} if language == 'ru' else {'one', 'other'}
                if not required <= set(value):
                    errors.append(dict(locale=language, key=key, reason='missing_plural_forms'))
            for form in forms:
                try:
                    actual = fields(form)
                    if actual != expected:
                        errors.append(dict(locale=language, key=key, reason='placeholder_mismatch'))
                except ValueError:
                    errors.append(dict(locale=language, key=key, reason='invalid_format'))
    # Semantic keys referenced by new code must exist in both catalogs.
    for path in (ROOT / 'src/pokemon_red').glob('*.py'):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 't' and node.args and isinstance(node.args[0], ast.Constant):
                key = node.args[0].value
                if key not in english:
                    errors.append(dict(file=path.name, line=node.lineno, key=key, reason='unknown_key'))
    known = set(catalogs['ru'].values()) if all(isinstance(v, str) for v in catalogs['ru'].values()) else {v for v in catalogs['ru'].values() if isinstance(v, str)}
    manifest=load('manifest.json')
    known.update(entry['source'] for entry in manifest.values() if isinstance(entry,dict) and isinstance(entry.get('source'),str))
    unregistered = []
    for path in (ROOT / 'src/pokemon_red').glob('*.py'):
        if path.name in ('i18n.py', 'entity_names.py', 'localized_tk.py'):
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and re.search('[А-Яа-яЁё]', node.value) and node.value not in known:
                # Regexes and replacement backreferences are implementation data.
                if '\\' in node.value or node.value.startswith('(?'):
                    continue
                unregistered.append(dict(file=path.name, line=node.lineno, reason='unregistered_literal'))
    errors.extend(unregistered)
    entity_data = load('entities.json')
    for kind, entries in entity_data.items():
        for key, entry in entries.items():
            for language in SUPPORTED_LOCALES:
                if not entry.get(language):
                    errors.append(dict(key=f'entities.{kind}.{key}', locale=language, reason='missing_entity_name'))
    # Cover the canonical IDs of every supported game, including Hoenn offsets.
    for path in (ROOT / 'vendor/catalog').glob('*.json'):
        data = json.loads(path.read_text())
        if not all(kind in data for kind in ('species', 'moves', 'abilities')):
            continue
        for kind in ('species', 'moves', 'abilities'):
            for key in data[kind]:
                if key not in entity_data[kind]:
                    errors.append(dict(file=path.name, key=f'{kind}.{key}', reason='missing_entity'))
    for path in (ROOT / 'vendor/reference').rglob('location_reference.json'):
        for key in json.loads(path.read_text())['maps']:
            if key not in entity_data['locations']:
                errors.append(dict(file=str(path.relative_to(ROOT)), key=key, reason='missing_location'))
    return dict(ok=not errors, locales=list(SUPPORTED_LOCALES), messages=len(english), entities={kind:len(entries) for kind,entries in entity_data.items()}, errors=errors)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json', type=Path, help='Also write a machine-readable report')
    args = parser.parse_args()
    report = audit()
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report['ok'] else 1)
