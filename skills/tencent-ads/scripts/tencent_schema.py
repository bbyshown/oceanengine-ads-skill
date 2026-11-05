"""Portable Tencent parameter validation. Monetary API fields use integer fen."""
import base64
from datetime import date
from decimal import Decimal, InvalidOperation
import re

READS = {'tencent_status', 'tencent_inventory', 'tencent_funds', 'tencent_conversions',
         'tencent_report', 'tencent_materials', 'tencent_history'}
WRITES = {'tencent_authorize', 'tencent_new_adgroup', 'tencent_new_creative', 'tencent_update_adgroup',
          'tencent_update_creative', 'tencent_delete_adgroup', 'tencent_delete_creative', 'tencent_upload'}
OPS = READS | WRITES
GROUP_FIELDS = ['adgroup_id', 'adgroup_name', 'marketing_carrier_type', 'marketing_carrier_detail',
                'configured_status', 'system_status', 'is_deleted', 'begin_date', 'end_date', 'time_series',
                'daily_budget', 'bid_amount', 'bid_mode', 'optimization_goal', 'deep_conversion_spec',
                'conversion_id', 'deep_conversion_worth_rate', 'deep_conversion_worth_advanced_rate', 'targeting',
                'marketing_goal', 'marketing_sub_goal', 'first_day_begin_time', 'automatic_site_enabled',
                'site_set', 'scene_spec', 'user_action_sets', 'smart_bid_type', 'bid_scene']
CREATIVE_FIELDS = ['dynamic_creative_id', 'dynamic_creative_name', 'adgroup_id', 'creative_components',
                   'configured_status', 'is_deleted', 'creative_template_id', 'delivery_mode', 'dynamic_creative_type']
GROUP_PATCH = {'adgroup_name', 'configured_status', 'daily_budget', 'bid_amount', 'begin_date', 'end_date',
               'first_day_begin_time', 'time_series', 'targeting', 'deep_conversion_spec',
               'deep_conversion_worth_rate', 'deep_conversion_worth_advanced_rate', 'smart_targeting_mode'}
GROUP_CREATE = GROUP_PATCH | {'marketing_goal', 'marketing_sub_goal', 'marketing_carrier_type',
    'marketing_carrier_detail', 'marketing_asset_outer_spec', 'bid_mode', 'smart_bid_type', 'bid_scene',
    'optimization_goal', 'conversion_id', 'automatic_site_enabled', 'site_set', 'scene_spec', 'user_action_sets',
    'additional_user_action_sets', 'feedback_id'}
CREATIVE_PATCH = {'dynamic_creative_name', 'configured_status', 'creative_components', 'click_tracking_url', 'impression_tracking_url'}
CREATIVE_CREATE = CREATIVE_PATCH | {'creative_template_id', 'delivery_mode', 'dynamic_creative_type'}
ROI_GOALS = {'IAA': {'GOAL_1DAY_MONETIZATION_ROAS', 'GOAL_7DAY_MONETIZATION_ROAS'},
             'IAP': {'GOAL_1DAY_PURCHASE_ROAS', 'GOAL_7DAY_PURCHASE_ROAS', 'GOAL_7DAY_LONGTERM_PURCHASE_ROAS',
                     'GOAL_14DAY_LONGTERM_PURCHASE_ROAS', 'GOAL_30DAY_LONGTERM_PURCHASE_ROAS'}}


def integer(value):
    if type(value) is not int or value <= 0: raise ValueError('Use a positive integer ID.')


def money(yuan):
    if isinstance(yuan, bool): raise ValueError('Amount must be in yuan with at most two decimals.')
    try: value = Decimal(str(yuan))
    except InvalidOperation: raise ValueError('Invalid amount.')
    if not value.is_finite() or value <= 0 or value * 100 != (value * 100).to_integral_value(): raise ValueError('Amount must be positive yuan with at most two decimals.')
    return int(value * 100)


def ratio(value):
    if isinstance(value, bool): raise ValueError('Invalid ROI ratio.')
    try: v = Decimal(str(value))
    except InvalidOperation: raise ValueError('Invalid ROI ratio.')
    if not v.is_finite() or not Decimal('.001') <= v <= 1000 or v * 10000 != (v * 10000).to_integral_value():
        raise ValueError('ROI is a ratio from 0.001 to 1000, with at most four decimals.')
    return float(v)


