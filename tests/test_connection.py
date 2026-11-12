import copy
import hashlib
import hmac
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import remote_client
import settings

spec = importlib.util.spec_from_file_location('skill_setup', Path(settings.__file__).with_name('setup.py'))
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


def profile(mode='read_only'):
    return {'base_url': 'https://gateway.example.com', 'key': 'ab' * 32,
            'access_mode': mode, 'default_account': 'secondary',
            'accounts': {'primary': {'id': '12345'}, 'secondary': {'id': '67890'}}}


class ConnectionTests(unittest.TestCase):
    def test_default_and_exact_accounts_do_not_guess_suffixes(self):
        cfg = profile()
        self.assertEqual(settings.select_account(config=cfg), 67890)
        self.assertEqual(settings.select_account('primary', cfg), 12345)
        self.assertEqual(settings.select_account('67890', cfg), 67890)
        for bad in ('90', 'unknown', True, 123):
            with self.assertRaises(ValueError): settings.select_account(bad, cfg)

    def test_invalid_origins_and_ambiguous_accounts_are_rejected(self):
        for url in ('http://gateway.example.com', 'https://user:pass@gateway.example.com',
                    'https://gateway.example.com/path', 'https://gateway.example.com?token=x'):
            with self.assertRaises(ValueError): settings.validate(dict(profile(), base_url=url))
        cfg = profile()
        cfg['accounts']['secondary']['id'] = '12345'
        with self.assertRaises(ValueError): settings.validate(cfg)
        cfg = profile()
        cfg['accounts']['secondary']['id'] = True
        with self.assertRaises(ValueError): settings.validate(cfg)

    def test_config_permissions_and_explicit_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'connection.json'
            setup.write_config(target, profile())
            self.assertEqual(settings.load(target), profile())
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(ValueError): setup.write_config(target, profile('operator'))
            self.assertEqual(settings.load(target)['access_mode'], 'read_only')
            if os.name == 'posix':
                target.chmod(0o644)
                with self.assertRaises(ValueError): settings.load(target)

    def test_read_only_blocks_every_write_before_network(self):
        with patch.object(settings, 'load', return_value=profile()), patch.object(remote_client, 'build_opener') as network:
            for op in remote_client.WRITES:
                with self.assertRaises(PermissionError): remote_client.submit(op, {}, 'test-key')
            network.assert_not_called()

    def test_default_account_is_signed_into_body_and_redirects_are_disabled(self):
        cfg = profile()
        sent = []
        class Opener:
            def open(self, request, timeout):
                sent.append(request)
                return io.BytesIO(b'{"job_id":"test-job"}')
        with patch.object(settings, 'load', return_value=cfg), patch.object(remote_client, 'build_opener', return_value=Opener()) as opener:
            args = {}
            remote_client.submit('status', args, 'stable-key')
            self.assertEqual(args, {})
            request = sent[0]
            self.assertEqual(json.loads(request.data)['args']['account_id'], 67890)
            headers = {k.lower(): v for k, v in request.header_items()}
            message = ('POST\n/manage/v1/jobs\n' + headers['x-manage-time'] + '\n' +
                       headers['x-manage-nonce'] + '\n' + hashlib.sha256(request.data).hexdigest()).encode()
            expected = hmac.new(bytes.fromhex(cfg['key']), message, hashlib.sha256).hexdigest()
            self.assertEqual(headers['x-manage-signature'], expected)
            self.assertIsInstance(opener.call_args.args[0], remote_client.NoRedirect)
            self.assertIsNone(opener.call_args.args[0].redirect_request(None, None, 302, '', {}, 'https://other.example.com'))
            with self.assertRaises(ValueError): remote_client.submit('status', {'account_id': 99999}, 'bad-account')
            self.assertEqual(len(sent), 1)


if __name__ == '__main__': unittest.main()


