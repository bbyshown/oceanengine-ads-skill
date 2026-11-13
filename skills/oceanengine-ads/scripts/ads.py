"""Reusable chat-to-ads command entrypoint. All writes use signed, resumable jobs."""
import argparse
import base64
import copy
import hashlib
import json
from pathlib import Path
import re
import sys
import time
import uuid

import operation_output
import remote_client
import creation_schema as creation
import settings

ROOT = settings.workspace_state()
RUNS = ROOT / 'data/operations'
PRIMARY = 0
CLIENT = remote_client


class SelectedClient:
    def __init__(self, account_id):self.account_id=account_id
    def submit(self, op, args, key):return remote_client.submit(op,dict(args,account_id=self.account_id),key)
    def request(self, route, args):return remote_client.request(route,args)


def select_account(ref=None):
    return settings.select_account(ref)


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2));temp.chmod(0o600);temp.replace(path)


def wait(job_id, seconds=25, client=remote_client):
    deadline = time.monotonic() + seconds
    while True:
        result = client.request('job', {'job_id': job_id})
        if result['status'] not in ('queued', 'running') or time.monotonic() >= deadline:return result
        time.sleep(0.25)


def read(op, args=None, client=None):
    client=client or CLIENT
    started = client.submit(op, args or {}, 'read-' + uuid.uuid4().hex)
    row = wait(started['job_id'], client=client)
    r = row.get('result') or {}
    if row['status'] != 'done' or r.get('code', 0) != 0:
        path = ROOT / 'data/operations/read-errors' / (started['job_id'] + '.json')
        save(path, row)
        details = {key: r[key] for key in ('code', 'message', 'error') if key in r}
        raise RuntimeError('Read failed; job ' + started['job_id'] + ': '
                           + json.dumps(operation_output.visible(details), ensure_ascii=False)
                           + '; details: ' + str(path))
    return r


def resolve(inventory, ref):
    rows = inventory['projects']
    text = str(ref).upper()
    if re.fullmatch(r'V?\d{1,2}', text):
        alias = 'V' + text.lstrip('V').zfill(2)
        found = [r for r in rows if re.search(r'(?:^|_)' + alias + r'(?:_|$)', r['name'].upper())]
    elif text.isdecimal():found = [r for r in rows if r['project_id'] == int(text)]
    else:found = [r for r in rows if r['name'] == str(ref)]
    if len(found) != 1:raise ValueError('Project must match exactly one live project: ' + str(ref))
    if found[0]['project_id'] not in inventory['managed_project_ids']:raise ValueError('Project is outside the managed game scope.')
    return found[0]


def ads_for(inventory, projects):
    return [r for r in inventory['ads'] if r['project_id'] in projects]


def merge_ad_patch(ad, patch):
    """Material updates replace the platform section; retain its required fields."""
    patch=copy.deepcopy(patch)
    if 'promotion_materials' not in patch:return patch
    old=ad.get('promotion_materials') or {};materials={}
    for key,fields in [('video_material_list',{'image_mode','video_id','video_cover_id','video_hp_visibility'}),
                       ('title_material_list',{'title'})]:
        if key in old:materials[key]=[{k:v for k,v in row.items() if k in fields} for row in old[key]]
    for key,fields in [('mini_program_info',{'app_id','url'}),
                       ('product_info',{'product_name_type','product_image_type','product_selling_point_type','titles','image_ids','selling_points'})]:
        if key in old:materials[key]={k:v for k,v in old[key].items() if k in fields}
    if 'external_url_material_list' in old:
        materials['external_url_material_list']=[u.split('?',1)[0] for u in old['external_url_material_list']]
    if 'call_to_action_buttons' in old:materials['call_to_action_buttons']=copy.deepcopy(old['call_to_action_buttons'])
    for key,value in patch['promotion_materials'].items():
        if key in ('product_info','mini_program_info') and isinstance(value,dict):materials.setdefault(key,{}).update(value)
        else:materials[key]=value
    patch['promotion_materials']=materials
    return patch


