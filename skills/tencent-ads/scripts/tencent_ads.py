"""Tencent v3.0 chat-operation client. The gateway alone holds Tencent OAuth credentials."""
import argparse
import base64
import getpass
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.error import URLError, HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
import uuid

import tencent_schema as schema

DEFAULT_CONFIG = Path.home() / '.config/tencent-ads/connection.json'
OWNER_PAIRING = Path(__file__).resolve().parent / '.secrets/remote-management.json'
if not DEFAULT_CONFIG.exists() and OWNER_PAIRING.exists(): DEFAULT_CONFIG = OWNER_PAIRING
STATE = Path(os.environ.get('TENCENT_ADS_HOME', str(Path.cwd() / '.tencent-ads'))).expanduser()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as f: json.dump(value, f, ensure_ascii=False, indent=2)
    temp.replace(path)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs): return None


class Gateway:
    def __init__(self, path=None):
        path = Path(path or os.environ.get('TENCENT_MANAGEMENT_CONFIG', str(DEFAULT_CONFIG))).expanduser()
        if not path.exists(): raise ValueError('Tencent connection missing; run configure. If the same team gateway is already configured for Oceanengine, explicitly use configure --from-oceanengine-config PATH. Do not paste keys into chat.')
        if os.name == 'posix' and path.stat().st_mode & 0o077: raise ValueError('Gateway profile permissions must be 0600.')
        self.cfg = json.loads(path.read_text());self.validate(self.cfg)

    @staticmethod
    def validate(cfg):
        url = urlsplit(cfg.get('base_url', ''))
        if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment or url.path not in ('', '/'):
            raise ValueError('Use an HTTPS gateway origin without credentials or path.')
        if not re.fullmatch('[A-Fa-f0-9]{64}', str(cfg.get('key', ''))): raise ValueError('Management key must have64 hexadecimal characters.')
        if cfg.get('access_mode', 'read_only') not in ('read_only', 'operator'): raise ValueError('Use read_only or operator.')

    def request(self, route, body):
        if route not in ('jobs', 'job'): raise ValueError('Unsupported gateway route.')
        if route == 'jobs':
            schema.validate(body['op'], body['args'])
            if body['op'] in (schema.WRITES | schema.CONFIG_WRITES) and self.cfg.get('access_mode', 'read_only') != 'operator':
                raise PermissionError('Profile is read_only; configure operator only for an authorized operator.')
        path = '/manage/v1/' + route
        raw = json.dumps(body, ensure_ascii=False, separators=(',', ':')).encode()
        if len(raw) > 72 * 1024 * 1024: raise ValueError('Gateway request exceeds72MiB.')
        stamp, nonce = str(int(time.time())), uuid.uuid4().hex
        message = ('POST\n' + path + '\n' + stamp + '\n' + nonce + '\n' + hashlib.sha256(raw).hexdigest()).encode()
        signature = hmac.new(bytes.fromhex(self.cfg['key']), message, hashlib.sha256).hexdigest()
        req = Request(self.cfg['base_url'].rstrip('/') + path, data=raw, method='POST', headers={
            'Content-Type': 'application/json', 'X-Manage-Time': stamp, 'X-Manage-Nonce': nonce, 'X-Manage-Signature': signature})
        with build_opener(NoRedirect()).open(req, timeout=45) as response: return json.load(response)


def wait(client, job_id, timeout=35):
    deadline = time.monotonic() + timeout
    failures = 0
    while True:
        try:
            row = client.request('job', {'job_id': job_id})
        except (TimeoutError, ConnectionError, URLError) as error:
            if isinstance(error,HTTPError) and error.code not in (429,500,502,503,504): raise
            failures += 1
            if failures >= 3 or time.monotonic() >= deadline:
                raise RuntimeError('Tencent job status unavailable; inspect original job '+job_id+'; do not submit a new operation.') from None
            time.sleep(.5);continue
        if row['status'] not in ('queued', 'running') or time.monotonic() >= deadline: return row
        time.sleep(.5)


def read(client, op, args):
    if op not in schema.READS: raise ValueError('Read entrypoint cannot submit a mutation.')
    job = client.request('jobs', {'op': op, 'args': args, 'idempotency_key': 'tencent-read-' + uuid.uuid4().hex})
    row = (wait(client, job['job_id'], timeout=180) if op == 'tencent_discover_accounts' else wait(client, job['job_id']));result = row.get('result') or {}
    if row['status'] != 'done' or result.get('code') != 0: raise RuntimeError('Tencent read failed; inspect job ' + job['job_id'] + '. Missing data is not zero.')
    return result


