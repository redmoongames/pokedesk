"""Reviewed party changes through ordinary travel, healing and PC menus."""
from .i18n import t
from .training import TrainingProblem


def validate_roster(inventory, desired):
    if not inventory.get('ready'):
        raise ValueError(t('party_edit.wait_inventory'))
    if not isinstance(desired, (list, tuple)) or not 1 <= len(desired) <= 6:
        raise ValueError(t('party_edit.choose_count'))
    if any(not isinstance(uid, str) for uid in desired) or len(set(desired)) != len(desired):
        raise ValueError(t('party_edit.duplicates'))
    owned = {m['uid']: m for m in inventory.get('party', []) + inventory.get('boxes', [])}
    if any(uid not in owned for uid in desired):
        raise ValueError(t('party_edit.missing'))
    if any(not owned[uid].get('checksum_valid', True) or owned[uid].get('is_egg') for uid in desired):
        raise ValueError(t('party_edit.unavailable_mon'))
    removed = [m for m in inventory.get('party', []) if m['uid'] not in desired]
    if any(121 <= m.get('held_item', 0) <= 132 for m in removed):
        raise ValueError(t('party_edit.mail'))
    # Deposit/Withdraw deliberately never enter Move/Release. Keep a temporary
    # box slot for a full-party swap; reject before travelling or sending input.
    if removed and 14 * 30-len(inventory.get('boxes', [])) < len(removed):
        raise ValueError(t('party_edit.boxes_full'))
    return [owned[uid] for uid in desired]


def validate_field(state):
    if not state.get('ready') or not state.get('telemetry_valid', True):
        raise ValueError(t('party_edit.wait_game'))
    c = state.get('controls', {})
    if state.get('in_battle') or c.get('callback') != 'CB2_Overworld' or c.get('field_locked') or c.get('moving'):
        raise ValueError(t('party_edit.close_dialog'))


def roster_plan(root, state, inventory, provider, desired):
    """Run in a private planning process; never in a Tk callback."""
    from .travel import navigator, strongest
    validate_field(state)
    validate_roster(inventory, desired)
    if strongest(inventory.get('party', [])) is None:
        raise ValueError(t('party_edit.no_runner'))
    nav = navigator(root, state, inventory, provider)
    # Only current-party tools may prove the first Center reachable.
    clinic, path = nav.nearest_clinic(before_preparation=True)
    hub = nav.spec['hubs'][clinic]
    party = [m['uid'] for m in inventory['party']]
    return dict(desired=list(desired), clinic=clinic, destination=hub['map'],
                label=hub['label'], goal=hub['nurse'], steps=path['cost'][1],
                removed=[uid for uid in party if uid not in desired],
                added=[uid for uid in desired if uid not in party])


def order_party(trainer, desired):
    """Fix slots using the existing first-slot swap, with a fresh read each time."""
    for index in range(1, len(desired)):
        party = trainer.state()['party']
        if party[index]['uid'] == desired[index]:
            continue
        if party[0]['uid'] != desired[index]:
            trainer.lead(desired[index])
        trainer.lead(trainer.state()['party'][index]['uid'])
    if trainer.state()['party'][0]['uid'] != desired[0]:
        trainer.lead(desired[0])
    if [m['uid'] for m in trainer.state()['party']] != list(desired):
        raise TrainingProblem('party_order_mismatch', str(t('party_edit.verify_failed')))


def run_party_change(bot, config):
    from .travel import Traveler
    from .storage import Storage
    desired = config['desired']
    trainer = Traveler(bot, dict(allow_trainers=False))
    state = trainer.state()
    validate_field(state)
    inventory = bot.inventory()
    validate_roster(inventory, desired)
    # Confirm the reviewed destination remains reachable, rather than silently
    # choosing a different clinic or a party containing boxed field providers.
    from .navigation import Navigator
    trainer.navigator = Navigator(trainer).configure_tools(inventory, 'party')
    trainer.navigator.current_plan(config['destination'], config['goal'])
    bot.safety_profile('training')
    bot.expect_interaction('travel')
    bot.manage_speed(True, max_speed=12)
    trainer.stage(str(t('party_edit.travelling', clinic=config['label'])))
    bot.event('party_change_started', str(t('party_edit.started')), desired=desired,
              destination=config['destination'])
    trainer.travel_lead()
    trainer.navigator.travel(config['destination'], config['goal'])
    if trainer.state()['map']['name'] != config['destination']:
        raise TrainingProblem('party_wrong_center', str(t('party_edit.verify_failed')))
    # Healing first makes a living desired Pokémon available before the guard
    # can leave. Storage itself retains and checks the last usable party member.
    trainer.heal_here()
    validate_roster(bot.inventory(), desired)
    trainer.stage(str(t('party_edit.changing')))
    Storage(trainer).assemble(desired)
    trainer.heal_here()
    trainer.stage(str(t('party_edit.ordering')))
    order_party(trainer, desired)
    bot.checkpoint(str(t('party_edit.after_checkpoint')))
    bot.event('party_change_complete', str(t('party_edit.complete')), desired=desired)
    bot.set_speed(0)
    bot.handoff('party_change_complete', str(t('party_edit.complete')))


def run(bot):
    import json
    from .bot import ControlLost, HandedOff
    try:
        run_party_change(bot, json.loads((bot.project_dir / 'Data/party-change.json').read_text()))
    except (ControlLost, HandedOff):
        raise
    except Exception as error:
        bot.set_speed(0)
        bot.handoff(getattr(error, 'code', 'party_change_error'),
                    str(t('party_edit.stopped', reason=str(error))))
