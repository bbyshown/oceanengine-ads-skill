import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import account_access
import ads
import remote_client
import settings
from test_connection import profile, setup


class AccountAccessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/'connection.json'; self.cfg = profile('operator')
        setup.write_config(self.path, self.cfg)
        self.target = 77777; self.game = 'tt-example'
        self.discovery = {'data': {'registration_version': 1, 'game_app_id': self.game, 'accounts': [
            {'account_id': self.target, 'managed': False}]}}
        self.after = copy.deepcopy(self.discovery); self.after['data']['accounts'][0]['managed'] = True
        self.result = {'verified': True, 'account_id': self.target, 'game_app_id': self.game, 'scope_changed': True}
        self.receipt = {'status': 'done', 'steps': [{'response': {'result': {'code': 0, 'data': self.result}}}]}

    def add(self, **kw):
        return account_access.add_account('new=77777', 'enroll-test-001', config_path=self.path, **kw)

    def test_verified_enrollment_preserves_key_default_existing_aliases_and_mode(self):
        with patch.object(ads, 'read', side_effect=[self.discovery, self.after]), patch.object(ads, 'execute_plan', return_value=self.receipt) as execute:
            r = self.add()
        self.assertTrue(r['local_alias_saved']); merged = settings.load(self.path)
        self.assertEqual(merged, dict(self.cfg, accounts=dict(self.cfg['accounts'], new={'id': '77777'})))
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        args = execute.call_args.args[0]['steps'][0]['args']
        self.assertEqual(args, {'target_account_id': self.target, 'game_app_id': self.game})

    def test_preview_and_pending_never_write_local_alias(self):
        original = self.path.read_bytes()
        with patch.object(ads, 'read', return_value=self.discovery), patch.object(ads, 'execute_plan', return_value={'status': 'running'}) as execute:
            self.assertEqual(self.add(dry_run=True)['status'], 'preview'); execute.assert_not_called()
            self.assertFalse(self.add()['local_alias_saved'])
        self.assertEqual(self.path.read_bytes(), original)

    def test_read_only_cannot_enroll_even_an_already_managed_account(self):
        setup.write_config(self.path, profile(), overwrite=True)
        with patch.object(ads, 'read') as read:
            with self.assertRaises(PermissionError): self.add()
            read.assert_not_called()

    def test_unauthorized_target_and_mismatched_readback_preserve_configuration(self):
        original = self.path.read_bytes()
        denied = copy.deepcopy(self.discovery); denied['data']['accounts'] = []
        with patch.object(ads, 'read', return_value=denied), patch.object(ads, 'execute_plan') as execute:
            with self.assertRaises(ValueError): self.add()
            execute.assert_not_called()
        self.result['account_id'] = self.target+1
        with patch.object(ads, 'read', return_value=self.discovery), patch.object(ads, 'execute_plan', return_value=self.receipt):
            with self.assertRaises(ValueError): self.add()
        self.assertEqual(self.path.read_bytes(), original)

    def test_missing_server_registration_or_concurrent_config_change_preserves_local_config(self):
        original = self.path.read_bytes()
        with patch.object(ads, 'read', side_effect=[self.discovery, self.discovery]), patch.object(ads, 'execute_plan', return_value=self.receipt):
            with self.assertRaises(ValueError): self.add()
        self.assertEqual(self.path.read_bytes(), original)
        def read(op, client=None):
            changed = copy.deepcopy(self.cfg); changed['default_account'] = 'primary'
            setup.write_config(self.path, changed, overwrite=True)
            return self.after
        with patch.object(ads, 'read', side_effect=read), patch.object(ads, 'execute_plan', return_value=self.receipt):
            with self.assertRaisesRegex(ValueError, 'concurrently'): self.add()
        self.assertEqual(settings.load(self.path)['default_account'], 'primary')
        self.assertNotIn('new', settings.load(self.path)['accounts'])

    def test_alias_reassignment_and_duplicate_ids_are_rejected_before_network(self):
        for entry in ('primary=77777', 'new=12345', '../bad=77777', 'new=0'):
            with self.subTest(entry=entry), self.assertRaises(ValueError): account_access.check_alias(self.cfg, entry)

    def test_global_signed_enrollment_does_not_require_target_already_selected(self):
        sent = []
        class Opener:
            def open(self, request, timeout):
                sent.append(json.loads(request.data)); return io.BytesIO(b'{"job_id":"enrollment-job"}')
        with patch.object(settings, 'load', return_value=self.cfg), patch.object(remote_client, 'build_opener', return_value=Opener()):
            remote_client.submit('register_account', {'target_account_id': self.target, 'game_app_id': self.game}, 'enroll-test-001')
            remote_client.submit('discover_accounts', {}, 'discovery-test-001')
        self.assertNotIn('account_id', sent[0]['args']); self.assertEqual(sent[1]['args'], {})

    def test_isolated_authorization_link_does_not_modify_local_account_configuration(self):
        data={'profile_id':'new-team','storage':'isolated_profile','existing_credentials_replaced':False,
              'management_enabled':False,'authorization_url':'https://open.oceanengine.com/audit/oauth.html?state=example'}
        receipt={'status':'done','steps':[{'response':{'result':{'data':data}}}]}
        original=self.path.read_bytes()
        with patch.object(settings,'load',return_value=self.cfg),patch.object(ads,'execute_plan',return_value=receipt) as execute:
            r=account_access.authorize_profile('new-team','profile-test-001')
            self.assertEqual(r['status'],'awaiting_user_authorization')
            self.assertEqual(execute.call_args.args[0]['steps'][0]['op'],'oauth_profile_authorize')
            execute.reset_mock()
            self.assertEqual(account_access.authorize_profile('new-team','profile-test-001',dry_run=True)['status'],'preview')
            execute.assert_not_called()
            data['existing_credentials_replaced']=True
            with self.assertRaises(ValueError):account_access.authorize_profile('new-team','profile-test-001')
        self.assertEqual(original,self.path.read_bytes())

    def test_profile_authorization_is_operator_only_and_installation_scoped(self):
        with patch.object(settings,'load',return_value=profile()),patch.object(ads,'execute_plan') as execute:
            with self.assertRaises(PermissionError):account_access.authorize_profile('new-team','profile-test-001')
            execute.assert_not_called()
        sent=[]
        class Opener:
            def open(self,request,timeout):
                sent.append(json.loads(request.data));return io.BytesIO(b'{"job_id":"profile-job"}')
        with patch.object(settings,'load',return_value=self.cfg),patch.object(remote_client,'build_opener',return_value=Opener()):
            remote_client.submit('oauth_profile_authorize',{'profile_id':'new-team'},'profile-test-001')
            remote_client.submit('oauth_profile_status',{'profile_id':'new-team'},'profile-read-001')
        self.assertEqual(sent[0]['args'],{'profile_id':'new-team'})
        self.assertEqual(sent[1]['args'],{'profile_id':'new-team'})


if __name__ == '__main__': unittest.main()
