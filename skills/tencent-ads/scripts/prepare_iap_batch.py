"""Prepare a paused IAP mini-game batch locally; never connect to a gateway."""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path

from tencent_ads import validate_steps
from tencent_schema import money, ratio

# The manually selected placement set used by the verified no-Channels workflow.
NO_CHANNELS_SITES = [
    'SITE_SET_MOBILE_UNION', 'SITE_SET_TENCENT_NEWS', 'SITE_SET_TENCENT_VIDEO',
    'SITE_SET_SEARCH_SCENE', 'SITE_SET_MOMENTS', 'SITE_SET_PCQQ', 'SITE_SET_KANDIAN',
    'SITE_SET_QQ_MUSIC_GAME', 'SITE_SET_WECHAT', 'SITE_SET_WECHAT_PLUGIN',
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--account', type=int, required=True)
    parser.add_argument('--profile', required=True)
    parser.add_argument('--game', required=True, help='Verified WeChat mini-game wxAppID.')
    parser.add_argument('--conversion', type=int, required=True)
    parser.add_argument('--video', required=True)
    parser.add_argument('--cover', required=True)
    parser.add_argument('--brand-image', required=True, help='Uploaded brand image ID; verify template dimensions first.')
    parser.add_argument('--brand-name', required=True)
    parser.add_argument('--description', required=True)
    parser.add_argument('--name-prefix', required=True, help='A distinct name for this batch; preserve it on recovery.')
    parser.add_argument('--budget', required=True, help='Daily yuan budget, not fen.')
    parser.add_argument('--roi', required=True, help='First-day purchase ROAS ratio, e.g. 0.2.')
    parser.add_argument('--registration-bid', required=True, help='Base registration bid in yuan; separate from ROAS.')
    parser.add_argument('--date', default=datetime.now(timezone(timedelta(hours=8))).date().isoformat())
    parser.add_argument('--site', action='append', choices=NO_CHANNELS_SITES,
                        help='Repeat to override the default manually selected no-Channels placement set.')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if not args.game.startswith('wx') or not args.brand_name.strip() or not args.description.strip():
        parser.error('Provide a verified wxAppID, brand name and description.')
    if args.conversion <= 0 or any(not value.strip() for value in (args.video, args.cover, args.brand_image)):
        parser.error('Provide positive conversion ID and nonempty uploaded material IDs.')
    selection = {'account_id': args.account, 'profile_id': args.profile}
    group = {
        'adgroup_name': args.name_prefix + '_单元_暂停',
        'marketing_goal': 'MARKETING_GOAL_USER_GROWTH',
        'marketing_sub_goal': 'MARKETING_SUB_GOAL_MINI_GAME_NEW_CUSTOMER_GROWTH',
        'marketing_carrier_type': 'MARKETING_CARRIER_TYPE_WECHAT_MINI_GAME',
        'marketing_carrier_detail': {'marketing_carrier_id': args.game},
        'marketing_asset_outer_spec': {'marketing_target_type': 'MARKETING_TARGET_TYPE_WECHAT_MINI_GAME',
                                      'marketing_asset_outer_id': args.game},
        'begin_date': args.date, 'end_date': '', 'time_series': '1' * 336,
        'daily_budget': money(args.budget), 'bid_amount': money(args.registration_bid),
        'bid_mode': 'BID_MODE_OCPM', 'optimization_goal': 'OPTIMIZATIONGOAL_APP_REGISTER',
        'conversion_id': args.conversion, 'targeting': {'age': [{'min': 18, 'max': 66}]},
        'automatic_site_enabled': False, 'site_set': list(dict.fromkeys(args.site or NO_CHANNELS_SITES)),
        'deep_conversion_spec': {'deep_conversion_type': 'DEEP_CONVERSION_WORTH',
                                 'deep_conversion_worth_spec': {'goal': 'GOAL_1DAY_PURCHASE_ROAS',
                                                                'expected_roi': ratio(args.roi)}},
        'configured_status': 'AD_STATUS_SUSPEND',
    }
    creative = {
        'dynamic_creative_name': args.name_prefix + '_创意_暂停',
        'delivery_mode': 'DELIVERY_MODE_COMPONENT',
        'dynamic_creative_type': 'DYNAMIC_CREATIVE_TYPE_PROGRAM',
        'creative_components': {
            'description': [{'value': {'content': args.description}}],
            'video': [{'value': {'video_id': args.video, 'cover_id': args.cover}}],
            'brand': [{'value': {'brand_name': args.brand_name, 'brand_image_id': args.brand_image}}],
            'main_jump_info': [{'value': {'page_type': 'PAGE_TYPE_WECHAT_MINI_GAME',
                                         'page_spec': {'wechat_mini_game_spec': {'mini_game_id': args.game}}}}],
        },
        'configured_status': 'AD_STATUS_SUSPEND',
    }
    steps = [{'op': 'tencent_new_adgroup', 'args': dict(selection, monetization='IAP', payload=group)},
             {'op': 'tencent_new_creative', 'adgroup_from': 1, 'args': dict(selection, payload=creative)}]
    validate_steps(steps)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with os.fdopen(os.open(args.out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w', encoding='utf-8') as file:
        json.dump(steps, file, ensure_ascii=False, indent=2)
        file.write('\n')
    print(json.dumps({'prepared': True, 'file': str(args.out.resolve()), 'steps': 2,
                      'paused_only': True, 'channels_excluded': True, 'network_requests': 0}, ensure_ascii=False))


if __name__ == '__main__':
    main()
