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

    def test_oauth_can_complete_before_account_game_selection_without_ad_access(self):
        from urllib.parse import urlsplit, parse_qs
        cfg=config();cfg.update(accounts={},write_enabled=False)
        runtime.save(self.root / 'private/tencent/config.json', cfg)
        result=self.execute('tencent_authorize', {})
        url=result['data']['authorization_url']
        state=parse_qs(urlsplit(url).query)['state'][0]
        with patch.object(runtime,'token_request',return_value={'access_token':'fake-token'}) as exchange:
            self.assertTrue(runtime.callback(self.root,{'state':state,'authorization_code':'fake-code'})['authorized'])
            exchange.assert_called_once()
        with self.assertRaises(runtime.Rejected):self.execute('tencent_inventory',{'account_id':123})
        with self.assertRaises(runtime.Rejected):self.execute('tencent_update_adgroup',{'account_id':123,'adgroup_id':11,'patch':{'daily_budget':50000}})
        self.assertEqual(self.api.calls,[])

    def test_oauth_config_still_rejects_invalid_credentials_callback_and_account_entries(self):
        for changes in ({'client_secret':''},{'redirect_uri':'http://gateway.example.com/manage/v1/tencent/oauth/callback'},
                        {'accounts':[]},{'accounts':{'123':None}},{'accounts':{'123':{'mini_game_ids':['tt123']}}}):
            runtime.save(self.root / 'private/tencent/config.json',dict(config(),**changes))
            with self.assertRaises(runtime.Rejected):runtime.load_config(self.root,require_accounts=False)

    def isolated_config(self, profile='client-team-b'):
        runtime.provision_profile(self.root, profile, client_id='67890', client_secret='fake-second-secret',
                                  redirect_uri=config()['redirect_uri'])
        return runtime.load_config(self.root, profile_id=profile, require_accounts=False)

    def test_profile_oauth_uses_correct_app_and_preserves_legacy_tokens(self):
        from urllib.parse import urlsplit, parse_qs
        legacy=self.root/'private/tencent/tokens.json';runtime.save(legacy, {'access_token':'legacy-token'})
        before=legacy.read_bytes();cfg=self.isolated_config()
        url=self.execute('tencent_authorize', {'profile_id':'client-team-b'})['data']['authorization_url']
        query=parse_qs(urlsplit(url).query);state=query['state'][0]
        self.assertEqual(query['client_id'],['67890'])
        self.assertTrue(state.startswith('txp1_client-team-b.'))
        with patch.object(runtime,'token_request',return_value={'access_token':'new-token'}) as exchange:
            with self.assertRaises(runtime.Rejected):runtime.callback(self.root, {'state':state.replace('client-team-b','client-team-c'), 'authorization_code':'code'})
            exchange.assert_not_called()
            result=runtime.callback(self.root, {'state':state,'authorization_code':'code'})
            self.assertEqual(result['profile_id'],'client-team-b');self.assertFalse(result['management_enabled'])
            self.assertEqual(exchange.call_args.args[0]['client_secret'],'fake-second-secret')
            with self.assertRaises(runtime.Rejected):runtime.callback(self.root, {'state':state,'authorization_code':'code'})
            self.assertEqual(exchange.call_count,1)
        self.assertEqual(legacy.read_bytes(),before)
        self.assertTrue((runtime.directory(self.root,cfg)/'tokens.json').exists())
        with self.assertRaises(runtime.Rejected):runtime.authorize_url(self.root,cfg)

    def test_profile_oauth_uncertainty_blocks_reexchange_and_new_link(self):
        from urllib.parse import urlsplit, parse_qs
        cfg=self.isolated_config();state=parse_qs(urlsplit(runtime.authorize_url(self.root,cfg)).query)['state'][0]
        with patch.object(runtime,'token_request',side_effect=TimeoutError()) as exchange:
            with self.assertRaises(TimeoutError):runtime.callback(self.root,{'state':state,'authorization_code':'code'})
            with self.assertRaises(runtime.Rejected):runtime.callback(self.root,{'state':state,'authorization_code':'code'})
            with self.assertRaises(runtime.Rejected):runtime.authorize_url(self.root,cfg)
            self.assertEqual(exchange.call_count,1)

    def test_profile_auth_does_not_inherit_legacy_allowlist_or_writes(self):
        self.isolated_config()
        for op,args in [('tencent_inventory',{'account_id':123}),('tencent_update_adgroup',{'account_id':123,'adgroup_id':11,'patch':{'daily_budget':50000}})]:
            with self.assertRaises(runtime.Rejected):self.execute(op,dict(args,profile_id='client-team-b'))
        status=self.execute('tencent_status',{'profile_id':'client-team-b'})
        self.assertEqual(status['client_id'],'67890');self.assertFalse(status['management_enabled'])
        self.assertEqual(self.api.calls,[])
        with self.assertRaises(runtime.Rejected):self.execute('tencent_inventory',{'profile_id':'missing-team','account_id':123})

    def test_profile_token_refresh_uses_its_own_lock_and_token_file(self):
        cfg=self.isolated_config();path=runtime.directory(self.root,cfg)/'tokens.json'
        stale={'client_id':'67890','access_token':'old-token','refresh_token':'profile-refresh','received_at':time.time()-90000,
               'access_token_expires_in':86400,'refresh_token_expires_in':2592000}
        runtime.save(path,stale)
        legacy=self.root/'private/tencent/tokens.json';runtime.save(legacy,{'access_token':'legacy-token'})
        before=legacy.read_bytes()
        fresh=dict(stale,received_at=time.time(),access_token='fresh-profile-token')
        with patch.object(runtime,'token_request',return_value=fresh) as exchange:
            self.assertEqual(runtime.access_token(self.root,cfg),'fresh-profile-token')
            self.assertEqual(exchange.call_args.args[0]['client_id'],'67890')
            self.assertEqual(exchange.call_args.args[1]['refresh_token'],'profile-refresh')
        self.assertEqual(legacy.read_bytes(),before)

    def test_profile_names_and_existing_credentials_cannot_be_rebound(self):
        for bad in ('../escape','default/other','Ateam','x'):
            with self.assertRaises(ValueError):schema.validate('tencent_authorize',{'profile_id':bad})
        cfg=self.isolated_config();runtime.provision_profile(self.root,'client-team-b',client_id='67890',client_secret='fake-second-secret',redirect_uri=cfg['redirect_uri'])
        with self.assertRaises(runtime.Rejected):runtime.provision_profile(self.root,'client-team-b',client_id='98765',client_secret='another',redirect_uri=cfg['redirect_uri'])
        self.assertEqual(runtime.load_config(self.root,require_accounts=False,profile_id='client-team-b')['client_id'],'67890')

    def test_local_read_only_blocks_writes_before_network(self):
        file = self.root / 'gateway.json';runtime.save(file, {'base_url': 'https://gateway.example.com', 'key': 'ab' * 32, 'access_mode': 'read_only'})
        gateway = client.Gateway(file)
        with patch.object(client, 'build_opener') as network:
            with self.assertRaises(PermissionError): gateway.request('jobs', {'op': 'tencent_authorize', 'args': {}, 'idempotency_key': 'readonly-test'})
            network.assert_not_called()

    def test_private_import_waits_without_network_and_never_invents_token_lifetimes(self):
        pair={'access_token':'private-access','refresh_token':'private-refresh'}
        ready=time.time()+600
        result=runtime.stage_private_tokens(self.root,pair,ready)
        self.assertNotIn('private-access',json.dumps(result))
        self.assertTrue(runtime.stage_private_tokens(self.root,pair,ready)['already_staged'])
        with patch.object(runtime,'token_request') as exchange:
            self.assertEqual(runtime.finish_private_token_import(self.root)['status'],'waiting_for_activation')
            exchange.assert_not_called()
        self.assertFalse((self.root/'private/tencent/tokens.json').exists())

    def test_private_import_refreshes_once_and_reuses_returned_lifetimes(self):
        pair={'access_token':'private-access','refresh_token':'private-refresh'}
        ready=time.time()+600;runtime.stage_private_tokens(self.root,pair,ready)
        fresh={'access_token':'fresh-access','refresh_token':'fresh-refresh','received_at':ready+1,
               'access_token_expires_in':1234,'refresh_token_expires_in':5678}
        with patch.object(runtime.time,'time',return_value=ready+1),patch.object(runtime,'token_request',return_value=fresh) as exchange:
            result=runtime.finish_private_token_import(self.root)
            self.assertEqual(result['access_token_expires_in'],1234)
            self.assertTrue(runtime.finish_private_token_import(self.root)['already_imported'])
            self.assertEqual(exchange.call_count,1)
            self.assertNotIn('fresh-access',json.dumps(result))
        saved=json.loads((self.root/'private/tencent/tokens.json').read_text())
        self.assertEqual(saved['received_at'],ready+1)
        self.assertEqual(saved['refresh_token_expires_in'],5678)

    def test_private_import_refresh_timeout_is_not_repeated(self):
        ready=time.time()+600
        runtime.stage_private_tokens(self.root,{'access_token':'private-access','refresh_token':'private-refresh'},ready)
        with patch.object(runtime.time,'time',return_value=ready+1),patch.object(runtime,'token_request',side_effect=TimeoutError()) as exchange:
            with self.assertRaises(TimeoutError):runtime.finish_private_token_import(self.root)
            with self.assertRaises(runtime.Rejected):runtime.finish_private_token_import(self.root)
            self.assertEqual(exchange.call_count,1)

    def test_private_import_preserves_existing_identity_and_rejects_malformed_inputs(self):
        ready=time.time()+600
        for pair in ({'access_token':'a'}, {'access_token':'a b','refresh_token':'c'}):
            with self.assertRaises(runtime.Rejected):runtime.stage_private_tokens(self.root,pair,ready)
        runtime.save(self.root/'private/tencent/tokens.json',{'access_token':'existing'})
        with self.assertRaises(runtime.Rejected):runtime.stage_private_tokens(self.root,{'access_token':'new','refresh_token':'new'},ready)
        self.assertEqual(json.loads((self.root/'private/tencent/tokens.json').read_text())['access_token'],'existing')

    def test_private_import_rejected_refresh_preserves_outcome_and_stops(self):
        ready=time.time()+600
        runtime.stage_private_tokens(self.root,{'access_token':'private-access','refresh_token':'private-refresh'},ready)
        with patch.object(runtime.time,'time',return_value=ready+1),patch.object(runtime,'token_request',side_effect=runtime.Rejected('Tencent OAuth rejected: 123')) as exchange:
            with self.assertRaises(runtime.Rejected):runtime.finish_private_token_import(self.root)
            with self.assertRaises(runtime.Rejected):runtime.finish_private_token_import(self.root)
            self.assertEqual(exchange.call_count,1)
        self.assertFalse((self.root/'private/tencent/tokens.json').exists())

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

    def test_batch_attaches_creative_to_verified_new_parent_and_resumes(self):
        class Jobs:
            cfg = {'base_url': 'https://gateway.example.com'}

            def __init__(self):
                self.calls = []

            def request(self, route, body):
                if route == 'job':
                    return {'status': 'done', 'result': {'code': 0, 'data': {'verified': True, 'adgroup_id': 732}}}
                self.calls.append(body)
                if len(self.calls) == 2:
                    raise TimeoutError()
                return {'job_id': str(len(self.calls))}

        steps = [
            {'op': 'tencent_new_adgroup', 'args': {'account_id': 123, 'monetization': 'IAA',
                                                'payload': {'adgroup_name': 'Group'}}},
            {'op': 'tencent_new_creative', 'adgroup_from': 1, 'args': {'account_id': 123,
                'payload': {'dynamic_creative_name': 'Creative', 'creative_components': {}}}},
        ]
        gateway = Jobs()
        with self.assertRaises(TimeoutError):
            client.run(gateway, steps, 'paired-batch-test', self.root)
        receipt = client.run(gateway, steps, 'paired-batch-test', self.root)
        self.assertEqual(receipt['status'], 'done')
        self.assertEqual(len(gateway.calls), 3)
        self.assertEqual(gateway.calls[1], gateway.calls[2])
        self.assertEqual(gateway.calls[2]['args']['adgroup_id'], 732)
        self.assertNotIn('adgroup_from', gateway.calls[2])
        invalid = copy.deepcopy(steps)
        invalid[1]['args']['profile_id'] = 'other-team'
        with self.assertRaises(ValueError):
            client.run(gateway, invalid, 'invalid-pair-test', self.root)
        self.assertEqual(len(gateway.calls), 3)

    def test_invalid_last_batch_step_prevents_any_submission(self):
        class Jobs:
            cfg={'base_url':'https://gateway.example.com'}
            def request(self,*a):raise AssertionError('Must not submit an invalid batch.')
        steps=[{'op':'tencent_update_adgroup','args':{'account_id':123,'adgroup_id':11,'patch':{'daily_budget':50000}}},
               {'op':'tencent_update_adgroup','args':{'account_id':123,'adgroup_id':12,'patch':{'daily_budget':50}}}]
        with self.assertRaises(ValueError):client.run(Jobs(),steps,'invalid-batch-test',self.root)


