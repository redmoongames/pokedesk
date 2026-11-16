"""Check formal editorial regressions; this does not replace human copy review."""
import argparse
from collections import Counter
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def audit():
    folder = ROOT / 'src/pokemon_red/locales'
    messages = json.loads((folder / 'ru.json').read_text(encoding='utf-8'))
    entities = json.loads((folder / 'entities.json').read_text(encoding='utf-8'))
    errors = []
    for kind in ('species', 'moves', 'abilities'):
        names = Counter(entry['ru'].casefold() for entry in entities[kind].values())
        for name, count in names.items():
            if count > 1:
                errors.append(dict(kind=kind, name=name, reason='duplicate_display_name'))
        for identifier, entry in entities[kind].items():
            name = entry['ru']
            if re.search(r'\s{2,}|\n|\b(?:форма|формы|нормальный)\b', name, re.I):
                errors.append(dict(kind=kind, id=identifier, reason='scraped_caption_in_name'))
            if kind == 'moves' and re.search('[А-ЯЁ]', name[1:]):
                errors.append(dict(kind=kind, id=identifier, reason='inconsistent_title_case'))
    rejected = re.compile(
        r'рисует электрические движения|упс нападает|лечит при отключении|'
        r'лечит тело, проливая|суперэффективные.*хиты|предотвращает снижение способностей|'
        r'меняет тип на ход врага|покемонаа|покемоныы|шайни шайни', re.I)
    for key, value in messages.items():
        forms = value.values() if isinstance(value, dict) else [value]
        for text in forms:
            if rejected.search(text):
                errors.append(dict(key=key, reason='rejected_copy'))
    for identifier in entities['abilities']:
        key = f'entity.abilities.{identifier}.description'
        if not re.search('[А-Яа-яЁё]', messages.get(key, '')):
            errors.append(dict(key=key, reason='missing_russian_explanation'))
    # Contact effects are probabilistic; avoid promising an unconditional status.
    for identifier in (9, 27, 38, 49, 56):
        key = f'entity.abilities.{identifier}.description'
        if not re.search('может', messages[key], re.I):
            errors.append(dict(key=key, reason='missing_probability_qualifier'))
    return dict(ok=not errors, names={kind:len(entities[kind]) for kind in ('species','moves','abilities')},
                ability_descriptions=len(entities['abilities']), errors=errors)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json', type=Path)
    args = parser.parse_args()
    result = audit()
    output = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(output, encoding='utf-8')
    print(output, end='')
    raise SystemExit(not result['ok'])
