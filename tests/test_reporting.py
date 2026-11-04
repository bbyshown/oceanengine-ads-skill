import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import ads
import report_ads


class ReportingTests(unittest.TestCase):
    def run_report(self, rows, include_totals=True, ad_id='7'):
        inv = {'projects': [{'project_id': 100, 'name': 'AI_V02_test'}],
               'ads': [{'promotion_id': 7, 'project_id': 100}], 'managed_project_ids': [100]}
        metrics = ['stat_cost', 'show_cnt', 'click_cnt', 'active', 'attribution_micro_game_0d_roi']
        calls = []
        def read(op, args=None, client=None):
            calls.append((op, copy.deepcopy(args), client.account_id))
            if op == 'inventory': return {'data': inv}
            if op == 'report_config':
                return {'data': {'list': [{'data_topic': 'BASIC_DATA', 'metrics': [{'field': m} for m in metrics]}]}}
            data = {'rows': rows, 'page_info': {'total_page': 1}}
            if include_totals: data['total_metrics'] = {m: 0 for m in metrics}
            return {'data': data}
        argv = ['report_ads.py', '--account', 'secondary', '--project', 'V02',
                '--promotion-id', ad_id, '--date', '2026-01-02']
        with tempfile.TemporaryDirectory() as directory, patch.object(ads, 'ROOT', Path(directory)), \
                patch.object(report_ads.settings, 'select_account', return_value=67890), \
                patch.object(ads, 'read', side_effect=read), patch('sys.argv', argv), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            report_ads.main()
            return json.loads(out.getvalue()), calls

    def test_report_binds_account_project_and_ad_without_mutations(self):
        result, calls = self.run_report([])
        self.assertEqual(result['account_id'], 67890)
        self.assertEqual(result['total_metrics']['stat_cost'], 0)
        self.assertTrue(all(c[2] == 67890 for c in calls))
        self.assertEqual([c[0] for c in calls], ['inventory', 'report_config', 'report'])
        filters = calls[-1][1]['filters']
        self.assertEqual([f['values'] for f in filters], [['100'], ['7']])

    def test_absent_totals_cannot_be_reported_as_zero(self):
        with self.assertRaises(ValueError): self.run_report([], include_totals=False)

    def test_wrong_project_or_ad_is_rejected(self):
        for dims in ({'cdp_project_id': '200', 'cdp_promotion_id': '7'},
                     {'cdp_project_id': '100', 'cdp_promotion_id': '8'}):
            with self.assertRaises(ValueError): self.run_report([{'dimensions': dims}])
        with self.assertRaises(ValueError): self.run_report([], ad_id='8')


if __name__ == '__main__': unittest.main()
