"""Account/game-scoped Tencent v3.0 operations for the existing signed job gateway."""
import base64
import copy
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
import time
import uuid

import tencent_runtime as runtime

from tencent_schema import (READS, WRITES, OPS, GROUP_FIELDS, CREATIVE_FIELDS, integer, validate)


class Failure(Exception):
    def __init__(self, state, result): self.state, self.result = state, result;super().__init__(state)




def unpack(result):
    if result.get('code') != 0: raise runtime.Rejected(json.dumps(result, ensure_ascii=False))
    return result.get('data') or {}


def all_rows(api, endpoint, params):
    rows = []
    for page in range(1, 101):
        data = unpack(api(endpoint, dict(params, page=page, page_size=100)))
        if not isinstance(data.get('list'), list) or not isinstance(data.get('page_info'), dict): raise ValueError('Tencent list/page_info missing; pagination cannot be inferred.')
        rows += data['list']
        if page >= data['page_info'].get('total_page', 1): return rows
    raise ValueError('Tencent pagination exceeds synchronous limits; stop without a partial inventory.')


def allowed_game(row, account):
    return row.get('marketing_carrier_type') == 'MARKETING_CARRIER_TYPE_WECHAT_MINI_GAME' and (row.get('marketing_carrier_detail') or {}).get('marketing_carrier_id') in account['mini_game_ids']


def one(api, account_id, identifier, creative=False, deleted=False, extra_fields=()):
    key = 'dynamic_creative_id' if creative else 'adgroup_id'
    rows = all_rows(api, ('dynamic_creatives' if creative else 'adgroups') + '/get', {
        'account_id': account_id, 'fields': sorted(set(CREATIVE_FIELDS if creative else GROUP_FIELDS) | set(extra_fields)),
        'filtering': [{'field': key, 'operator': 'EQUALS', 'values': [str(identifier)]}], 'is_deleted': deleted})
    if len(rows) != 1 or str(rows[0].get(key)) != str(identifier): raise ValueError('Tencent object identity could not be verified.')
    return rows[0]


def subset(actual, expected):
    if isinstance(expected, dict): return isinstance(actual, dict) and all(k in actual and subset(actual[k], v) for k, v in expected.items())
    if isinstance(expected, list): return isinstance(actual, list) and all(any(subset(a, e) for a in actual) for e in expected)
    return actual == expected


def guard_jumps(value, game):
    if isinstance(value, dict):
        if 'page_type' in value and value['page_type'] != 'PAGE_TYPE_WECHAT_MINI_GAME': raise ValueError('Tencent creative destination must remain the registered WeChat mini-game.')
        if 'mini_game_id' in value and value['mini_game_id'] != game: raise ValueError('Tencent creative points at a different mini-game.')
        if 'page_spec' in value and set(value['page_spec']) - {'wechat_mini_game_spec'}: raise ValueError('Unregistered Tencent landing-page spec.')
        for child in value.values(): guard_jumps(child, game)
    elif isinstance(value, list):
        for child in value: guard_jumps(child, game)