if __name__ == '__main__': unittest.main()


class OAuthNodePinTests(unittest.TestCase):
    def test_pin_keeps_domain_tls_and_connects_only_to_selected_ip(self):
        import ssl
        connection = runtime.PinnedHTTPSConnection('api.e.qq.com', remote_ip='8.8.8.8', timeout=3)
        self.assertTrue(connection._context.check_hostname)
        self.assertEqual(connection._context.verify_mode, ssl.CERT_REQUIRED)
        with patch.object(runtime.socket, 'create_connection') as connect, patch.object(connection._context, 'wrap_socket') as wrap:
            connection.connect()
        connect.assert_called_once_with(('8.8.8.8', 443), 3, None)
        wrap.assert_called_once_with(connect.return_value, server_hostname='api.e.qq.com')

    def test_invalid_pins_rejected_before_any_token_request(self):
        for value in ('198.18.3.252', '127.0.0.1', 'https://example.com', '', '10.0.0.1'):
            with self.subTest(value=value), patch.object(runtime, 'fetch_json') as fetch:
                with self.assertRaises(runtime.Rejected):
                    runtime.token_request(dict(config(), oauth_token_remote_ip=value), {})
                fetch.assert_not_called()

    def test_pin_passed_only_to_token_transport(self):
        result = {'code': 0, 'data': {'access_token': 'a', 'refresh_token': 'r',
                  'access_token_expires_in': 1000, 'refresh_token_expires_in': 2000}}
        with patch.object(runtime, 'fetch_json', return_value=result) as fetch:
            runtime.token_request(dict(config(), oauth_token_remote_ip='8.8.8.8'), {'grant_type': 'authorization_code'})
        self.assertEqual(fetch.call_args.kwargs, {'remote_ip': '8.8.8.8'})
        self.assertEqual(runtime.urlsplit(fetch.call_args.args[0].full_url).hostname, 'api.e.qq.com')


