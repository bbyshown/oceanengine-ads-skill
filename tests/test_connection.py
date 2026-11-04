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