def status_steps(inventory, project_ids, enabled, include_ads=True):
    """Pause parent first; enable ads before parent. Preserve unrelated switches."""
    steps = []
    def add(op, field, ids, status):
        for offset in range(0, len(ids), 20):steps.append({'op': op, 'args': {field: ids[offset:offset + 20], 'opt_status': status}})
    ps = [r['project_id'] for r in inventory['projects'] if r['project_id'] in project_ids and r['opt_status'] != ('ENABLE' if enabled else 'DISABLE')]
    children = ads_for(inventory, project_ids)
    aa = [r['promotion_id'] for r in children if r['opt_status'] != ('ENABLE' if enabled else 'DISABLE')]
    if enabled and not children:raise ValueError('Cannot start a project without any ad.')
    if not enabled:add('set_project_status', 'project_ids', ps, 'DISABLE')
    if include_ads:add('set_ad_status', 'promotion_ids', aa, 'ENABLE' if enabled else 'DISABLE')
    if enabled:add('set_project_status', 'project_ids', ps, 'ENABLE')
    return steps


def make_plan(inventory, action, refs=None, value=None, options=None):
    options = options or {}
    targets = [resolve(inventory, r)['project_id'] for r in (refs or [])]
    if len(set(targets)) != len(targets):raise ValueError('Duplicate project target.')
    steps, checks = [], {}
    if action == 'account-budget':steps = [{'op': 'set_account_budget', 'args': {'budget': value}}]
    elif action in ('budget', 'roi', 'schedule', 'dates', 'edit-ad', 'create-ad'):
        if len(targets) != 1:raise ValueError('Exactly one project is required.')
        p = targets[0]
        if action == 'budget':steps = [{'op': 'set_project_budget', 'args': {'project_ids': [p], 'budget': value}}]
        elif action == 'roi':steps = [{'op': 'set_project_bid', 'args': {'project_ids': [p], 'roi_goal': value}}]
        elif action == 'schedule':steps = [{'op': 'set_project_schedule', 'args': {'project_ids': [p], 'schedule_time': value}}]
        elif action == 'dates':steps = [{'op': 'set_project_dates', 'args': dict(options, project_ids=[p])}]
        elif action == 'create-ad':steps = [{'op': 'create_paused_ad', 'args': dict(options, project_id=p)}]
        else:
            children = ads_for(inventory, [p])
            promotion = options.get('promotion_id')
            if promotion is None and len(children) == 1:promotion = children[0]['promotion_id']
            if promotion not in {a['promotion_id'] for a in children}:raise ValueError('Specify an ad belonging to this project.')
            ad=next(a for a in children if a['promotion_id']==promotion)
            steps = [{'op': 'update_ad', 'args': {'promotion_id': promotion, 'patch': merge_ad_patch(ad,options['patch'])}}]
    elif action in ('start', 'pause'):
        if not targets:raise ValueError('Project target required.')
        steps = status_steps(inventory, targets, action == 'start')
        checks['project_status'] = {str(i): 'ENABLE' if action == 'start' else 'DISABLE' for i in targets}
        checks['ad_status'] = {str(a['promotion_id']): 'ENABLE' if action == 'start' else 'DISABLE' for a in ads_for(inventory, targets)}
    elif action == 'switch':
        if len(targets) != 2 or targets[0] == targets[1]:raise ValueError('Use distinct source and destination projects.')
        old, new = targets
        steps = status_steps(inventory, [old], False) + status_steps(inventory, [new], True)
        checks['project_status'] = {str(old): 'DISABLE', str(new): 'ENABLE'}
        checks['ad_status'] = {str(a['promotion_id']): 'DISABLE' if a['project_id'] == old else 'ENABLE' for a in ads_for(inventory, targets)}
    elif action in ('delete', 'keep-only'):
        if not targets:raise ValueError('Project target required.')
        if action == 'keep-only':
            if len(targets) != 1:raise ValueError('Keep exactly one project.')
            keep = targets[0]
            targets = [p['project_id'] for p in inventory['projects'] if p['project_id'] != keep]
            checks['keep_only'] = keep
        if not set(targets) <= set(inventory['managed_project_ids']):raise ValueError('Cleanup includes unregistered projects; stop before changing anything.')
        steps = status_steps(inventory, targets, False)
        aids = [r['promotion_id'] for r in ads_for(inventory, targets)]
        # Projects adopted from an existing account were never created by this tool.
        # They are editable, but removing them is a separate decision: keep-only must
        # not sweep them away merely because they became manageable.
        adopted = sorted(inventory.get('adopted_project_ids', []))
        if adopted and options.get('confirm_adopted') is not True:
            raise ValueError('This action would delete ' + str(len(adopted)) + ' project(s) adopted from the existing account ('
                             + ', '.join(str(i) for i in adopted)
                             + '). Resend with --confirm-adopted if that is intended.')
        for op, field, ids in [('delete_ads', 'promotion_ids', aids), ('delete_projects', 'project_ids', targets)]:
            for offset in range(0, len(ids), 20):
                extra = {'confirm_adopted': True} if op == 'delete_projects' and adopted else {}
                steps.append({'op': op, 'args': dict({field: ids[offset:offset + 20]}, **extra)})
        checks.update(deleted_project_ids=targets, deleted_promotion_ids=aids)
    else:raise ValueError('Unknown command: ' + action)
    if checks:steps.append({'op': 'inventory', 'args': {}, 'checks': checks})
    return {'action': action, 'steps': steps, 'before_inventory': inventory}


