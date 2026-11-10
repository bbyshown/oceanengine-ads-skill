"""Explicit Tencent account/game registration and operator linking; no ad writes."""
import copy
import json
import time

import tencent_runtime as runtime

FIELDS = ['account_id', 'corporation_name', 'mdm_id', 'mdm_name', 'system_status']


def rows(api, endpoint, params):
    output = []
    if endpoint in ('advertiser/get','organization_account_relation/get'): params = dict(params, pagination_mode='PAGINATION_MODE_NORMAL')
    for page in range(1, 101):
        result = api(endpoint, dict(params, page=page, page_size=100))
        data = result.get('data') or {}
        if result.get('code') != 0 or not isinstance(data.get('list'), list) or not isinstance(data.get('page_info'), dict):
            raise runtime.Rejected('Tencent account discovery failed; no partial registration.')
        output += data['list']
        pages=data['page_info'].get('total_page')
        if type(pages) is not int or pages < 0: raise runtime.Rejected('Tencent discovery page count missing; no partial registration.')
        if page >= pages: return output
    raise runtime.Rejected('Tencent discovery pagination incomplete; no partial registration.')


def advertiser(api, account_id):
    found = rows(api, 'advertiser/get', {'account_id': account_id, 'fields': FIELDS})
    if len(found) != 1 or found[0].get('account_id') != account_id or found[0].get('system_status') != 'CUSTOMER_STATUS_NORMAL':
        raise runtime.Rejected('Tencent target account is unavailable to this OAuth identity.')
    return {k: found[0].get(k) for k in FIELDS}


def persist(root, cfg, changed, original):
    with runtime.locked(root, cfg) as folder:
        file = folder / 'config.json'
        if file.read_bytes() != original:
            raise runtime.Rejected('Tencent profile changed during verification; inspect and retry registration.')
        runtime.save(file, changed)
        if json.loads(file.read_text()) != changed: raise runtime.Rejected('Tencent registration readback mismatch.')


def execute(op, args, *, root, cfg, api):
    if not cfg.get('_profile_id'): raise runtime.Rejected('Select an explicit Tencent third-party profile.')
    if op == 'tencent_operator_authorize':
        return {'code': 0, 'data': runtime.operator_authorize_url(root, cfg, args['operator_id'])}
    if op == 'tencent_discover_accounts':
        found = ([advertiser(api, account) for account in args['account_ids']] if args.get('account_ids')
                 else rows(api, 'organization_account_relation/get', {'fields': ['account_id','corporation_name']}))
        return {'code': 0, 'data': {'accounts': [dict({k: r.get(k) for k in FIELDS},
            managed=str(r['account_id']) in cfg['accounts']) for r in found],
            'discovery_grants_management': False, 'discovery_source': 'explicit_account_verification' if args.get('account_ids') else 'organization_account_relation'}}
    original = (runtime.directory(root, cfg) / 'config.json').read_bytes()
    changed = json.loads(original)
    if op == 'tencent_bind_operator':
        selected = args['account_ids']
        if any(str(i) not in cfg['accounts'] for i in selected):
            raise runtime.Rejected('Register the selected account/game scope before linking its operator.')
    else:
        selected = [row['account_id'] for row in args['accounts']]
        for entry in args['accounts']:
            identifier = entry['account_id']; advertiser(api, identifier)
            assets = rows(api, 'conversions/get', {'account_id': identifier,
                'fields': ['conversion_id', 'marketing_carrier_id', 'access_status']})
            games = {a.get('marketing_carrier_id') for a in assets if a.get('access_status') == 'ACCESS_STATUS_COMPLETED'}
            if not set(entry['mini_game_ids']) <= games:
                raise runtime.Rejected('Tencent selected game lacks an accessible completed conversion asset.')
            account = changed['accounts'].setdefault(str(identifier), {'mini_game_ids': []})
            account['mini_game_ids'] = sorted(set(account['mini_game_ids']) | set(entry['mini_game_ids']))
    operator = args.get('operator_id')
    if operator:
        runtime.require_organization(api.organization_authentication(operator, selected), selected)
        for identifier in selected: changed['accounts'][str(identifier)]['operator_id'] = operator
    persist(root, cfg, changed, original)
    return {'code': 0, 'data': {'account_ids': selected, 'operator_id': operator,
        'verified': True, 'scope_changed': changed['accounts'] != cfg['accounts'], 'advertising_settings_changed': False,
        'operator_organization_verified': bool(operator), 'write_enabled': changed.get('write_enabled', False)}}


def migrate_legacy_operator(root, cfg, source_account_id, operator_id, account_ids):
    """Owner-only migration after live organization checks; no copying credentials per account."""
    runtime.operator_name(operator_id)
    if not cfg.get('_profile_id') or any(str(i) not in cfg['accounts'] for i in account_ids):
        raise runtime.Rejected('Migration must stay in an explicit profile and existing account scope.')
    original = (runtime.directory(root, cfg) / 'config.json').read_bytes()
    changed = json.loads(original); credential = changed['accounts'][str(source_account_id)]
    if not runtime.valid_operator(credential): raise runtime.Rejected('Legacy operator credential missing or expired.')
    if operator_id in changed.get('operators', {}): raise runtime.Rejected('Operator already exists; preserve it and bind explicitly.')
    operator = {k: credential[k] for k in ('user_token', 'user_token_expires_at') if k in credential}
    changed.setdefault('operators', {})[operator_id] = operator
    checked = dict(changed, _profile_id=cfg['_profile_id'])
    runtime.require_organization(runtime.API(root, checked).organization_authentication(operator_id, account_ids), account_ids)
    for identifier in account_ids: changed['accounts'][str(identifier)]['operator_id'] = operator_id
    # Preserve the original securely for rollback, while the active profile stores this token once.
    with runtime.locked(root, cfg) as folder:
        if (folder/'config.json').read_bytes() != original: raise runtime.Rejected('Profile changed during migration.')
        runtime.save(folder / ('config-before-operator-migration-' + str(time.time_ns()) + '.json'), json.loads(original))
        for account in changed['accounts'].values():
            if account.get('user_token') == operator['user_token']:
                account.pop('user_token', None); account.pop('user_token_expires_at', None)
        runtime.save(folder/'config.json', changed)
        pending = folder/'user-authorization.json'
        if pending.exists():
            state = json.loads(pending.read_text())
            if state.get('status') == 'issued' and not state.get('operator_id'):
                state.update(status='superseded', message='Account credential replaced by a verified operator association.')
                runtime.save(pending,state)
    return {'migrated': True, 'operator_id': operator_id, 'account_ids': account_ids,
            'organization_verified': True, 'advertising_settings_changed': False}
