import copy
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

import ads
import monitor_ads as monitor


class MonitoringTests(unittest.TestCase):
    def setUp(self):
        source = Path(monitor.__file__).parent.parent / 'references/monitor-policy.example.json'
        self.policy = json.loads(source.read_text())
        self.snapshot = {'date': '2026-01-02', 'checked_at': '2026-01-02T18:00:00+08:00',
                         'target_missing': False, 'project_switch': 'ENABLE', 'ad_switch': 'ENABLE',
                         'ad_status': 'OK', 'cost': 20, 'impressions': 500, 'clicks': 10,
                         'activations': 2, 'revenue': 0, 'roi': 0, 'daily_budget': 300,
                         'roi_coefficient': 0.4}

    def test_small_sample_never_triggers_low_roi(self):
        state = {'started_at': 0}
        for stamp in (36000, 37800, 39600):
            state, alerts = monitor.evaluate(self.policy, state, self.snapshot, stamp)
            self.assertNotIn('low_roi', [a['code'] for a in alerts])

    def test_low_roi_requires_spaced_samples_and_alert_is_deduplicated(self):
        snap = dict(self.snapshot, cost=120, activations=20)
        state, alerts = monitor.evaluate(self.policy, {'started_at': 0}, snap, 36000)
        self.assertEqual(alerts, [])
        state, alerts = monitor.evaluate(self.policy, state, snap, 36001)
        self.assertEqual(alerts, [])
        state, alerts = monitor.evaluate(self.policy, state, snap, 37801)
        self.assertEqual([a['code'] for a in alerts], ['low_roi'])
        state, alerts = monitor.evaluate(self.policy, state, snap, 39601)
        self.assertEqual(alerts, [])

    def test_no_mutation_operation_can_enter_monitor_transport(self):
        with patch.object(ads, 'read') as downstream:
            with self.assertRaises(ValueError): monitor.read('set_ad_status', {}, object())
            downstream.assert_not_called()

    def test_missing_metric_is_not_zero(self):
        for value in ({}, {'stat_cost': None}, {'stat_cost': '--'}, {'stat_cost': 'NaN'}):
            with self.assertRaises(ValueError): monitor.number(value, 'stat_cost')
        self.assertEqual(monitor.number({'stat_cost': '0'}, 'stat_cost'), 0)

    def test_read_failure_preserves_success_and_only_notifies_once(self):
        with tempfile.TemporaryDirectory() as directory:
            policy_path = Path(directory) / 'policy.json'
            policy_path.write_text(json.dumps(self.policy))
            store = Path(directory) / 'state'
            now = datetime(2026, 1, 2, 18, tzinfo=ZoneInfo('Asia/Shanghai'))
            with patch.object(ads, 'select_account', return_value=self.policy['advertiser_id']), patch.object(monitor, 'fetch', return_value=self.snapshot) as fetch:
                first = monitor.run(policy_path, store, object(), now)
                self.assertFalse(first['should_report'])
                fetch.side_effect = TimeoutError('gateway unavailable')
                failed = [monitor.run(policy_path, store, object(), now + timedelta(minutes=30 * i)) for i in (1, 2, 3)]
            self.assertEqual([r['should_report'] for r in failed], [False, True, False])
            state_file = next(store.glob('state-*.json'))
            state = json.loads(state_file.read_text())
            self.assertEqual(state['last_snapshot'], self.snapshot)
            self.assertEqual(state['read_failures'], 3)
            self.assertFalse(failed[-1]['ad_mutations_performed'])

    def test_automatic_pause_policy_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'policy.json'
            target.write_text(json.dumps(dict(self.policy, automatic_pause=True)))
            with self.assertRaises(ValueError): monitor.run(target, Path(directory) / 'state')


if __name__ == '__main__': unittest.main()