def check_patch(patch, creative=False, create=False, monetization=None):
    allowed = (CREATIVE_CREATE if create else CREATIVE_PATCH) if creative else (GROUP_CREATE if create else GROUP_PATCH)
    if not isinstance(patch, dict) or not patch or set(patch) - allowed: raise ValueError('Unsupported Tencent fields; identities cannot be supplied inside a patch.')
    if 'configured_status' in patch and patch['configured_status'] not in ('AD_STATUS_NORMAL', 'AD_STATUS_SUSPEND'): raise ValueError('Use AD_STATUS_NORMAL or AD_STATUS_SUSPEND.')
    for name in ('adgroup_name', 'dynamic_creative_name'):
        if name in patch and (not isinstance(patch[name], str) or not patch[name].strip() or len(patch[name].encode()) > 180): raise ValueError('Invalid Tencent object name.')
    if 'daily_budget' in patch and (type(patch['daily_budget']) is not int or not 5000 <= patch['daily_budget'] <= 400000000): raise ValueError('Tencent daily_budget is integer fen, 5000–400000000; zero means unlimited and is not enabled here.')
    if 'bid_amount' in patch and (type(patch['bid_amount']) is not int or patch['bid_amount'] < 0): raise ValueError('Tencent bid_amount must be nonnegative integer fen; platform enforces goal-specific limits.')
    for name in ('begin_date', 'end_date'):
        if name in patch and not (name == 'end_date' and patch[name] == ''):
            if not isinstance(patch[name], str) or date.fromisoformat(patch[name]).isoformat() != patch[name]: raise ValueError('Use YYYY-MM-DD.')
    if patch.get('begin_date') and patch.get('end_date') and patch['begin_date'] > patch['end_date']: raise ValueError('End date precedes start date.')
    if 'time_series' in patch and (not isinstance(patch['time_series'], str) or not re.fullmatch('[01]{336}', patch['time_series']) or '1' not in patch['time_series']): raise ValueError('Use a 336-bit half-hour weekly mask; all-zero masks are rejected.')
    if 'targeting' in patch:
        target = patch['targeting']
        if not isinstance(target, dict): raise ValueError('Targeting must be an object.')
        if 'gender' in target and target['gender'] not in (['MALE'], ['FEMALE'], []): raise ValueError('Tencent gender is MALE/FEMALE array, not an Oceanengine enum.')
    for name in ('deep_conversion_worth_rate', 'deep_conversion_worth_advanced_rate'):
        if name in patch: ratio(patch[name])
    spec = patch.get('deep_conversion_spec') or {}
    if not isinstance(spec, dict): raise ValueError('Deep conversion specification must be an object.')
    for name in ('deep_conversion_worth_spec', 'deep_conversion_worth_advanced_spec'):
        if name in spec:
            worth = spec[name]
            if not isinstance(worth, dict) or set(worth) != {'goal', 'expected_roi'}: raise ValueError('ROI spec requires goal and expected_roi.')
            ratio(worth['expected_roi'])
            goals = ROI_GOALS.get(monetization, set().union(*ROI_GOALS.values()))
            if worth['goal'] not in goals: raise ValueError('ROI goal is incompatible with the selected IAA/IAP mode.')
    if creative and 'creative_components' in patch and not isinstance(patch['creative_components'], dict): raise ValueError('Use v3.0 creative_components, not the Oceanengine materials schema.')


def validate(op, args):
    if op not in OPS or not isinstance(args, dict): raise ValueError('Unknown Tencent operation.')
    if 'profile_id' in args:
        if not isinstance(args['profile_id'], str) or not re.fullmatch(r'[a-z][a-z0-9_-]{3,47}', args['profile_id']):
            raise ValueError('Invalid Tencent authorization profile ID.')
        args = {k: v for k, v in args.items() if k != 'profile_id'}
    if op in ('tencent_status', 'tencent_authorize'):
        if args: raise ValueError('This Tencent operation takes no account arguments.')
        return
    required = {'account_id'};allowed = set(required)
    if op in ('tencent_new_adgroup',): required |= {'payload', 'monetization'};allowed |= {'payload', 'monetization'}
    if op in ('tencent_new_creative',): required |= {'adgroup_id', 'payload'};allowed |= {'adgroup_id', 'payload'}
    if op in ('tencent_update_adgroup', 'tencent_delete_adgroup'): required |= {'adgroup_id'};allowed |= {'adgroup_id'}
    if op in ('tencent_update_creative', 'tencent_delete_creative'): required |= {'dynamic_creative_id'};allowed |= {'dynamic_creative_id'}
    if op.startswith('tencent_update_'): required |= {'patch'};allowed |= {'patch'}
    if op == 'tencent_report': required |= {'query'};allowed |= {'query', 'hourly'}
    if op == 'tencent_materials': required |= {'kind', 'query'};allowed |= {'kind', 'query'}
    if op == 'tencent_conversions': required |= {'query'};allowed |= {'query'}
    if op == 'tencent_upload': required |= {'kind', 'filename', 'base64'};allowed |= {'kind', 'filename', 'base64'}
    if op == 'tencent_history': allowed |= {'limit'}
    if not required <= set(args) or set(args) - allowed: raise ValueError('Unexpected or missing Tencent arguments.')
    for field in ('account_id', 'adgroup_id', 'dynamic_creative_id'):
        if field in args: integer(args[field])
    if 'patch' in args: check_patch(args['patch'], creative='creative' in op)
    if 'payload' in args:
        if op == 'tencent_new_adgroup' and args['monetization'] not in ROI_GOALS: raise ValueError('Choose IAA or IAP.')
        check_patch(args['payload'], creative='creative' in op, create=True, monetization=args.get('monetization'))
    if op in ('tencent_materials', 'tencent_upload') and args['kind'] not in ('image', 'video'): raise ValueError('Choose image or video.')
    if op == 'tencent_history' and (type(args.get('limit', 10)) is not int or not 1 <= args.get('limit', 10) <= 100): raise ValueError('History limit must be 1–100.')
    if op == 'tencent_report' and type(args.get('hourly', False)) is not bool: raise ValueError('hourly must be boolean.')
    if op == 'tencent_upload':
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', args['filename']): raise ValueError('Use a safe basename.')
        raw = base64.b64decode(args['base64'], validate=True)
        if not 0 < len(raw) <= (10 if args['kind'] == 'image' else 50) * 1024 * 1024: raise ValueError('Gateway upload limits: images10MiB, videos50MiB.')
