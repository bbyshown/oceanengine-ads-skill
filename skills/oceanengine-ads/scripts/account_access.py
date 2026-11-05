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


def add_account(pair, run_id, *, dry_run=False, config_path=None,profile_id=None,game_app_id=None):
    import ads
    path = Path(config_path) if config_path else settings.config_path()
    config = settings.load(path)
    alias, target = check_alias(config, pair)
    if config['access_mode'] != 'operator':
        raise PermissionError('Account enrollment requires an authorized operator profile.')
    if not re.fullmatch(r'[A-Za-z0-9_-]{8,64}', run_id):
        raise ValueError('Use one stable 8–64 character run-id; reuse it after interruption.')
    client = ads.SelectedClient(settings.select_account(config=config))
    profile_args={'profile_id':profile_id} if profile_id else {}
    data = ads.read('discover_accounts',profile_args, client=client)['data']
    if data.get('registration_version') != 1 or not isinstance(data.get('game_app_id'), str):
        raise ValueError('Gateway does not advertise compatible account enrollment.')
    if data.get('profile_id')!=profile_id:raise ValueError('Gateway did not select the requested authorization profile.')
    game=game_app_id or data['game_app_id']
    if target not in {r['account_id'] for r in data['accounts']}:
        raise ValueError('Account is not authorized in this gateway workbench; complete platform authorization first.')
    plan = {'action': 'register_account', 'steps': [{'op': 'register_account', 'args': {
        'target_account_id': target, 'game_app_id': game,**profile_args}}]}
    if dry_run: return {'status': 'preview', 'account_id': target, 'plan': plan, 'scope_changed': False}
    receipt = ads.execute_plan(plan, run_id, client=client)
    if receipt['status'] != 'done':
        return {'status': receipt['status'], 'run_id': run_id, 'local_alias_saved': False,
                'next_step': 'Repeat the same add-account command with the same run-id.'}
    result = receipt['steps'][0]['response']['result'].get('data') or {}
    if result.get('verified') is not True or result.get('account_id') != target or result.get('game_app_id') != game or result.get('profile_id')!=profile_id:
        raise ValueError('Registration readback mismatch; local configuration preserved.')
    after = ads.read('discover_accounts',profile_args, client=client)['data']
    if after.get('profile_id')!=profile_id or not any(
            r.get('account_id') == target and r.get('managed') is True and r.get('game_app_id',after.get('game_app_id'))==game for r in after.get('accounts', [])):
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


def authorize_profile(profile_id, run_id, *, dry_run=False):
    import ads
    if (not isinstance(profile_id,str) or not re.fullmatch(r'[a-z][a-z0-9_-]{3,47}',profile_id)
            or profile_id in {'default','primary','legacy'}):
        raise ValueError('Choose a new 4–48 character lowercase profile ID.')
    cfg=settings.load()
    if cfg['access_mode']!='operator':raise PermissionError('Authorization link creation requires an authorized operator profile.')
    if not re.fullmatch(r'[A-Za-z0-9_-]{8,64}',run_id):raise ValueError('Use a stable 8–64 character run-id.')
    client=ads.SelectedClient(settings.select_account(config=cfg))
    plan={'action':'isolated_oauth_authorize','steps':[{'op':'oauth_profile_authorize','args':{'profile_id':profile_id}}]}
    if dry_run:return {'status':'preview','plan':plan}
    receipt=ads.execute_plan(plan,run_id,client=client)
    if receipt['status']!='done':return {'status':receipt['status'],'run_id':run_id,'profile_id':profile_id}
    data=receipt['steps'][0]['response']['result']['data']
    if data.get('profile_id')!=profile_id or data.get('storage')!='isolated_profile' or data.get('existing_credentials_replaced') is not False:
        raise ValueError('Gateway did not confirm isolated authorization; stop before opening the link.')
    return dict(data,status='awaiting_user_authorization',run_id=run_id)
