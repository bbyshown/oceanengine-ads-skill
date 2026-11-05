"""Enroll a provider-authorized account and merge its local alias after readback."""
import copy
from pathlib import Path
import re

import settings


def check_alias(config, pair):
    alias, sep, identifier = pair.partition('=')
    if (not sep or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', alias)
            or not re.fullmatch(r'[1-9][0-9]{0,18}', identifier)):
        raise ValueError('Use alias=account_id with a safe alias and positive decimal ID.')
    target = int(identifier)
    known = settings.accounts(config)
    if alias in known and known[alias] != target:
        raise ValueError('Alias already belongs to another account; no configuration changed.')
    if any(i == target and name != alias for name, i in known.items()):
        raise ValueError('Account already has a local alias; use that alias.')
    return alias, target


def add_account(pair, run_id, *, dry_run=False, config_path=None):
    import ads
    path = Path(config_path) if config_path else settings.config_path()
    config = settings.load(path)
    alias, target = check_alias(config, pair)
    if config['access_mode'] != 'operator':
        raise PermissionError('Account enrollment requires an authorized operator profile.')
    if not re.fullmatch(r'[A-Za-z0-9_-]{8,64}', run_id):
        raise ValueError('Use one stable 8–64 character run-id; reuse it after interruption.')
    client = ads.SelectedClient(settings.select_account(config=config))
    data = ads.read('discover_accounts', client=client)['data']
    if data.get('registration_version') != 1 or not isinstance(data.get('game_app_id'), str):
        raise ValueError('Gateway does not advertise compatible account enrollment.')
    if target not in {r['account_id'] for r in data['accounts']}:
        raise ValueError('Account is not authorized in this gateway workbench; complete platform authorization first.')
    plan = {'action': 'register_account', 'steps': [{'op': 'register_account', 'args': {
        'target_account_id': target, 'game_app_id': data['game_app_id']}}]}
    if dry_run: return {'status': 'preview', 'account_id': target, 'plan': plan, 'scope_changed': False}
    receipt = ads.execute_plan(plan, run_id, client=client)
    if receipt['status'] != 'done':
        return {'status': receipt['status'], 'run_id': run_id, 'local_alias_saved': False,
                'next_step': 'Repeat the same add-account command with the same run-id.'}
    result = receipt['steps'][0]['response']['result'].get('data') or {}
    if result.get('verified') is not True or result.get('account_id') != target or result.get('game_app_id') != data['game_app_id']:
        raise ValueError('Registration readback mismatch; local configuration preserved.')
    after = ads.read('discover_accounts', client=client)['data']
    if after.get('game_app_id') != data['game_app_id'] or not any(
            r.get('account_id') == target and r.get('managed') is True for r in after.get('accounts', [])):
        raise ValueError('Account registration is not visible; reuse the same run-id after inspection.')
    if settings.load(path) != config:
        raise ValueError('Local configuration changed concurrently; repeat with the same run-id.')
    merged = copy.deepcopy(config); merged['accounts'][alias] = {'id': str(target)}
    settings.validate(merged)
    # Reuse the existing writer without importing a possibly unrelated installed setup module.
    import importlib.util
    spec = importlib.util.spec_from_file_location('account_connection_setup', Path(__file__).with_name('setup.py'))
    writer = importlib.util.module_from_spec(spec); spec.loader.exec_module(writer)
    writer.write_config(path, merged, overwrite=True)
    return {'status': 'done', 'account_id': target, 'alias': alias, 'local_alias_saved': True,
            'scope_changed': result.get('scope_changed'), 'ad_mutations_performed': False, 'run_id': run_id}
