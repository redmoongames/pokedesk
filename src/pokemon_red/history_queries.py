"""Shared read-only journal queries and aggregation, independent from a live core.

Collect SQLite rows inside one read transaction, release its lock, then perform
JSON decoding and aggregation. The synchronous History API and process worker
use the same implementation so calculations cannot drift between execution paths.
"""
import json
from datetime import datetime, timezone

QUERIES = frozenset({'comparisons', 'cycles', 'forecast_results', 'rows', 'events', 'export'})


def validate(name, params):
    if name not in QUERIES:
        raise ValueError('Unknown history query')
    params = tuple(params)
    if name in ('comparisons', 'export'):
        if params:raise ValueError('History query takes no arguments')
    elif name == 'forecast_results':
        if len(params) != 2 or not isinstance(params[0], str) or len(params[0]) > 200:
            raise ValueError('Invalid forecast query')
        limit = params[1]
        if type(limit) is not int or not 1 <= limit <= 200:raise ValueError('Invalid history limit')
    elif len(params) != 1 or type(params[0]) is not int or not 1 <= params[0] <= 100000:
        raise ValueError('Invalid history limit')
    return params


def records(db, sql, params=()):
    cursor = db.execute(sql, params)
    return [column[0] for column in cursor.description], cursor.fetchall()


def collect(db, name, params=()):
    params = validate(name, params)
    cycles = 'SELECT c.*,r.route,r.strategy,r.target_uid FROM training_cycles c JOIN training_runs r ON c.run_id=r.id '
    if name == 'comparisons':
        return records(db, cycles + "WHERE c.status='completed' ORDER BY c.id")
    if name in ('cycles', 'forecast_results'):
        return records(db, cycles + 'ORDER BY c.id DESC LIMIT ?', (200 if name == 'forecast_results' else params[0],))
    if name in ('events', 'rows'):
        return records(db, 'SELECT * FROM ' + ('events' if name == 'events' else 'battles') + ' ORDER BY id DESC LIMIT ?', params)
    return dict(comparisons=collect(db, 'comparisons'), cycles=collect(db, 'cycles', (100000,)))


def dictionaries(raw):
    columns, rows = raw
    return [dict(zip(columns, row)) for row in rows]


def comparisons(raw):
    from .run_context import context_complete
    columns, rows = raw
    groups = {}
    for values in rows:
        row = dict(zip(columns, values));body = json.loads(row['body']);complete = context_complete(body.get('context'))
        key = (row['route'], row['strategy'], row['target_uid'], row['team_fingerprint'], None if complete else row['run_id'])
        if key not in groups:
            groups[key] = dict(route=row['route'],strategy=row['strategy'],target_uid=row['target_uid'],team_fingerprint=row['team_fingerprint'],base_team_fingerprint=body.get('team_base_fingerprint',row['team_fingerprint']),cycles=0,target_xp=0,game_seconds=0,active_seconds=0,battles=0,context_complete=complete,legacy_run_id=None if complete else row['run_id'],speeds=set(),last_sample_at='',latest_id=-1)
        group = groups[key]
        for destination, source in [('cycles',None),('target_xp','target_xp'),('game_seconds','game_seconds'),('active_seconds','active_seconds'),('battles','battles')]:
            group[destination] += 1 if source is None else row[source] or 0
        group['speeds'].update(interval['speed'] for interval in body.get('speed_intervals', []))
        latest = row['ended_at'] or row['started_at']
        if (latest, row['id']) > (group['last_sample_at'], group['latest_id']):
            group.update(last_sample_at=latest,started_at=latest,latest_id=row['id'],team=body['team'],clinic=body.get('clinic'),area=body.get('area'),context=body.get('context'),timeline_id=body.get('timeline_id'))
    result = []
    for group in groups.values():
        group['speeds'] = sorted(group['speeds'])
        group['speed_note'] = 'скорость не записана' if not group['speeds'] else f"{group['speeds'][0]:g}×" if len(group['speeds']) == 1 else 'разные скорости'
        group['xp_game_minute'] = group['target_xp'] * 60 / max(1, group['game_seconds'])
        group['xp_active_minute'] = group['target_xp'] * 60 / max(1, group['active_seconds'])
        result.append(group)
    result.sort(key=lambda group:group['xp_game_minute'], reverse=True)
    return result


def render(name, raw, params=()):
    if name == 'comparisons':return comparisons(raw)
    if name == 'cycles':return dictionaries(raw)
    if name == 'forecast_results':
        result = []
        for row in dictionaries(raw):
            if row['target_uid'] == params[0]:
                body = json.loads(row['body'])
                if body.get('evaluation'):result.append(dict(row, body=body))
        return result[:params[1]]
    if name == 'events':
        return [dict(id=r[0],time=r[1],code=r[2],message=r[3],details=json.loads(r[4])) for r in raw[1]]
    if name == 'rows':
        return [dict(id=r[0],time=r[1],map=r[2],outcome=r[3],xp=r[4],frames=r[5],detail=json.loads(r[6])) for r in raw[1]]
    return dict(schema=2,exported_at=datetime.now(timezone.utc).isoformat(),comparisons=comparisons(raw['comparisons']),cycles=[dict(row,body=json.loads(row['body'])) for row in dictionaries(raw['cycles'])])


def query(db, name, params=()):
    return render(name, collect(db, name, params), params)