def execute(op, args, *, root, api=None):
    validate(op, args);root = Path(root)
    profile_id = args.get('profile_id')
    if op == 'tencent_status':
        folder = runtime.directory(root, profile_id=profile_id)
        path = folder / 'config.json'
        state_file = folder / 'oauth-state.json'
        state = json.loads(state_file.read_text()) if state_file.exists() else {}
        state_name = state.get('status', 'not_started')
        if state_name == 'issued' and time.time() > state.get('expires_at', 0): state_name = 'expired'
        cfg = runtime.load_config(root, require_accounts=False, profile_id=profile_id) if path.exists() else {}
        return {'code': 0, 'provider': 'tencent', 'api_version': 'v3.0', 'configured': path.exists(),
                'authorized': (folder / 'tokens.json').exists(), 'operations': sorted(OPS),
                'profile_id': profile_id, 'client_id': str(cfg['client_id']) if cfg else None,
                'authorization_status': state_name, 'link_expires_at': state.get('expires_at'),
                'authorization_error_code': state.get('provider_error_code'),
                'authorization_diagnostic': state.get('provider_diagnostic', {}),
                'oauth_token_remote_ip': runtime.token_remote_ip(cfg),
                'oauth_token_host': runtime.token_host(cfg),
                'management_enabled': bool(cfg.get('accounts')), 'managed_account_ids': sorted(cfg.get('accounts', {})),
                'operator_credentials': {k: {'configured': bool(a.get('user_token')),
                    'expires_at': a.get('user_token_expires_at'),
                    'valid': bool(a.get('user_token')) and (a.get('user_token_expires_at') is None or a['user_token_expires_at'] > time.time())}
                    for k, a in cfg.get('accounts', {}).items()},
                'live_account_verification': 'pending', 'create_policy': 'paused_only', 'automatic_pause': False}
    cfg = runtime.load_config(root, require_accounts=op != 'tencent_authorize', profile_id=profile_id)
    folder = runtime.directory(root, cfg)
    if op == 'tencent_authorize': return {'code': 0, 'data': {'authorization_url': runtime.authorize_url(root, cfg)}}
    if op in WRITES and cfg.get('write_enabled') is not True: raise runtime.Rejected('Tencent advertising writes are disabled in the server profile; complete read-only account verification first.')
    account_id = args['account_id'];account = cfg['accounts'].get(str(account_id))
    if account is None: raise runtime.Rejected('Tencent account is outside the configured allowlist; Oceanengine account permissions do not apply.')
    api = api or runtime.API(root, cfg)
    if op == 'tencent_history':
        directory = folder / 'changes'
        records = [json.loads(p.read_text()) for p in directory.glob('*.json')] if directory.exists() else []
        rows = sorted((r for r in records if r['account_id'] == account_id), key=lambda r: r['created_at'], reverse=True)
        return {'code': 0, 'data': {'changes': rows[:args.get('limit', 10)]}}
    if op == 'tencent_funds': return api('funds/get', {'account_id': account_id})
    if op in ('tencent_report', 'tencent_materials', 'tencent_conversions'):
        query = copy.deepcopy(args['query'])
        if not isinstance(query, dict) or {'account_id', 'organization_id', 'access_token', 'user_token'} & set(query): raise ValueError('Query must not override account or credentials.')
        if not isinstance(query.get('fields'), list) or not query['fields']: raise ValueError('Explicit Tencent fields are required; do not invent missing metrics.')
        if op == 'tencent_report':
            allowed = {'level', 'date_range', 'filtering', 'group_by', 'order_by', 'time_line', 'fields'}
            if set(query) - allowed or not {'level', 'date_range', 'group_by'} <= set(query): raise ValueError('Use v3.0 report level/date_range/group_by/fields.')
            if query['level'] not in ('REPORT_LEVEL_ADVERTISER', 'REPORT_LEVEL_ADGROUP', 'REPORT_LEVEL_DYNAMIC_CREATIVE'): raise ValueError('Unsupported report level.')
            calendar = 'hour' if args.get('hourly') else 'date'
            if calendar not in query['group_by']: raise ValueError('Include the report time dimension.')
            dates = query['date_range']
            start, end = date.fromisoformat(dates['start_date']), date.fromisoformat(dates['end_date'])
            if start > end or (args.get('hourly') and start != end): raise ValueError('Invalid Tencent report date range; hourly supports one day.')
            endpoint = 'hourly_reports/get' if args.get('hourly') else 'daily_reports/get'
        elif op == 'tencent_materials':
            allowed = {'fields', 'filtering'};endpoint = ('images' if args['kind'] == 'image' else 'videos') + '/get'
        else: allowed = {'fields', 'filtering'};endpoint = 'conversions/get'
        if set(query) - allowed: raise ValueError('Unsupported query fields.')
        rows = all_rows(api, endpoint, dict(query, account_id=account_id))
        return {'code': 0, 'data': {'list': rows}, 'provider': 'tencent', 'amount_unit': 'fen', 'timezone': 'Asia/Shanghai', 'missing_metrics_are_zero': False}
    if op == 'tencent_inventory':
        groups = all_rows(api, 'adgroups/get', {'account_id': account_id, 'fields': GROUP_FIELDS, 'is_deleted': False})
        groups = [g for g in groups if allowed_game(g, account)]
        creatives = []
        for group in groups:
            children = all_rows(api, 'dynamic_creatives/get', {'account_id': account_id, 'fields': CREATIVE_FIELDS, 'is_deleted': False,
                'filtering': [{'field': 'adgroup_id', 'operator': 'EQUALS', 'values': [str(group['adgroup_id'])]}]})
            if any(str(c.get('adgroup_id')) != str(group['adgroup_id']) for c in children): raise ValueError('Tencent inventory returned creatives from a different parent.')
            creatives += children
        return {'code': 0, 'data': {'account_id': account_id, 'adgroups': groups, 'creatives': creatives}, 'provider': 'tencent', 'amount_unit': 'fen'}
    if op == 'tencent_upload':
        raw = base64.b64decode(args['base64'], validate=True);kind = args['kind']
        params = {'account_id': account_id, 'signature': hashlib.md5(raw).hexdigest()}
        if kind == 'image': params['upload_type'] = 'UPLOAD_TYPE_FILE'
        return api(('images' if kind == 'image' else 'videos') + '/add', params, post=True,
                   upload=('file' if kind == 'image' else 'video_file', args['filename'], raw))
    creative = op.endswith('_creative');creating = op.startswith('tencent_new_');deleting = op.startswith('tencent_delete_')
    key = 'dynamic_creative_id' if creative else 'adgroup_id';endpoint = 'dynamic_creatives' if creative else 'adgroups'
    before = None;wanted = copy.deepcopy(args.get('payload', args.get('patch', {})))
    if creating:
        wanted['configured_status'] = 'AD_STATUS_SUSPEND'
        if creative:
            parent = one(api, account_id, args['adgroup_id'])
            if not allowed_game(parent, account): raise ValueError('Tencent creative parent game is outside scope.')
            wanted['adgroup_id'] = args['adgroup_id']
            required = {'dynamic_creative_name', 'creative_components'}
            game = parent['marketing_carrier_detail']['marketing_carrier_id']
            if isinstance(wanted.get('creative_components'), dict):
                wanted['creative_components'].setdefault('main_jump_info', [{'value': {'page_type': 'PAGE_TYPE_WECHAT_MINI_GAME',
                    'page_spec': {'wechat_mini_game_spec': {'mini_game_id': game}}}}])
                guard_jumps(wanted['creative_components'], game)
        else:
            required = {'adgroup_name', 'marketing_goal', 'marketing_carrier_type', 'marketing_carrier_detail',
                        'marketing_asset_outer_spec', 'begin_date', 'end_date', 'time_series', 'daily_budget', 'optimization_goal'}
            if not allowed_game(wanted, account): raise ValueError('New Tencent marketing unit must use an allowed WeChat game.')
            outer = wanted.get('marketing_asset_outer_spec') or {}
            if outer.get('marketing_target_type') != 'MARKETING_TARGET_TYPE_WECHAT_MINI_GAME' or outer.get('marketing_asset_outer_id') != wanted['marketing_carrier_detail']['marketing_carrier_id']:
                raise ValueError('Tencent carrier and promoted game must match.')
        if not required <= set(wanted): raise ValueError('Missing required Tencent creation fields: ' + ','.join(sorted(required - set(wanted))))
        name_key = 'dynamic_creative_name' if creative else 'adgroup_name'
        existing = all_rows(api, endpoint + '/get', {'account_id': account_id, 'fields': [key, name_key], 'is_deleted': False,
            'filtering': [{'field': name_key, 'operator': 'EQUALS', 'values': [wanted[name_key]]}]})
        if existing: raise ValueError('Tencent object name already exists; inspect it instead of creating a duplicate.')
        for file in (folder / 'changes').glob('*.json'):
            previous = json.loads(file.read_text())
            if previous['account_id'] == account_id and previous['op'] == op and previous['desired'].get(name_key) == wanted[name_key] and previous['status'] in ('prepared', 'uncertain'):
                raise Failure('uncertain', {'message': 'Previous creation is unresolved; do not post it again.', 'change_id': previous['id']})
    else:
        before = one(api, account_id, args[key], creative)
        parent = one(api, account_id, int(before['adgroup_id'])) if creative else before
        if not allowed_game(parent, account): raise ValueError('Tencent object is outside the configured account/game scope.')
        if creative: guard_jumps(wanted.get('creative_components', {}), parent['marketing_carrier_detail']['marketing_carrier_id'])
        if deleting:
            if before.get('configured_status') != 'AD_STATUS_SUSPEND': raise ValueError('Pause the Tencent object before deletion.')
            if not creative:
                children = all_rows(api, 'dynamic_creatives/get', {'account_id': account_id, 'fields': ['dynamic_creative_id', 'adgroup_id'], 'is_deleted': False,
                    'filtering': [{'field': 'adgroup_id', 'operator': 'EQUALS', 'values': [str(args[key])]}]})
                if children: raise ValueError('Delete remaining Tencent creatives before their parent.')
        wanted[key] = args[key]
    change_id = uuid.uuid4().hex;record_path = folder / 'changes' / (change_id + '.json')
    record = {'id': change_id, 'op': op, 'account_id': account_id, 'created_at': time.time(), 'before': before,
              'desired': wanted, 'status': 'prepared'}
    runtime.save(record_path, record)
    try:
        result = api(endpoint + ('/add' if creating else '/delete' if deleting else '/update'), dict(wanted, account_id=account_id), post=True)
        record['upstream'] = result
        if result.get('code') != 0:
            record['status'] = 'rejected';runtime.save(record_path, record);return dict(result, change_id=change_id)
        identifier = int(unpack(result).get(key, args.get(key, 0)));integer(identifier)
        after = one(api, account_id, identifier, creative, deleted=deleting, extra_fields=set(wanted) - {'marketing_asset_outer_spec'})
        record['after'] = after
        expected = {'is_deleted': True} if deleting else {k: v for k, v in wanted.items() if k not in ('marketing_asset_outer_spec',)}
        verified = subset(after, expected)
        record['status'] = 'verified' if verified else 'mismatch';runtime.save(record_path, record)
        if not verified: raise Failure('mismatch', {'message': 'Tencent field readback mismatch.', 'change_id': change_id})
        return {'code': 0, 'data': {key: identifier, 'verified': True, 'after': after}, 'change_id': change_id}
    except Failure: raise
    except Exception:
        record['status'] = 'uncertain';runtime.save(record_path, record)
        raise Failure('uncertain', {'message': 'Tencent result uncertain; inspect original job, history and live object before retrying.', 'change_id': change_id}) from None