class OAuthTokenHostTests(unittest.TestCase):
    def test_only_tencent_hosts_allowed(self):
        self.assertEqual(runtime.token_host({}), 'api.e.qq.com')
        self.assertEqual(runtime.token_host({'oauth_token_host':'developers.e.qq.com'}), 'developers.e.qq.com')
        for host in ('example.com', 'api.e.qq.com.evil.test', 'api.e.qq.com:443', ''):
            with self.assertRaises(runtime.Rejected):runtime.token_host({'oauth_token_host':host})

    def test_configured_host_preserves_pin_and_tls_domain(self):
        cfg=dict(config(),oauth_token_host='developers.e.qq.com',oauth_token_remote_ip='8.8.8.8')
        result={'code':0,'data':dict(access_token='a',refresh_token='r',access_token_expires_in=1000,refresh_token_expires_in=2000)}
        with patch.object(runtime,'fetch_json',return_value=result) as fetch:
            runtime.token_request(cfg,{'grant_type':'authorization_code'})
        self.assertEqual(runtime.urlsplit(fetch.call_args.args[0].full_url).hostname,'developers.e.qq.com')
        self.assertEqual(fetch.call_args.kwargs,{'remote_ip':'8.8.8.8'})
        connection=runtime.PinnedHTTPSConnection('developers.e.qq.com',remote_ip='8.8.8.8',timeout=3)
        with patch.object(runtime.socket,'create_connection') as connect,patch.object(connection._context,'wrap_socket') as wrap:
            connection.connect()
        wrap.assert_called_once_with(connect.return_value,server_hostname='developers.e.qq.com')

class OperatorCredentialTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        cfg = dict(config(), write_enabled=False, _profile_id='test-operator')
        folder = runtime.directory(self.root, cfg)
        runtime.save(folder/'config.json', {k:v for k,v in cfg.items() if k!='_profile_id'})
        runtime.save(folder/'tokens.json', {'access_token':'existing-app-token'})
        self.cfg = runtime.load_config(self.root, profile_id='test-operator')
        self.folder = folder
        self.link = runtime.user_authorize_url(self.root, self.cfg, 123)
        self.state = runtime.urlsplit(self.link['authorization_url']).query
        from urllib.parse import parse_qs
        self.state = parse_qs(self.state)['state'][0]
        self.query = dict(state=self.state, user_status='2', user_token='fake-operator-secret',expire_time=str(int(time.time())+3600))

    def test_callback_saves_only_scoped_credential_without_enabling_ads(self):
        old_tokens = (self.folder/'tokens.json').read_bytes()
        result = runtime.user_callback(self.root, dict(self.query, wx_id='fake-wechat-id'))
        cfg = runtime.load_config(self.root, profile_id='test-operator')
        self.assertTrue(result['user_authorized'])
        self.assertNotIn('fake-operator-secret', json.dumps(result))
        self.assertNotIn('fake-wechat-id', json.dumps(result))
        self.assertNotIn('fake-wechat-id', (self.folder/'config.json').read_text())
        self.assertNotIn('fake-operator-secret', (self.folder/'user-authorization.json').read_text())
        self.assertEqual(cfg['accounts']['123']['user_token'],'fake-operator-secret')
        self.assertFalse(cfg['write_enabled'])
        self.assertEqual(old_tokens,(self.folder/'tokens.json').read_bytes())
        self.assertEqual((self.folder/'config.json').stat().st_mode & 0o777,0o600)
        with self.assertRaises(runtime.Rejected):runtime.user_callback(self.root,self.query)

    def test_bad_state_expired_token_and_missing_token_preserve_config(self):
        original=(self.folder/'config.json').read_bytes()
        for change in ({'state':self.state+'x'}, {'expire_time':'1'}, {'user_token':''},
                       {'user_status':'3'}, {'user_token':'bad\nvalue'}):
            with self.subTest(change=change), self.assertRaises(runtime.Rejected):
                runtime.user_callback(self.root,dict(self.query,**change))
            self.assertEqual(original,(self.folder/'config.json').read_bytes())
        state=json.loads((self.folder/'user-authorization.json').read_text());state['expires_at']=1
        runtime.save(self.folder/'user-authorization.json',state)
        with self.assertRaises(runtime.Rejected):runtime.user_callback(self.root,self.query)

    def test_live_link_not_reissued_and_incomplete_verification_not_saved(self):
        with self.assertRaises(runtime.Rejected):runtime.user_authorize_url(self.root,self.cfg,123)
        result=runtime.user_callback(self.root,dict(self.query,user_status='1'))
        self.assertFalse(result['user_authorized'])
        self.assertNotIn('user_token',runtime.load_config(self.root,profile_id='test-operator')['accounts']['123'])
        with self.assertRaises(runtime.Rejected):runtime.user_authorize_url(self.root,self.cfg,456)

    def test_expired_operator_token_stops_before_transport(self):
        cfg=dict(self.cfg,accounts={'123':dict(self.cfg['accounts']['123'],user_token='expired-secret',user_token_expires_at=1)})
        with patch.object(runtime,'access_token',return_value='app-token'),patch.object(runtime,'fetch_json') as fetch:
            with self.assertRaises(runtime.Rejected):runtime.API(self.root,cfg)('adgroups/add',{'account_id':123},post=True)
        fetch.assert_not_called()


