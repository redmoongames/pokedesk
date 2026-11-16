"""Pure recovery checks shared by training and isolated game-button players."""


class HealingTelemetryError(RuntimeError):
    """Recovery cannot be decided safely from the supplied observation."""


def recovery_reasons(state):
    """Return missing HP/status/PP, or fail rather than trusting incomplete data.

    No timer or cached success is used: changing the party or spending one PP
    makes a later call require recovery again. Eggs do not need nurse treatment.
    """
    party = state.get('party', [])
    if not party or not state.get('telemetry_valid', True):
        raise HealingTelemetryError('Нет корректных данных команды для проверки лечения')
    reasons = []
    for mon in party:
        if not mon.get('checksum_valid', True):
            raise HealingTelemetryError('Данные Pokémon ещё обновляются')
        if mon.get('is_egg'):
            continue
        maximum, hp = mon.get('max_hp', 0), mon.get('hp', -1)
        if type(maximum) is not int or type(hp) is not int or maximum <= 0 or not 0 <= hp <= maximum:
            raise HealingTelemetryError('Некорректные HP при проверке лечения')
        missing = []
        for move in mon.get('moves', []):
            limit, current = move.get('max_pp', move.get('pp')), move.get('current_pp')
            if type(limit) is not int or type(current) is not int or not 0 <= current <= limit:
                raise HealingTelemetryError('Некорректные PP при проверке лечения')
            if current < limit:
                missing.append(move['id'])
        status = bool(mon.get('status_code', 0)) or mon.get('status', 'В норме') not in ('В норме', 'Без сознания')
        if hp < maximum or status or missing:
            reasons.append(dict(uid=mon['uid'], pokemon=mon.get('nickname', 'Pokémon'),
                                missing_hp=maximum-hp, status=mon.get('status') if status else None,
                                moves=missing))
    return reasons
