"""Recovery decisions use only validated current data, without a ROM or UI."""
from copy import deepcopy
import unittest

from pokemon_red.healing import HealingTelemetryError, recovery_reasons


def pokemon():
    return dict(uid='one', hp=30, max_hp=30, status_code=0, checksum_valid=True,
                moves=[dict(id=33, current_pp=35, max_pp=35)])


class RecoveryStateTests(unittest.TestCase):
    def test_healthy_party_needs_no_recovery_and_is_not_mutated(self):
        state = dict(party=[pokemon()]);before = deepcopy(state)
        self.assertEqual(recovery_reasons(state), [])
        self.assertEqual(state, before)

    def test_hp_status_and_pp_independently_require_recovery(self):
        for kind in ('damage', 'faint', 'poison', 'sleep', 'paralysis', 'pp'):
            mon = pokemon()
            if kind in ('damage', 'faint'):mon['hp'] = 10 if kind == 'damage' else 0
            elif kind == 'pp':mon['moves'][0]['current_pp'] -= 1
            else:mon['status_code'] = {'poison':8, 'sleep':3, 'paralysis':64}[kind]
            with self.subTest(kind=kind):self.assertEqual(len(recovery_reasons(dict(party=[mon]))), 1)

    def test_changed_party_and_spent_pp_are_not_hidden_by_a_success_cache(self):
        state = dict(party=[pokemon()]);self.assertFalse(recovery_reasons(state))
        mon = pokemon();mon.update(uid='two', hp=1);state['party'].append(mon)
        self.assertEqual(recovery_reasons(state)[0]['uid'], 'two')
        state['party'].pop();state['party'][0]['moves'][0]['current_pp'] -= 1
        self.assertEqual(recovery_reasons(state)[0]['moves'], [33])

    def test_invalid_or_transient_observations_never_mean_healthy(self):
        for change in ({'hp':-1}, {'hp':31}, {'max_hp':0}, {'hp':True}, {'checksum_valid':False}):
            mon = dict(pokemon(), **change)
            with self.subTest(change=change), self.assertRaises(HealingTelemetryError):recovery_reasons(dict(party=[mon]))
        for state in ({}, {'party':[]}, {'party':[pokemon()], 'telemetry_valid':False}):
            with self.assertRaises(HealingTelemetryError):recovery_reasons(state)

    def test_invalid_pp_is_rejected_instead_of_starting_a_retry_loop(self):
        for current, maximum in ((None,35), (36,35), (-1,35), (3,None), (True,35)):
            mon = pokemon();mon['moves'][0].update(current_pp=current, max_pp=maximum)
            with self.subTest(current=current, maximum=maximum), self.assertRaises(HealingTelemetryError):recovery_reasons(dict(party=[mon]))

    def test_pp_fallback_and_eggs_preserve_existing_semantics(self):
        mon = pokemon();mon['moves'][0].pop('max_pp');mon['moves'][0]['pp'] = 35
        self.assertFalse(recovery_reasons(dict(party=[mon, dict(is_egg=True)])))