class OperatorTokenTransportTests(unittest.TestCase):
    def test_operator_token_is_query_parameter_not_json_or_header(self):
        from urllib.parse import parse_qs
        cfg=dict(config(),accounts={'123':dict(config()['accounts']['123'],user_token='fake-user-token+=',user_token_expires_at=int(time.time())+3600)})
        with patch.object(runtime,'access_token',return_value='fake-app-token'),patch.object(runtime,'fetch_json',return_value={'code':0}) as fetch:
            runtime.API(Path('/unused'),cfg)('adgroups/add',{'account_id':123},post=True)
        request=fetch.call_args.args[0]
        query=parse_qs(runtime.urlsplit(request.full_url).query)
        self.assertEqual(query['user_token'],['fake-user-token+='])
        self.assertNotIn('user_token',json.loads(request.data))
        self.assertNotIn('fake-user-token',str(request.headers))


class ReadbackDateTests(unittest.TestCase):
    def test_only_empty_group_end_date_matches_zero_representation(self):
        self.assertTrue(management.verified_fields({'end_date':'0','daily_budget':30000},{'end_date':'','daily_budget':30000}))
        self.assertFalse(management.verified_fields({'end_date':'0','daily_budget':40000},{'end_date':'','daily_budget':30000}))
        self.assertFalse(management.verified_fields({'end_date':'2026-12-01'},{'end_date':''}))
        self.assertFalse(management.verified_fields({'end_date':'0'},{'end_date':'2026-12-01'}))
        self.assertFalse(management.verified_fields({'end_date':'0'},{'end_date':''},creative=True))