def verify_inventory(data, checks):
    ps = {r['project_id']: r for r in data['projects']};aa = {r['promotion_id']: r for r in data['ads']}
    for key, rows in [('project_status', ps), ('ad_status', aa)]:
        for key_id, status in checks.get(key, {}).items():
            if rows.get(int(key_id), {}).get('opt_status') != status:raise RuntimeError('Final switch readback mismatch.')
    if set(checks.get('deleted_project_ids', [])) & set(ps):raise RuntimeError('Some projects were not deleted.')
    if set(checks.get('deleted_promotion_ids', [])) & set(aa):raise RuntimeError('Some ads were not deleted.')
    if 'keep_only' in checks and set(ps) != {checks['keep_only']}:raise RuntimeError('Account contains unexpected remaining projects.')


def creation_plan(items, run_id, operation='new_campaign'):
    if not isinstance(items, list) or not 1 <= len(items) <= 100:raise ValueError('Create 1–100 entries per plan.')
    steps, names = [], set()
    for index, item in enumerate(items):
        args = dict(item, creation_id=run_id + '-' + str(index))
        creation.validate(operation, args)  # Validate the entire batch before any write.
        name = ('project', args['project']['name']) if 'project' in args else ('ad', args['project_id'], args['ad']['name'])
        if name in names:raise ValueError('Duplicate names inside this creation batch.')
        names.add(name);steps.append({'op': operation, 'args': args})
    return {'action': operation, 'steps': steps, 'create_paused_only': True}


def batch_items(rows, budget, roi=None, roi_start=None, roi_end=None, prefix='', product_image_id=None):
    if not isinstance(rows, list) or not 1 <= len(rows) <= 100:raise ValueError('Manifest must contain 1–100 ad rows.')
    if (roi_start is None) != (roi_end is None) or (roi is not None and roi_start is not None):raise ValueError('Choose one ROI value or a complete ROI range.')
    if roi is None and roi_start is None and any('roi_goal' not in row for row in rows):raise ValueError('Every project requires an explicit ROI coefficient.')
    output = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) - {'name','video_id','cover_id','titles','orientation','budget','roi_goal','product_image_id','videos','roi_mode','image_material_list','carousel_material_list'}:raise ValueError('Unsupported manifest fields.')
        goal = row.get('roi_goal', roi if roi_start is None else round(roi_start + (roi_end - roi_start) * i / max(len(rows) - 1, 1), 4))
        name = prefix + row['name']
        ad = {k: row[k] for k in ('video_id','cover_id','titles','orientation','product_image_id','videos','image_material_list','carousel_material_list') if k in row};ad['name'] = name + '_广告'
        if 'product_image_id' not in ad and product_image_id is not None:ad['product_image_id']=product_image_id
        project = {'name': name, 'budget': row.get('budget', budget), 'roi_goal': goal}
        if 'roi_mode' in row:project['roi_mode'] = row['roi_mode']
        output.append({'project': project, 'ad': ad})
    return output


