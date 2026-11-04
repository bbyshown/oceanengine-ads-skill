import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import tencent_ads as client
import tencent_management as management
import tencent_runtime as runtime
import tencent_schema as schema

GAME = 'wx0000000000000001'


def config():
    return {'client_id': '12345', 'client_secret': 'fake-application-secret', 'write_enabled': True,
            'redirect_uri': 'https://gateway.example.com/manage/v1/tencent/oauth/callback',
            'accounts': {'123': {'mini_game_ids': [GAME]}}}


def group():
    return {'adgroup_id': 11, 'adgroup_name': 'Test game', 'configured_status': 'AD_STATUS_NORMAL',
            'marketing_goal': 'MARKETING_GOAL_USER_GROWTH',
            'marketing_carrier_type': 'MARKETING_CARRIER_TYPE_WECHAT_MINI_GAME',
            'marketing_carrier_detail': {'marketing_carrier_id': GAME},
            'daily_budget': 30000, 'is_deleted': False}


def new_group():
    p = group();p.pop('adgroup_id');p.pop('is_deleted');p['adgroup_name'] = 'New game'
    p.update(marketing_asset_outer_spec={'marketing_target_type': 'MARKETING_TARGET_TYPE_WECHAT_MINI_GAME',
            'marketing_asset_outer_id': GAME}, begin_date='2026-01-01', end_date='', time_series='1' * 336,
            optimization_goal='OPTIMIZATIONGOAL_APP_REGISTER')
    return p


class API:
    def __init__(self): self.groups = [group()];self.creatives = [];self.calls = [];self.timeout = False;self.invisible = False
    def __call__(self, endpoint, params, post=False, upload=None):
        self.calls.append((endpoint, copy.deepcopy(params), post))
        creative = endpoint.startswith('dynamic_creatives');rows = self.creatives if creative else self.groups
        key = 'dynamic_creative_id' if creative else 'adgroup_id'
        if endpoint.endswith('/get'):
            found = [] if self.invisible else copy.deepcopy(rows)
            for f in params.get('filtering', []): found = [r for r in found if str(r.get(f['field'])) in f['values']]
            if 'is_deleted' in params: found = [r for r in found if r.get('is_deleted', False) == params['is_deleted']]
            return {'code': 0, 'data': {'list': found, 'page_info': {'total_page': 1}}}
        if endpoint.endswith('/add'):
            row = dict(params, **{key: 22 if creative else 33, 'is_deleted': False});rows.append(row)
        else:
            row = next(r for r in rows if r[key] == params[key])
            if endpoint.endswith('/delete'): row['is_deleted'] = True
            else: row.update(params)
        if self.timeout: raise TimeoutError('committed but response lost')
        return {'code': 0, 'data': {key: row[key]}}


class TencentTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name);runtime.save(self.root / 'private/tencent/config.json', config());self.api = API()
    def execute(self, op, args): return management.execute(op, args, root=self.root, api=self.api)

    def test_money_uses_fen_and_rejects_ambiguous_precision(self):
        self.assertEqual(schema.money('1000'), 100000)
        self.assertEqual(schema.money('0.40'), 40)
        for bad in ('0.001', 'NaN', '-1', True):
            with self.assertRaises(ValueError): schema.money(bad)

    def test_iaa_and_iap_roi_goals_cannot_be_interchanged(self):
        p = {'deep_conversion_spec': {'deep_conversion_worth_spec': {'goal': 'GOAL_1DAY_MONETIZATION_ROAS', 'expected_roi': .4}}}
        schema.check_patch(p, create=True, monetization='IAA')
        with self.assertRaises(ValueError): schema.check_patch(p, create=True, monetization='IAP')

    def test_invalid_schedules_and_platform_enums_are_rejected(self):
        for p in ({'time_series': '0' * 336}, {'time_series': '1' * 335},
                  {'configured_status': 'ENABLE'}, {'daily_budget': 300}, {'targeting': {'gender': ['GENDER_MALE']}}, {'account_id': 456}):
            with self.assertRaises(ValueError): schema.check_patch(p)

    def test_unconfigured_status_has_no_token_or_api_side_effect(self):
        self.assertFalse(management.execute('tencent_status', {}, root=self.root / 'empty')['configured'])
        self.assertEqual(self.api.calls, [])

    def test_oceanengine_account_does_not_gain_tencent_permission(self):
        with self.assertRaises(runtime.Rejected): self.execute('tencent_inventory', {'account_id': 456})
        self.assertEqual(self.api.calls, [])

    def test_server_writes_default_off_even_with_a_signed_client(self):
        cfg=config();cfg.pop('write_enabled');runtime.save(self.root / 'private/tencent/config.json', cfg)
        with self.assertRaises(runtime.Rejected): self.execute('tencent_update_adgroup', {'account_id':123,'adgroup_id':11,'patch':{'daily_budget':50000}})
        self.assertEqual(self.api.calls, [])

    def test_creation_is_paused_and_does_not_reuse_oceanengine_fields(self):
        p = new_group()
        result = self.execute('tencent_new_adgroup', {'account_id': 123, 'monetization': 'IAA', 'payload': p})
        self.assertTrue(result['data']['verified'])
        self.assertEqual(result['data']['after']['configured_status'], 'AD_STATUS_SUSPEND')
        self.assertEqual(p['configured_status'], 'AD_STATUS_NORMAL')
        self.assertEqual(result['data']['after']['daily_budget'], 30000)

    def test_cross_game_creation_or_update_is_stopped_before_write(self):
        p = new_group();p['marketing_carrier_detail']['marketing_carrier_id'] = 'wx0000000000000002'
        with self.assertRaises(ValueError): self.execute('tencent_new_adgroup', {'account_id': 123, 'monetization': 'IAA', 'payload': p})
        self.api.groups[0]['marketing_carrier_detail']['marketing_carrier_id'] = 'wx0000000000000002'
        with self.assertRaises(ValueError): self.execute('tencent_update_adgroup', {'account_id': 123, 'adgroup_id': 11, 'patch': {'daily_budget': 50000}})
        self.assertFalse(any(post for _, _, post in self.api.calls))

    def test_creation_timeout_is_uncertain_and_invisible_retry_is_blocked(self):
        args = {'account_id': 123, 'monetization': 'IAA', 'payload': new_group()};self.api.timeout = True
        with self.assertRaises(management.Failure) as error: self.execute('tencent_new_adgroup', args)
        self.assertEqual(error.exception.state, 'uncertain')
        self.api.invisible = True
        with self.assertRaises(management.Failure): self.execute('tencent_new_adgroup', args)
        self.assertEqual(len([c for c in self.api.calls if c[2]]), 1)

    def test_budget_update_preserves_enabled_state(self):
        r = self.execute('tencent_update_adgroup', {'account_id': 123, 'adgroup_id': 11, 'patch': {'daily_budget': 50000}})
        self.assertEqual(r['data']['after']['daily_budget'], 50000)
        self.assertEqual(r['data']['after']['configured_status'], 'AD_STATUS_NORMAL')

    def test_wrong_readback_is_mismatch_not_success(self):
        original = self.api
        def mismatch(endpoint, params, **kwargs):
            if kwargs.get('post'): return {'code': 0, 'data': {'adgroup_id': 11}}
            return original(endpoint, params, **kwargs)
        self.api = mismatch
        with self.assertRaises(management.Failure) as error:
            self.execute('tencent_update_adgroup', {'account_id': 123, 'adgroup_id': 11, 'patch': {'daily_budget': 50000}})
        self.assertEqual(error.exception.state, 'mismatch')

    def test_creative_creation_keeps_running_parent_and_guards_destination(self):
        p = {'dynamic_creative_name': 'New creative', 'creative_components': {'description': [{'value': {'content': 'Test copy'}}]}}
        result = self.execute('tencent_new_creative', {'account_id': 123, 'adgroup_id': 11, 'payload': p})
        self.assertTrue(result['data']['verified'])
        self.assertEqual(self.api.groups[0]['configured_status'], 'AD_STATUS_NORMAL')
        value = result['data']['after']['creative_components']['main_jump_info'][0]['value']
        self.assertEqual(value['page_spec']['wechat_mini_game_spec']['mini_game_id'], GAME)
        for bad in ({'page_type': 'PAGE_TYPE_H5'}, {'mini_game_id': 'wx0000000000000002'}):
            with self.assertRaises(ValueError): management.guard_jumps(bad, GAME)

    def test_parent_delete_requires_paused_parent_and_no_children(self):
        args = {'account_id': 123, 'adgroup_id': 11}
        with self.assertRaises(ValueError): self.execute('tencent_delete_adgroup', args)
        self.api.groups[0]['configured_status'] = 'AD_STATUS_SUSPEND'
        self.api.creatives.append({'dynamic_creative_id': 22, 'adgroup_id': 11})
        with self.assertRaises(ValueError): self.execute('tencent_delete_adgroup', args)
        self.api.creatives.clear()
        self.assertTrue(self.execute('tencent_delete_adgroup', args)['data']['verified'])

    def test_report_cannot_override_account_or_omit_fields(self):
        for query in ({'account_id': 456, 'fields': ['cost']}, {'level': 'REPORT_LEVEL_ADGROUP'}):
            with self.assertRaises(ValueError): self.execute('tencent_report', {'account_id': 123, 'query': query})
        self.assertEqual(self.api.calls, [])

    def test_missing_report_list_is_not_zero(self):
        with self.assertRaises(ValueError): management.all_rows(lambda *a, **k: {'code': 0, 'data': {}}, 'daily_reports/get', {})

    def test_secret_redaction_including_error_message_values(self):
        cfg = config();token = {'access_token': 'fake-access-token'}
        result = runtime.scrub({'user_token': 'identity', 'message': cfg['client_secret'] + ' fake-access-token'}, cfg, token)
        self.assertNotIn('user_token', result);self.assertEqual(result['message'], '[redacted] [redacted]')

    def test_credential_url_transport_exception_is_withheld(self):
        with patch.object(runtime, 'build_opener', side_effect=RuntimeError('url?client_secret=sensitive')):
            with self.assertRaises(RuntimeError) as error: runtime.fetch_json(object())
            self.assertNotIn('sensitive', str(error.exception))

    def test_valid_token_is_reused_and_refresh_timeout_not_repeated(self):
        token = {'access_token': 'fake-token', 'refresh_token': 'fake-refresh', 'received_at': time.time(),
                 'access_token_expires_in': 86400, 'refresh_token_expires_in': 2592000}
        runtime.save(self.root / 'private/tencent/tokens.json', token)
        with patch.object(runtime, 'token_request') as refresh:
            self.assertEqual(runtime.access_token(self.root, config()), 'fake-token');refresh.assert_not_called()
        token['received_at'] = time.time() - 90000;runtime.save(self.root / 'private/tencent/tokens.json', token)
        with patch.object(runtime, 'token_request', side_effect=TimeoutError()) as refresh:
            with self.assertRaises(TimeoutError): runtime.access_token(self.root, config())
            with self.assertRaises(runtime.Rejected): runtime.access_token(self.root, config())
            self.assertEqual(refresh.call_count, 1)

    def test_oauth_state_is_one_use_and_wrong_state_cannot_exchange(self):
        from urllib.parse import urlsplit, parse_qs
        url = runtime.authorize_url(self.root, config());state = parse_qs(urlsplit(url).query)['state'][0]
        with patch.object(runtime, 'token_request', return_value={'access_token': 'fake'}) as exchange:
            with self.assertRaises(runtime.Rejected): runtime.callback(self.root, {'state': 'wrong', 'authorization_code': 'fake-code'})
            exchange.assert_not_called()
            self.assertTrue(runtime.callback(self.root, {'state': state, 'authorization_code': 'fake-code'})['authorized'])
            with self.assertRaises(runtime.Rejected): runtime.callback(self.root, {'state': state, 'authorization_code': 'fake-code'})
            self.assertEqual(exchange.call_count, 1)

    def test_local_read_only_blocks_writes_before_network(self):
        file = self.root / 'gateway.json';runtime.save(file, {'base_url': 'https://gateway.example.com', 'key': 'ab' * 32, 'access_mode': 'read_only'})
        gateway = client.Gateway(file)
        with patch.object(client, 'build_opener') as network:
            with self.assertRaises(PermissionError): gateway.request('jobs', {'op': 'tencent_authorize', 'args': {}, 'idempotency_key': 'readonly-test'})
            network.assert_not_called()

    def test_http_non_string_query_parameters_use_json_and_tokens_stay_out_of_body(self):
        from urllib.parse import urlsplit, parse_qs
        token = {'access_token': 'fake-token', 'refresh_token': 'fake-refresh', 'received_at': time.time(),
                 'access_token_expires_in': 86400, 'refresh_token_expires_in': 2592000}
        runtime.save(self.root / 'private/tencent/tokens.json', token)
        sent = []
        def response(request): sent.append(request);return {'code':0,'data':{}}
        api = runtime.API(self.root, config())
        with patch.object(runtime, 'fetch_json', side_effect=response):
            api('adgroups/get', {'account_id':123,'fields':['adgroup_id'],'is_deleted':False})
            api('adgroups/update', {'account_id':123,'adgroup_id':11,'daily_budget':50000}, post=True)
        query=parse_qs(urlsplit(sent[0].full_url).query)
        self.assertEqual(query['is_deleted'],['false']);self.assertEqual(json.loads(query['fields'][0]),['adgroup_id'])
        self.assertNotIn('access_token',json.loads(sent[1].data));self.assertEqual(json.loads(sent[1].data)['daily_budget'],50000)

    def test_client_resumes_lost_submission_with_same_key(self):
        class Jobs:
            cfg={'base_url':'https://gateway.example.com'}
            def __init__(self):self.keys={};self.calls=[];self.lost=True
            def request(self,route,body):
                if route=='job':return {'status':'done','result':{'code':0,'data':{'verified':True}}}
                key=body['idempotency_key'];self.calls.append(key);self.keys.setdefault(key,str(len(self.keys)))
                if self.lost:self.lost=False;raise TimeoutError()
                return {'job_id':self.keys[key]}
        gateway=Jobs();steps=[{'op':'tencent_update_adgroup','args':{'account_id':123,'adgroup_id':11,'patch':{'daily_budget':50000}}}]
        with self.assertRaises(TimeoutError):client.run(gateway,steps,'client-resume-test',self.root)
        self.assertEqual(client.run(gateway,steps,'client-resume-test',self.root)['status'],'done')
        self.assertEqual(len(gateway.keys),1);self.assertEqual(gateway.calls[0],gateway.calls[1])
        client.run(gateway,steps,'client-resume-test',self.root);self.assertEqual(len(gateway.calls),2)
        other=copy.deepcopy(steps);other[0]['args']['account_id']=456
        with self.assertRaises(ValueError):client.run(gateway,other,'client-resume-test',self.root)

    def test_invalid_last_batch_step_prevents_any_submission(self):
        class Jobs:
            cfg={'base_url':'https://gateway.example.com'}
            def request(self,*a):raise AssertionError('Must not submit an invalid batch.')
        steps=[{'op':'tencent_update_adgroup','args':{'account_id':123,'adgroup_id':11,'patch':{'daily_budget':50000}}},
               {'op':'tencent_update_adgroup','args':{'account_id':123,'adgroup_id':12,'patch':{'daily_budget':50}}}]
        with self.assertRaises(ValueError):client.run(Jobs(),steps,'invalid-batch-test',self.root)


if __name__ == '__main__': unittest.main()