class ExistingGatewayConnectionTests(unittest.TestCase):
    def test_explicit_import_copies_connection_but_not_oceanengine_scope(self):
        with tempfile.TemporaryDirectory() as d:
            source=Path(d)/'oceanengine.json'
            client.save(source,{'base_url':'https://gateway.example.test','key':'a'*64,'access_mode':'operator',
                                'accounts':{'other':123},'default_account':'other','profile_id':'other-platform'})
            before=source.read_bytes()
            cfg=client.connection_from_oceanengine(source)
            self.assertEqual(cfg,{'base_url':'https://gateway.example.test','key':'a'*64,'access_mode':'read_only'})
            self.assertEqual(source.read_bytes(),before)
            self.assertEqual(client.connection_from_oceanengine(source,'operator')['access_mode'],'operator')
            source.chmod(0o644)
            if client.os.name=='posix':
                with self.assertRaises(ValueError):client.connection_from_oceanengine(source)

    def test_import_cli_never_prompts_or_prints_key_and_preserves_source(self):
        import io
        from contextlib import redirect_stdout
        with tempfile.TemporaryDirectory() as d:
            source=Path(d)/'oceanengine.json';target=Path(d)/'tencent.json'
            client.save(source,{'base_url':'https://gateway.example.test','key':'b'*64,'access_mode':'operator'})
            before=source.read_bytes();output=io.StringIO()
            argv=['tencent_ads.py','--config',str(target),'configure','--from-oceanengine-config',str(source)]
            with patch.object(client.sys,'argv',argv),patch.object(client.getpass,'getpass') as prompt,redirect_stdout(output):
                client.main()
            prompt.assert_not_called()
            self.assertNotIn('b'*64,output.getvalue())
            self.assertEqual(client.Gateway(target).cfg['access_mode'],'read_only')
            self.assertEqual(source.read_bytes(),before)
            self.assertEqual(target.stat().st_mode&0o777,0o600)
            with patch.object(client.sys,'argv',argv),self.assertRaises(ValueError):client.main()
            argv=['tencent_ads.py','--config',str(source),'configure','--from-oceanengine-config',str(source),'--overwrite']
            with patch.object(client.sys,'argv',argv),self.assertRaises(ValueError):client.main()
            self.assertEqual(source.read_bytes(),before)