def execute_plan(plan, run_id, *, directory=RUNS, client=None):
    client=client or CLIENT
    selected=getattr(client,'account_id',PRIMARY)
    if not re.fullmatch('[A-Za-z0-9_-]{8,64}', run_id):raise ValueError('run-id must be 8–64 safe characters.')
    path = directory / run_id / 'receipt.json'
    digest = hashlib.sha256(json.dumps(plan, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    if path.exists():
        receipt = json.loads(path.read_text())
        if receipt.get('account_id',PRIMARY)!=selected:raise ValueError('Saved operation belongs to another account.')
        if receipt['digest'] != digest:raise ValueError('Run ID already belongs to a different plan.')
    else:
        receipt = {'run_id': run_id, 'account_id':selected, 'digest': digest, 'plan': plan, 'steps': [], 'status': 'prepared'};save(path, receipt)
    for index, step in enumerate(plan['steps']):
        if index < len(receipt['steps']) and receipt['steps'][index].get('verified'):continue
        if index == len(receipt['steps']):receipt['steps'].append({'status': 'submitting'})
        entry = receipt['steps'][index]
        if not entry.get('job_id'):
            save(path, receipt)  # Same idempotency key recovers a lost submission response.
            started = client.submit(step['op'], step['args'], 'team-ads-' + run_id + '-' + str(index))
            entry['job_id'] = started['job_id'];save(path, receipt)
        row = wait(entry['job_id'], client=client);entry.update(status=row['status'], response=row)
        receipt['status'] = row['status'];save(path, receipt)
        if row['status'] in ('queued', 'running'):return receipt
        result = row.get('result') or {}
        if row['status'] != 'done' or result.get('code', 0) != 0:
            raise RuntimeError('Operation stopped; inspect ' + str(path) + ' before any new write.')
        if step.get('checks'):verify_inventory(result['data'], step['checks'])
        if step['op'].startswith(('set_', 'delete_', 'new_')) or step['op'] in ('update_ad', 'resume_creation', 'register_account'):
            if not (result.get('data') or {}).get('verified'):raise RuntimeError('Write lacks verified readback; stop.')
        entry['verified'] = True;save(path, receipt)
    receipt['status'] = 'done';save(path, receipt)
    return receipt


def summary(inv):
    return {'account_budget': inv['account_budget'],
            # Which projects can be edited, and which of those were adopted from the
            # existing account (adopted ones additionally need --confirm-adopted to delete).
            'managed_project_ids': inv.get('managed_project_ids', []),
            'adopted_project_ids': inv.get('adopted_project_ids', []),
            'projects': [
        {'id': p['project_id'], 'name': p['name'], 'switch': p['opt_status'], 'status': p.get('status'),
         'daily_budget': p.get('delivery_setting', {}).get('budget'), 'roi_goal': p.get('delivery_setting', {}).get('roi_goal'),
         'ads': [{'id': a['promotion_id'], 'switch': a['opt_status'], 'status': a.get('status'), 'reasons': a.get('status_second')}
                 for a in ads_for(inv, [p['project_id']])]} for p in inv['projects']]}


def show(value, path, full=False):
    save(path, value)
    if full:
        operation_output.print_json(value, full=True)
    else:
        output = operation_output.visible(value)
        if isinstance(output, dict):
            output['details_file'] = str(path)
        operation_output.print_json(output)


def main():
    global CLIENT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', help='Stable request ID; use resume after a timeout.')
    parser.add_argument('--full-output', action='store_true', help='Print full JSON except upload bodies.')
    parser.add_argument('--dry-run', action='store_true', help='Read and save a plan; no writes.')
    parser.add_argument('--account', help='Configured account alias or exact ID; defaults to the explicitly configured account.')
    sub = parser.add_subparsers(dest='command', required=True)
    for cmd in ('status', 'list', 'capabilities','preflight','ensure-game-asset','ensure-game-events'):sub.add_parser(cmd)
    for cmd in ('start', 'pause', 'delete', 'keep-only'):
        s = sub.add_parser(cmd);s.add_argument('projects', nargs='+')
        if cmd in ('delete', 'keep-only'):
            s.add_argument('--confirm-adopted', action='store_true',
                           help='Also delete projects adopted from the existing account.')
    s = sub.add_parser('switch');s.add_argument('source');s.add_argument('destination')
    for cmd in ('budget', 'roi'):
        s = sub.add_parser(cmd);s.add_argument('project');s.add_argument('value', type=float)
    s=sub.add_parser('rebind-account',help='Move an already-registered account to another configured game; requires the current game.')
    s.add_argument('target_account_id',type=int)
    s.add_argument('--from-game-app-id',required=True,dest='from_game_app_id')
    s.add_argument('--game-app-id',required=True)
    s.add_argument('--profile')
    s=sub.add_parser('claim-projects',help="Adopt an account's existing projects for editing; deletion still needs confirmation.")
    s.add_argument('project_ids',nargs='*',type=int)
    s.add_argument('--all',action='store_true',dest='all_projects')
    sub.add_parser('account-profile')
    s = sub.add_parser('account-name');s.add_argument('--name');s.add_argument('--note')
    sub.add_parser('account-budget').add_argument('value', type=float)
    s = sub.add_parser('schedule');s.add_argument('project');s.add_argument('--mask', required=True)
    s = sub.add_parser('dates');s.add_argument('project');s.add_argument('--end');s.add_argument('--long-term', action='store_true')
    s = sub.add_parser('edit-ad');s.add_argument('project');s.add_argument('--patch-file', type=Path, required=True);s.add_argument('--promotion-id', type=int)
    s = sub.add_parser('create-ad');s.add_argument('project');s.add_argument('--args-file', type=Path, required=True)
    s = sub.add_parser('new-project');s.add_argument('name');s.add_argument('--budget', type=float, required=True);s.add_argument('--roi', type=float, required=True)
    s.add_argument('--gender',choices=['male','female','all'],default='all')
    s.add_argument('--roi-mode', choices=['7d','30d'], help='IAA ROI window: 7-day or 30-day retrieval.')
    for cmd in ('new-ad', 'new-campaign'):
        s = sub.add_parser(cmd)
        s.add_argument('project' if cmd == 'new-ad' else 'name')
        if cmd == 'new-ad':s.add_argument('--name', required=True)
        else:
            s.add_argument('--budget', type=float, required=True);s.add_argument('--roi', type=float, required=True)
            s.add_argument('--gender',choices=['male','female','all'],default='all')
            s.add_argument('--roi-mode', choices=['7d','30d'], help='IAA ROI window: 7-day or 30-day retrieval.')
        s.add_argument('--video-id');s.add_argument('--cover-id')
        s.add_argument('--videos-file', type=Path, help='JSON array of video_id, cover_id and optional orientation.')
        s.add_argument('--images-file', type=Path)
        s.add_argument('--carousels-file', type=Path)
        s.add_argument('--product-image-id')
        s.add_argument('--landing-page',help='Override the game landing page for this ad (https://www.chengzijianzhan.com/tetris/page/<id>).')
        s.add_argument('--title', action='append');s.add_argument('--orientation', choices=['VERTICAL','HORIZONTAL'])
    s = sub.add_parser('batch-create');s.add_argument('--manifest', type=Path, required=True);s.add_argument('--budget', type=float, required=True)
    s.add_argument('--product-image-id', help='Default product image for this account; each manifest row may override it.')
    s.add_argument('--roi', type=float);s.add_argument('--roi-start', type=float);s.add_argument('--roi-end', type=float);s.add_argument('--prefix', default='')
    sub.add_parser('creation-status').add_argument('creation_id')
    sub.add_parser('resume-creation').add_argument('creation_id')
    sub.add_parser('create-carousel').add_argument('--args-file', type=Path, required=True)
    s = sub.add_parser('upload');s.add_argument('kind', choices=['video', 'image', 'avatar', 'audio']);s.add_argument('file', type=Path)
    s = sub.add_parser('report');s.add_argument('--args-file', type=Path, required=True)
    s = sub.add_parser('history');s.add_argument('--limit', type=int, default=10)
    sub.add_parser('resume').add_argument('saved_run_id')
    args = parser.parse_args()
    selected=select_account(args.account)
    CLIENT=SelectedClient(selected)
    if args.command in ('status', 'list'):
        inv = read('inventory')['data'];save(ROOT / 'data/operations/latest-inventory.json', inv)
        show(summary(inv), ROOT / 'data/operations/latest-summary.json', args.full_output);return
    if args.command == 'rebind-account':
        plan={'action':'rebind_account','steps':[{'op':'rebind_account','args':{
            'target_account_id':args.target_account_id,'game_app_id':args.game_app_id,
            'from_game_app_id':args.from_game_app_id,
            **({'profile_id':args.profile} if args.profile else {})}}]}
        run_id=args.run_id or time.strftime('%Y%m%d-%H%M%S-')+uuid.uuid4().hex[:8]
        if args.dry_run:print(json.dumps(plan,ensure_ascii=False,indent=2));return
        print(json.dumps(execute_plan(plan,run_id),ensure_ascii=False,indent=2));return
    if args.command == 'claim-projects':
        if args.all_projects == bool(args.project_ids):
            raise ValueError('Use either --all or explicit project IDs.')
        request = {'all_projects': True} if args.all_projects else {'project_ids': args.project_ids}
        plan={'action':'claim_projects','steps':[{'op':'claim_projects','args':request}]}
        run_id=args.run_id or time.strftime('%Y%m%d-%H%M%S-')+uuid.uuid4().hex[:8]
        if args.dry_run:print(json.dumps(plan,ensure_ascii=False,indent=2));return
        print(json.dumps(execute_plan(plan,run_id),ensure_ascii=False,indent=2));return
    if args.command == 'account-profile':
        show(read('account_profile'), ROOT / 'data/operations/latest-account-profile.json', args.full_output);return
    if args.command == 'capabilities':show(read('status'), ROOT / 'data/operations/latest-capabilities.json', args.full_output);return
    if args.command == 'preflight':show(read('account_preflight'), ROOT / 'data/operations/latest-preflight.json', args.full_output);return
    if args.command == 'history':show(read('change_history', {'limit': args.limit}), ROOT / 'data/operations/latest-history.json', args.full_output);return
    if args.command == 'creation-status':show(read('creation_status', {'creation_id': args.creation_id}), RUNS / args.creation_id / 'status.json', args.full_output);return
    if args.command == 'resume':
        run_id = args.saved_run_id
        if not re.fullmatch('[A-Za-z0-9_-]{8,64}', run_id):raise ValueError('Invalid run ID.')
        saved = json.loads((RUNS / run_id / 'receipt.json').read_text());plan = saved['plan']
        if args.account is None:
            selected=saved.get('account_id',PRIMARY);CLIENT=SelectedClient(selected)
    else:
        run_id = args.run_id or time.strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:8]
        if args.command == 'account-name':
            payload = {key: getattr(args, key) for key in ('name', 'note') if getattr(args, key) is not None}
            if not payload:parser.error('Provide --name and/or --note.')
            for key, value in payload.items():
                if not isinstance(value, str) or len(value) > 100 or any(not c.isprintable() for c in value) or (key == 'name' and not value.strip()):
                    parser.error('Use printable account name/note up to 100 characters.')
            before = read('account_profile')['data']
            if not payload.keys() <= before.keys():raise ValueError('Account readback lacks requested fields.')
            plan = {'action': 'account-name', 'steps': [{'op': 'set_account_name', 'args': payload}], 'before': before}
        elif args.command in ('ensure-game-asset','ensure-game-events'):
            op=args.command.replace('-','_');plan={'action':op,'steps':[{'op':op,'args':{}}]}
        elif args.command in ('new-project','new-ad','new-campaign','batch-create','resume-creation'):
            if args.command == 'resume-creation':
                creation.validate('resume_creation', {'creation_id': args.creation_id})
                plan = {'action': 'resume_creation', 'steps': [{'op': 'resume_creation', 'args': {'creation_id': args.creation_id}}]}
            elif args.command == 'batch-create':
                items = batch_items(json.loads(args.manifest.read_text()), args.budget, args.roi, args.roi_start, args.roi_end, args.prefix, args.product_image_id)
                plan = creation_plan(items, run_id)
            else:
                item = {}
                if args.command in ('new-project','new-campaign'):item['project'] = {'name': args.name, 'budget': args.budget, 'roi_goal': args.roi}
                if 'project' in item and args.roi_mode:item['project']['roi_mode'] = args.roi_mode
                if 'project' in item and args.gender!='all':item['project']['gender']='GENDER_'+args.gender.upper()
                if args.command in ('new-ad','new-campaign'):
                    ad = {'name': args.name if args.command == 'new-ad' else args.name + '_广告'}
                    if args.videos_file is not None:
                        if any(value is not None for value in (args.video_id, args.cover_id, args.orientation)):
                            parser.error('--videos-file cannot be combined with single-video flags.')
                        ad['videos'] = json.loads(args.videos_file.read_text())
                    elif any(value is not None for value in (args.video_id, args.cover_id, args.orientation)):
                        ad.update(video_id=args.video_id, cover_id=args.cover_id,
                                  orientation=args.orientation or 'VERTICAL')
                    if args.images_file is not None:
                        ad['image_material_list'] = json.loads(args.images_file.read_text())
                    if args.carousels_file is not None:
                        ad['carousel_material_list'] = json.loads(args.carousels_file.read_text())
                    item['ad'] = ad
                    if args.title:item['ad']['titles'] = args.title
                    if args.product_image_id:item['ad']['product_image_id']=args.product_image_id
                    if getattr(args,'landing_page',None):item['ad']['landing_page']=args.landing_page
                if args.command == 'new-ad':item['project_id'] = resolve(read('inventory')['data'], args.project)['project_id']
                plan = creation_plan([item], run_id, args.command.replace('-', '_'))
        elif args.command in ('upload', 'report', 'create-carousel'):
            if args.command == 'report':op, payload = 'report', json.loads(args.args_file.read_text())
            elif args.command == 'create-carousel':
                op, payload = 'create_carousel', json.loads(args.args_file.read_text())
                creation.carousel_request(payload)
            else:
                if args.kind == 'audio' and args.file.suffix.lower() not in ('.mp3', '.m4a'):
                    parser.error('Audio must be MP3 or M4A.')
                limit_mib = {'video': 100, 'audio': 20}.get(args.kind, 5)
                limit = limit_mib * 1024 * 1024
                with args.file.open('rb') as source:
                    raw = source.read(limit + 1)
                if not raw or len(raw) > limit:
                    raise ValueError(f'Upload file must be non-empty and at most {limit_mib} MiB.')
                filename = args.file.name if args.kind in ('video', 'image') else 'asset' + args.file.suffix.lower()
                op, payload = 'upload_' + args.kind, {'filename': filename, 'base64': base64.b64encode(raw).decode()}
            plan = {'action': args.command, 'steps': [{'op': op, 'args': payload}]}
        else:
            inv = read('inventory')['data'];refs = getattr(args, 'projects', None) or ([args.project] if hasattr(args, 'project') else [])
            options, value = {}, getattr(args, 'value', None)
            if args.command == 'switch':refs = [args.source, args.destination]
            if args.command == 'schedule':value = args.mask
            if args.command == 'dates':
                if bool(args.end) == bool(args.long_term):raise ValueError('Choose --end or --long-term.')
                options = {'schedule_type': 'SCHEDULE_FROM_NOW' if args.long_term else 'SCHEDULE_START_END'}
                if args.end:options['end_time'] = args.end
            if args.command == 'edit-ad':options = {'patch': json.loads(args.patch_file.read_text()), 'promotion_id': args.promotion_id}
            if args.command == 'create-ad':options = json.loads(args.args_file.read_text())
            if args.command in ('delete', 'keep-only'):options = {'confirm_adopted': getattr(args, 'confirm_adopted', False)}
            plan = make_plan(inv, args.command, refs, value, options)
        if not re.fullmatch('[A-Za-z0-9_-]{8,64}', run_id):raise ValueError('Invalid run ID.')
        save(RUNS / run_id / 'plan.json', plan)
    print('Run:', run_id, flush=True)
    if args.dry_run:
        preview = {'dry_run': True, 'steps': plan['steps'], 'plan_file': str(RUNS / run_id / 'plan.json')}
        operation_output.print_json(preview, args.full_output);return
    path = RUNS / run_id / 'receipt.json'
    try:
        receipt = execute_plan(plan, run_id)
    except Exception:
        if path.exists():
            output = operation_output.outcome(json.loads(path.read_text()))
            output['receipt'] = str(path)
            operation_output.print_json(output)
        raise
    output = receipt if args.full_output else operation_output.outcome(receipt)
    operation_output.print_json(dict(output, receipt=str(path)), args.full_output)


if __name__ == '__main__':
    try:main()
    except Exception as error:
        print(type(error).__name__ + ': ' + str(error), file=sys.stderr);sys.exit(1)
