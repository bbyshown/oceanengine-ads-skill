import json
from pathlib import Path
import subprocess
import sys
import unittest

import remote_client
import ubmax_pro_schema as schema


class UbmaxProContractTests(unittest.TestCase):
    def test_shipped_cli_prints_valid_flat_example_without_account(self):
        cli=Path(schema.__file__).with_name('ads.py')
        result=subprocess.check_output([sys.executable,str(cli),'ubmax-pro-schema'],text=True)
        payload=json.loads(result)
        schema.validate_creation(payload)
        self.assertNotIn(schema.CONFIRM,payload)
        self.assertIn('ubmax_pro_create_preview',remote_client.READS)
        self.assertIn('ubmax_pro_new_project',remote_client.WRITES)
        self.assertNotIn('ubmax_pro_new_project',remote_client.READS)

    def test_wrong_standard_shape_and_missing_confirmation_are_distinct(self):
        with self.assertRaisesRegex(ValueError,'missing: .*unexpected: ad, project'):
            schema.validate_creation({'project':{},'ad':{}},submit=True)
        with self.assertRaisesRegex(ValueError,schema.CONFIRM+'=true'):
            schema.validate_creation(schema.EXAMPLE,submit=True)
        schema.validate_creation(dict(schema.EXAMPLE,accept_scheduled_then_pause=True),submit=True)