def smart_group(goal='SMART_DELIVERY_GOAL_SEVEN_DAY_MONETIZATION'):
    p = new_group(); mode, field, conversion_goal = schema.SMART_GOALS[goal]
    p.update(smart_delivery_platform=schema.SMART_PLATFORM, conversion_id=77, bid_amount=200,
        smart_delivery_scene_spec={'smart_delivery_goal':goal,'conversion_id_list':[77],
            'smart_delivery_goal_spec':{'mini_game_promotion_spec':{'register_cost':200,field:.45}}},
        deep_conversion_spec={'deep_conversion_type':'DEEP_CONVERSION_WORTH',
            'deep_conversion_worth_spec':{'goal':conversion_goal,'expected_roi':.45}})
    return p


class SmartDeliveryTests(unittest.TestCase):
    setUp = TencentTests.setUp
    execute = TencentTests.execute
    # Only feature tests belong to this class; base fixture remains shared.
    def smart_api(self, mismatch=False, wrong_game=False):
        original = self.api
        def call(endpoint, params, post=False, upload=None):
            if endpoint == 'conversions/get':
                return {'code':0,'data':{'list':[{'conversion_id':77,
                    'marketing_carrier_id':'wxwrong' if wrong_game else GAME,
                    'optimization_goal':'OPTIMIZATIONGOAL_APP_REGISTER',
                    'deep_worth_optimization_goal':'GOAL_7DAY_MONETIZATION_ROAS',
                    'access_status':'ACCESS_STATUS_COMPLETED'}], 'page_info':{'total_page':1}}}
            result = original(endpoint, params, post, upload)
            if mismatch and endpoint == 'adgroups/get':
                for row in result['data']['list']: row.pop('smart_delivery_platform',None)
            return result
        return call

    def test_smart_all_four_goals_and_mode_validation(self):
        for goal, (mode, field, _) in schema.SMART_GOALS.items():
            p=smart_group(goal);schema.check_patch(p, create=True, monetization=mode)
            with self.assertRaises(ValueError): schema.check_patch(p, create=True, monetization='IAP' if mode=='IAA' else 'IAA')
            for key,value in [('conversion_id',78),('bid_amount',300),('smart_delivery_platform','unknown')]:
                bad=copy.deepcopy(p);bad[key]=value
                with self.assertRaises(ValueError):schema.check_patch(bad,create=True,monetization=mode)
            bad=copy.deepcopy(p);bad['smart_delivery_scene_spec']['smart_delivery_goal_spec']['mini_game_promotion_spec']['extra_roi']=.1
            with self.assertRaises(ValueError):schema.check_patch(bad,create=True,monetization=mode)

    def test_smart_readback_must_confirm_platform(self):
        for mismatch in (False,True):
            with self.subTest(mismatch=mismatch):
                self.api.groups=[group()]
                p=smart_group();p['adgroup_name']+='_'+str(mismatch)
                if mismatch:
                    with self.assertRaises(management.Failure) as caught:
                        management.execute('tencent_new_adgroup',{'account_id':123,'monetization':'IAA','payload':p},root=self.root,api=self.smart_api(True))
                    self.assertEqual(caught.exception.state,'mismatch')
                else:
                    r=management.execute('tencent_new_adgroup',{'account_id':123,'monetization':'IAA','payload':p},root=self.root,api=self.smart_api())
                    self.assertTrue(r['data']['verified'])
                    self.assertEqual(r['data']['after']['configured_status'],'AD_STATUS_SUSPEND')

    def test_smart_conversion_game_checked_before_post(self):
        with self.assertRaises(ValueError):
            management.execute('tencent_new_adgroup',{'account_id':123,'monetization':'IAA','payload':smart_group()},root=self.root,api=self.smart_api(wrong_game=True))
        self.assertFalse(any(post for _,_,post in self.api.calls))

    def test_smart_updates_preserve_goal_and_other_bid(self):
        g=smart_group();g['adgroup_id']=11;self.api.groups=[g]
        patch=schema.smart_scene_patch(g,roi_value='.6')
        values=patch['smart_delivery_scene_spec']['smart_delivery_goal_spec']['mini_game_promotion_spec']
        self.assertEqual(values,{'register_cost':200,'seven_day_monetization_roi':.6})
        self.assertEqual(g['smart_delivery_scene_spec']['smart_delivery_goal_spec']['mini_game_promotion_spec']['seven_day_monetization_roi'],.45)
        r=self.execute('tencent_update_adgroup',{'account_id':123,'adgroup_id':11,'patch':patch})
        self.assertTrue(r['data']['verified'])
        for bad in ({'bid_amount':300},dict(patch,bid_amount=300),{'smart_delivery_scene_spec':dict(patch['smart_delivery_scene_spec'],conversion_id_list=[78])}):
            with self.assertRaises(ValueError):self.execute('tencent_update_adgroup',{'account_id':123,'adgroup_id':11,'patch':bad})
        self.api.groups=[group()]
        with self.assertRaises(ValueError):self.execute('tencent_update_adgroup',{'account_id':123,'adgroup_id':11,'patch':patch})

    def test_smart_inventory_filters_and_keeps_game_scope(self):
        smart=smart_group();smart['adgroup_id']=33
        outside=copy.deepcopy(smart);outside['adgroup_id']=44;outside['marketing_carrier_detail']['marketing_carrier_id']='wxother'
        self.api.groups += [smart,outside]
        r=self.execute('tencent_inventory',{'account_id':123,'delivery':'smart'})
        self.assertEqual([g['adgroup_id'] for g in r['data']['adgroups']],[33])
        r=self.execute('tencent_inventory',{'account_id':123,'delivery':'standard'})
        self.assertEqual([g['adgroup_id'] for g in r['data']['adgroups']],[11])


