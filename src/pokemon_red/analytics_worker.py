"""One-shot read-only journal worker. Never creates a Game, UI or SQLite writer."""
from pathlib import Path
import json
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pokemon_red.history_queries import collect, render


def main():
    request_path, output_path = map(Path, sys.argv[1:])
    request = json.loads(request_path.read_text())
    from pokemon_red.installation_versions import require_response,versioned_response
    require_response(request)
    path = Path(request['database']).resolve()
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=5) as database:
        try:
            database.execute('PRAGMA query_only=ON')
            database.execute('BEGIN')
            raw = collect(database, request['name'], request['params'])
        finally:
            database.rollback()
    database.close()
    # Release the database read lock before the expensive Python/JSON phase.
    output_path.with_suffix('.started').write_text('aggregating')
    result = render(request['name'], raw, request['params'])
    with output_path.open('w',encoding='utf-8') as output:
        if request['name']=='export':json.dump(result,output,ensure_ascii=False);output.write('\n')
        else:
            # Bound each parent-side JSON decoding call; never decode a whole
            # 50k-group result in one GIL-holding json.loads() call.
            for row in result:output.write(json.dumps(row,ensure_ascii=False)+'\n')
    output_path.with_suffix('.version.json').write_text(json.dumps(versioned_response({})))


if __name__ == '__main__':
    main()