def validate_steps(steps):
    for index, step in enumerate(steps):
        if not isinstance(step, dict) or not {'op', 'args'} <= step.keys() or step.keys() - {'op', 'args', 'adgroup_from'}:
            raise ValueError('Each Tencent step requires op and args.')
        args = step['args']
        if 'adgroup_from' in step:
            source = step['adgroup_from']
            if (step['op'] != 'tencent_new_creative' or not isinstance(args, dict)
                    or 'adgroup_id' in args or type(source) is not int or not 1 <= source <= index):
                raise ValueError('adgroup_from must be an earlier, one-based batch step and replaces adgroup_id.')
            parent = steps[source - 1]
            if (parent['op'] != 'tencent_new_adgroup'
                    or any(parent['args'].get(key) != args.get(key) for key in ('account_id', 'profile_id'))):
                raise ValueError('adgroup_from must point to a new marketing unit in the same account and profile.')
            schema.validate(step['op'], dict(args, adgroup_id=1))
        else:
            schema.validate(step['op'], args)


def run(client, steps, run_id, state=STATE):
    if not re.fullmatch('[A-Za-z0-9_-]{8,64}', run_id): raise ValueError('Use an8–64 character stable run-id.')
    validate_steps(steps)
    path = state / 'operations' / run_id / 'receipt.json'
    digest = hashlib.sha256(json.dumps(steps, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    binding = hashlib.sha256(client.cfg['base_url'].rstrip('/').encode()).hexdigest()
    receipt = json.loads(path.read_text()) if path.exists() else {'provider': 'tencent', 'digest': digest, 'gateway': binding, 'steps': steps, 'jobs': [], 'status': 'prepared'}
    if receipt.get('provider') != 'tencent' or receipt['digest'] != digest or receipt['gateway'] != binding:
        raise ValueError('Saved Tencent operation belongs to different parameters or a different gateway.')
    save(path, receipt)
    for i, step in enumerate(steps):
        if len(receipt['jobs']) == i: receipt['jobs'].append({})
        entry = receipt['jobs'][i]
        if entry.get('verified'): continue
        if 'id' not in entry:
            args = step['args']
            if 'adgroup_from' in step:
                parent = receipt['jobs'][step['adgroup_from'] - 1]
                identifier = parent['response']['result']['data'].get('adgroup_id')
                schema.integer(identifier)
                args = dict(args, adgroup_id=identifier)
            started = client.request('jobs', {'op': step['op'], 'args': args,
                                              'idempotency_key': 'tencent9-' + run_id + '-' + str(i)})
            entry['id'] = started['job_id'];save(path, receipt)
        row = wait(client, entry['id']);entry['response'] = row;receipt['status'] = row['status'];save(path, receipt)
        if row['status'] in ('queued', 'running'): return receipt
        result = row.get('result') or {}
        if row['status'] != 'done' or result.get('code') != 0:
            if row['status'] == 'done':
                receipt['status'] = 'rejected' if result.get('code') is not None else 'uncertain'
                save(path, receipt)
            raise RuntimeError('Tencent operation stopped; inspect original receipt/job/history before retrying.')
        if step['op'] not in ('tencent_upload', 'tencent_authorize', 'tencent_operator_authorize') and not result.get('data', {}).get('verified'):
            receipt['status'] = 'unverified';save(path, receipt)
            raise RuntimeError('Tencent write has no verified readback.')
        if step['op'] == 'tencent_upload' and not any(result.get('data', {}).get(k) for k in ('image_id', 'video_id')):
            receipt['status'] = 'unverified';save(path, receipt)
            raise RuntimeError('Tencent upload returned no material identifier.')
        entry['verified'] = True;save(path, receipt)
    receipt['status'] = 'done';save(path, receipt)
    return receipt


def connection_from_oceanengine(path, access='read_only'):
    """Explicitly pair to the same team gateway, without importing platform scope."""
    source = Gateway(path).cfg
    cfg = {'base_url': source['base_url'], 'key': source['key'], 'access_mode': access}
    Gateway.validate(cfg)
    return cfg


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--account', type=int, help='Explicit Tencent account ID; never an Oceanengine alias.')
    parser.add_argument('--profile', help='Explicit isolated Tencent authorization identity.')
    parser.add_argument('--run-id');parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--config', type=Path)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('status', 'authorize', 'funds', 'history'): sub.add_parser(name)
    sub.add_parser('inventory').add_argument('--delivery', choices=['all', 'standard', 'smart'], default='all')
    p = sub.add_parser('accounts');p.add_argument('--ids', type=int, nargs='+');p.add_argument('--limit',type=int,default=10)
    p = sub.add_parser('register-accounts');p.add_argument('--manifest', type=Path, required=True);p.add_argument('--operator')
    p = sub.add_parser('bind-operator');p.add_argument('--operator', required=True);p.add_argument('--ids', type=int, nargs='+', required=True)
    sub.add_parser('operator-authorize').add_argument('--operator', required=True)
    c = sub.add_parser('configure')
    origin = c.add_mutually_exclusive_group(required=True)
    origin.add_argument('--base-url')
    origin.add_argument('--from-oceanengine-config', type=Path, help='Explicitly reuse the same team gateway connection; no account/OAuth scope is copied.')
    c.add_argument('--key-file', type=Path)
    c.add_argument('--access', choices=['read_only', 'operator'], default='read_only');c.add_argument('--overwrite', action='store_true')
    for name in ('new-adgroup', 'new-smart', 'new-creative'):
        p = sub.add_parser(name);p.add_argument('--args-file', type=Path, required=True)
        if name in ('new-adgroup', 'new-smart'): p.add_argument('--mode', choices=['IAA', 'IAP'], required=True)
        else: p.add_argument('--adgroup-id', type=int, required=True)
    for name in ('update-adgroup', 'update-creative'):
        p = sub.add_parser(name);p.add_argument('id', type=int);p.add_argument('--patch-file', type=Path, required=True)
    for name in ('start', 'pause', 'delete'):
        p = sub.add_parser(name);p.add_argument('level', choices=['adgroup', 'creative']);p.add_argument('id', type=int)
    for name in ('budget', 'bid', 'roi'):
        p = sub.add_parser(name);p.add_argument('id', type=int);p.add_argument('value')
    p = sub.add_parser('schedule');p.add_argument('id', type=int);p.add_argument('--mask', required=True)
    p = sub.add_parser('dates');p.add_argument('id', type=int);p.add_argument('--start');p.add_argument('--end', required=True, help='YYYY-MM-DD, or an empty string for long-term.')
    p = sub.add_parser('report');p.add_argument('--query-file', type=Path, required=True);p.add_argument('--hourly', action='store_true')
    p = sub.add_parser('conversions');p.add_argument('--query-file', type=Path, required=True)
    p = sub.add_parser('materials');p.add_argument('kind', choices=['image', 'video']);p.add_argument('--query-file', type=Path, required=True)
    p = sub.add_parser('upload');p.add_argument('kind', choices=['image', 'video']);p.add_argument('file', type=Path)
    p = sub.add_parser('batch-create');p.add_argument('--manifest', type=Path, required=True)
    sub.add_parser('resume').add_argument('saved_run_id')
    args = parser.parse_args()
    if args.command == 'configure':
        target = args.config or Path(os.environ.get('TENCENT_MANAGEMENT_CONFIG', str(Path.home() / '.config/tencent-ads/connection.json')))
        if target.exists() and not args.overwrite: raise ValueError('Configuration exists; inspect it before explicit --overwrite.')
        if args.from_oceanengine_config:
            if args.key_file: raise ValueError('Do not combine connection import with --key-file.')
            if args.from_oceanengine_config.expanduser().resolve() == target.expanduser().resolve():
                raise ValueError('Tencent destination must not overwrite the Oceanengine source configuration.')
            cfg = connection_from_oceanengine(args.from_oceanengine_config, args.access)
        else:
            key = args.key_file.read_text().strip() if args.key_file else getpass.getpass('Management key (hidden): ').strip()
            cfg = {'base_url': args.base_url, 'key': key, 'access_mode': args.access}
        Gateway.validate(cfg);save(target.expanduser(), cfg)
        print('Tencent local gateway profile saved with0600 permissions. No advertising changed.');return
    client = Gateway(args.config)
    selection = {'profile_id': args.profile} if args.profile else {}
    if args.command == 'status': print(json.dumps(read(client, 'tencent_status', selection), ensure_ascii=False, indent=2));return
    if args.command == 'accounts':
        payload=dict(selection)
        if args.ids: payload['account_ids']=args.ids
        if not 1 <= args.limit <= 100: raise ValueError('Use discovery limit 1-100.')
        result=read(client, 'tencent_discover_accounts', payload)
        details=STATE/('discovered-accounts-'+(args.profile or 'default')+'.json');save(details,result)
        rows=result['data']['accounts']
        print(json.dumps({'accounts':rows[:args.limit],'total':len(rows),'details_file':str(details.resolve()),
            'discovery_grants_management':False,'discovery_source':result['data'].get('discovery_source')},ensure_ascii=False,indent=2));return
    if args.command in ('register-accounts','bind-operator','operator-authorize'):
        if not args.profile: raise ValueError('Select an explicit Tencent profile for onboarding.')
        payload=dict(selection)
        if args.command == 'register-accounts':
            payload['accounts']=json.loads(args.manifest.read_text())
            if args.operator:payload['operator_id']=args.operator
        else:
            payload['operator_id']=args.operator
            if args.command == 'bind-operator':payload['account_ids']=args.ids
        op={'register-accounts':'tencent_register_accounts','bind-operator':'tencent_bind_operator','operator-authorize':'tencent_operator_authorize'}[args.command]
        schema.validate(op,payload)
        if args.dry_run:
            print(json.dumps({'dry_run':True,'op':op,'args':payload,'advertising_settings_changed':False},ensure_ascii=False,indent=2));return
        run_id=args.run_id or time.strftime('onboard-%Y%m%d-%H%M%S-')+uuid.uuid4().hex[:8]
        receipt=run(client,[{'op':op,'args':payload}],run_id)
        print(json.dumps({'status':receipt['status'],'jobs':[j.get('id') for j in receipt['jobs']],
            'receipt_file':str((STATE/'operations'/run_id/'receipt.json').resolve())},ensure_ascii=False,indent=2));return
    if args.command == 'resume':
        if not re.fullmatch('[A-Za-z0-9_-]{8,64}', args.saved_run_id): raise ValueError('Invalid saved run-id.')
        receipt = json.loads((STATE / 'operations' / args.saved_run_id / 'receipt.json').read_text())
        if args.account is not None and any(s['args'].get('account_id', args.account) != args.account for s in receipt['steps']): raise ValueError('Saved Tencent account differs.')
        if args.profile is not None and any(s['args'].get('profile_id') != args.profile for s in receipt['steps']): raise ValueError('Saved Tencent authorization profile differs.')
        print(json.dumps(run(client, receipt['steps'], args.saved_run_id), ensure_ascii=False, indent=2));return
    if args.command != 'authorize' and args.account is None: raise ValueError('Select an explicit Tencent --account ID.')
    account = dict(selection, account_id=args.account);command = args.command
    if command in ('inventory', 'funds', 'history', 'report', 'materials', 'conversions'):
        payload = dict(account)
        if command == 'inventory': payload['delivery'] = args.delivery
        if hasattr(args, 'query_file'): payload['query'] = json.loads(args.query_file.read_text())
        if command == 'report': payload['hourly'] = args.hourly
        if command == 'materials': payload['kind'] = args.kind
        result = read(client, 'tencent_' + command, payload)
        save(STATE / ('latest-' + command + '-' + (args.profile + '-' if args.profile else '') + str(args.account) + '.json'), result)
        print(json.dumps(result, ensure_ascii=False, indent=2));return
    steps = []
    if command == 'authorize': op, payload = 'tencent_authorize', dict(selection)
    elif command.startswith('new-'):
        op = 'tencent_new_adgroup' if command == 'new-smart' else 'tencent_' + command.replace('-', '_')
        payload = dict(account, payload=json.loads(args.args_file.read_text()))
        if command in ('new-adgroup', 'new-smart'): payload['monetization'] = args.mode
        if command == 'new-smart' and payload['payload'].get('smart_delivery_platform') != schema.SMART_PLATFORM:
            raise ValueError('new-smart requires an explicit supported smart platform and scene; ordinary fallback is forbidden.')
        if command == 'new-creative': payload['adgroup_id'] = args.adgroup_id
    elif command == 'upload':
        raw = args.file.read_bytes();safe = 'material-' + hashlib.sha256(raw).hexdigest()[:12] + args.file.suffix.lower()
        op, payload = 'tencent_upload', dict(account, kind=args.kind, filename=safe, base64=base64.b64encode(raw).decode())
    elif command == 'batch-create':
        steps = json.loads(args.manifest.read_text())
        if not isinstance(steps, list) or not 1 <= len(steps) <= 100: raise ValueError('Provide1–100 creation steps.')
        for step in steps:
            if (not isinstance(step, dict) or not isinstance(step.get('args'), dict)
                    or step.get('op') not in ('tencent_new_adgroup', 'tencent_new_creative')
                    or step['args'].get('account_id') != args.account): raise ValueError('Creation batch must stay in one explicit Tencent account.')
            if step['args'].get('profile_id') != args.profile: raise ValueError('Creation batch must stay in one explicit Tencent authorization profile.')
    else:
        creative = command.endswith('creative') or getattr(args, 'level', '') == 'creative'
        op = 'tencent_' + ('delete_' if command == 'delete' else 'update_') + ('creative' if creative else 'adgroup')
        payload = dict(account, **{'dynamic_creative_id' if creative else 'adgroup_id': args.id})
        if command != 'delete':
            if command.startswith('update-'): patch = json.loads(args.patch_file.read_text())
            elif command in ('start', 'pause'): patch = {'configured_status': 'AD_STATUS_NORMAL' if command == 'start' else 'AD_STATUS_SUSPEND'}
            elif command in ('budget', 'bid'):
                patch = {'daily_budget' if command == 'budget' else 'bid_amount': schema.money(args.value)}
                if command == 'bid':
                    inv = read(client, 'tencent_inventory', account)['data']
                    group = next((r for r in inv['adgroups'] if int(r['adgroup_id']) == args.id), None)
                    if group is None: raise ValueError('Tencent marketing unit not found in configured game scope.')
                    if schema.is_smart(group): patch = schema.smart_scene_patch(group, bid_yuan=args.value)
            elif command == 'schedule': patch = {'time_series': args.mask}
            elif command == 'dates':
                patch = {'end_date': args.end}
                if args.start: patch['begin_date'] = args.start
            elif command == 'roi':
                inv = read(client, 'tencent_inventory', account)['data']
                group = next((r for r in inv['adgroups'] if int(r['adgroup_id']) == args.id), None)
                if group is None: raise ValueError('Tencent marketing unit not found in configured game scope.')
                if schema.is_smart(group):
                    patch = schema.smart_scene_patch(group, roi_value=args.value)
                else:
                    spec = group.get('deep_conversion_spec') or {};fields = [k for k in ('deep_conversion_worth_spec', 'deep_conversion_worth_advanced_spec') if spec.get(k)]
                    if len(fields) != 1: raise ValueError('Existing ROI goal is ambiguous or absent; inspect conversion configuration first.')
                    field = fields[0];patch = {'deep_conversion_spec': {field: {'goal': spec[field]['goal'], 'expected_roi': schema.ratio(args.value)}}}
                    if spec.get('deep_conversion_type'): patch['deep_conversion_spec']['deep_conversion_type'] = spec['deep_conversion_type']
            else: raise ValueError('Unsupported Tencent command.')
            payload['patch'] = patch
    if not steps: steps = [{'op': op, 'args': payload}]
    for step in steps:
        payload = step['args'].get('payload')
        if step['op'] in ('tencent_new_adgroup', 'tencent_new_creative') and isinstance(payload, dict):
            payload['configured_status'] = 'AD_STATUS_SUSPEND'
    validate_steps(steps)
    run_id = args.run_id or time.strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:8]
    if args.dry_run:
        safe_steps = [{**s, 'args': {k: v for k, v in s['args'].items() if k != 'base64'}} for s in steps]
        print(json.dumps({'provider': 'tencent', 'dry_run': True, 'run_id': run_id, 'steps': safe_steps}, ensure_ascii=False, indent=2));return
    receipt = run(client, steps, run_id)
    print(json.dumps({'run_id': run_id, 'status': receipt['status'], 'jobs': receipt['jobs']}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try: main()
    except Exception as error: print(type(error).__name__ + ': ' + str(error), file=sys.stderr);raise SystemExit(1)