class CreationCliRegressionTests(unittest.TestCase):
    def test_single_group_commands_map_to_existing_op_without_creative_parent(self):
        import io
        from contextlib import redirect_stdout
        for command,payload in [('new-adgroup',new_group()),('new-smart',smart_group())]:
            with tempfile.TemporaryDirectory() as folder:
                path=Path(folder)/'payload.json';path.write_text(json.dumps(payload))
                argv=['tencent_ads.py','--account','123','--profile','team-example','--dry-run',command,'--mode','IAA','--args-file',str(path)]
                with patch('sys.argv',argv),patch.object(client,'Gateway'),redirect_stdout(io.StringIO()) as output:
                    client.main()
                step=json.loads(output.getvalue())['steps'][0]
                self.assertEqual(step['op'],'tencent_new_adgroup')
                self.assertNotIn('adgroup_id',step['args'])
                self.assertEqual(step['args']['payload']['configured_status'],'AD_STATUS_SUSPEND')

    def test_new_smart_refuses_ordinary_payload(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'payload.json';path.write_text(json.dumps(new_group()))
            argv=['tencent_ads.py','--account','123','--dry-run','new-smart','--mode','IAA','--args-file',str(path)]
            with patch('sys.argv',argv),patch.object(client,'Gateway'),self.assertRaises(ValueError):client.main()