class OperationWhitelistTests(unittest.TestCase):
    """Every op the CLI can emit must be accepted by the signed client.

    A missing entry fails only at submit time against the live gateway, so it is
    caught here instead: a command that exists but cannot be sent is a broken
    release, not a user error.
    """

    def test_every_cli_command_maps_to_an_allowed_operation(self):
        """Every subcommand that sends a job must have its op in the whitelist.

        The mapping is declared here explicitly so adding a CLI command without
        wiring its op fails this test instead of failing for a colleague.
        """
        import remote_client
        allowed = remote_client.READS | remote_client.WRITES
        cli_to_op = {
            'inventory': 'inventory', 'accounts': 'discover_accounts',
            'add-account': 'register_account', 'rebind-account': 'rebind_account',
            'claim-projects': 'claim_projects',
            'new-project': 'new_project', 'new-ad': 'new_ad', 'new-campaign': 'new_campaign',
            'batch-create': 'new_campaign', 'start': 'set_project_status',
            'pause': 'set_project_status', 'delete': 'delete_projects',
            'keep-only': 'delete_projects', 'switch': 'set_project_status',
            'budget': 'set_project_budget', 'roi': 'set_project_bid',
            'edit-ad': 'update_ad', 'create-ad': 'create_paused_ad',
            'upload': 'upload_video', 'report': 'report',
        }
        missing = {cli: op for cli, op in cli_to_op.items() if op not in allowed}
        self.assertEqual(missing, {})

    def test_adoption_operation_is_sendable(self):
        import remote_client
        self.assertIn('claim_projects', remote_client.WRITES)
        self.assertIn('register_account', remote_client.WRITES)
        self.assertIn('discover_accounts', remote_client.READS)

    def test_claim_projects_is_not_read_only_gated(self):
        """Adoption must run under operator access, matching register_account."""
        import remote_client
        self.assertNotIn('claim_projects', remote_client.READS)


class RebindInterfaceTests(unittest.TestCase):
    """Colleagues must be able to move an account themselves; verify the whole chain."""

    def test_rebind_is_a_signed_write_and_installation_level(self):
        import remote_client
        self.assertIn('rebind_account', remote_client.WRITES)
        self.assertNotIn('rebind_account', remote_client.READS)

    def test_both_client_entries_expose_rebind(self):
        import subprocess, sys
        from pathlib import Path
        base = Path(__file__).resolve().parent.parent / 'skills/oceanengine-ads/scripts'
        for script, needle in (('ads.py', 'rebind-account'), ('setup.py', 'rebind-account')):
            out = subprocess.run([sys.executable, str(base / script), '--help'],
                                 capture_output=True, text=True)
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertIn(needle, out.stdout, script)

    def test_rebind_requires_both_games_and_rejects_equal_pair(self):
        import account_access, os, tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / 'c.json'
            cfg.write_text('{"base_url":"https://gw.example.test","key":"%s","accounts":{"main":{"id":"1"}},"default_account":"main","access_mode":"operator"}' % ('a'*64))
            cfg.chmod(0o600)
            old = os.environ.get('OCEANENGINE_MANAGEMENT_CONFIG')
            os.environ['OCEANENGINE_MANAGEMENT_CONFIG'] = str(cfg)
            try:
                for bad in (('', 'x'), ('ttA', ''), ('ttA', 'ttA')):
                    with self.assertRaises(ValueError):
                        account_access.rebind_account('main=1', 'rebind-test-0001', bad[0], bad[1], dry_run=True)
                preview = account_access.rebind_account('main=1', 'rebind-test-0002', 'ttOld000001', 'ttNew000001', dry_run=True)
                self.assertEqual(preview['status'], 'preview')
                self.assertFalse(preview['scope_changed'])
                self.assertEqual(preview['plan']['steps'][0]['args']['from_game_app_id'], 'ttOld000001')
            finally:
                if old is None: os.environ.pop('OCEANENGINE_MANAGEMENT_CONFIG', None)
                else: os.environ['OCEANENGINE_MANAGEMENT_CONFIG'] = old
