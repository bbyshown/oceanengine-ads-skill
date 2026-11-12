import copy
import json
from pathlib import Path
import tempfile
import unittest

import ads


class Client:
    def __init__(self):self.jobs = {};self.keys = {};self.calls = [];self.fail_submit_once = False;self.pending = False;self.failure = False
    def submit(self, op, args, key):
        self.calls.append((op, copy.deepcopy(args), key))
        if key not in self.keys:
            job = str(len(self.jobs));self.keys[key] = job
            self.jobs[job] = {'id': job, 'status': 'done', 'result': {'code': 0, 'data': {'verified': True}}}
        job = self.keys[key]
        if self.fail_submit_once:self.fail_submit_once = False;raise TimeoutError()
        return {'job_id': job}
    def request(self, route, args):
        r = copy.deepcopy(self.jobs[args['job_id']])
        if self.failure:r.update(status='uncertain', result={'error': 'timeout'})
        return r


class AdsTests(unittest.TestCase):
    def setUp(self):
        self.inv = {'projects': [{'project_id': 100, 'name': 'AI_UBMAX_V02_ROI0.5', 'opt_status': 'ENABLE'},
                                 {'project_id': 200, 'name': 'AI_UBMAX_V05_ROI0.5', 'opt_status': 'DISABLE'}],
                    'ads': [{'promotion_id': 1, 'project_id': 100, 'opt_status': 'ENABLE'},
                            {'promotion_id': 2, 'project_id': 200, 'opt_status': 'DISABLE'}],
                    'managed_project_ids': [100, 200]}

    def test_alias_resolution_rejects_deleted_ambiguous_or_unmanaged(self):
        self.assertEqual(ads.resolve(self.inv, 'v2')['project_id'], 100)
        self.assertEqual(ads.resolve(self.inv, 'V05')['project_id'], 200)
        self.assertEqual(ads.resolve(self.inv, '100')['project_id'], 100)
        with self.assertRaises(ValueError):ads.resolve(self.inv, 'v09')
        self.inv['projects'].append(dict(self.inv['projects'][0], project_id=300))
        with self.assertRaises(ValueError):ads.resolve(self.inv, 'v02')

    def test_product_copy_update_retains_required_materials_without_readonly_fields(self):
        ad={'promotion_materials':{'title_material_list':[{'title':'Original game title','material_id':99}],
            'video_material_list':[{'video_id':'video','video_cover_id':'cover','image_mode':'CREATIVE_IMAGE_MODE_VIDEO_VERTICAL','video_hp_visibility':'HIDE_VIDEO_ON_HP','material_status':'OK'}],
            'mini_program_info':{'app_id':'game','url':'sslocal://game','params':''},
            'external_url_material_list':['https://landing.example.com/game?promotionid=__PROMOTION_ID__'],
            'call_to_action_buttons':['立即体验'],
            'product_info':{'titles':['Game'],'image_ids':['product'],'selling_points':['old'],'echo_titles':[]}}}
        original=copy.deepcopy(ad)
        patch=ads.merge_ad_patch(ad,{'promotion_materials':{'product_info':{'selling_points':['new one','new two','new three']}}})
        m=patch['promotion_materials']
        self.assertEqual(m['title_material_list'],[{'title':'Original game title'}])
        self.assertEqual(m['video_material_list'][0]['video_id'],'video');self.assertNotIn('material_status',m['video_material_list'][0])
        self.assertEqual(m['product_info']['titles'],['Game']);self.assertEqual(m['product_info']['image_ids'],['product'])
        self.assertEqual(m['product_info']['selling_points'],['new one','new two','new three']);self.assertNotIn('echo_titles',m['product_info'])
        self.assertEqual(m['call_to_action_buttons'],['立即体验']);self.assertEqual(ad,original)

    def test_switch_pauses_parent_and_ads_before_starting_destination(self):
        plan = ads.make_plan(self.inv, 'switch', ['V02', 'V05'])
        self.assertEqual([s['op'] for s in plan['steps']], ['set_project_status', 'set_ad_status', 'set_ad_status', 'set_project_status', 'inventory'])
        self.assertEqual(plan['steps'][0]['args'], {'project_ids': [100], 'opt_status': 'DISABLE'})
        self.assertEqual(plan['steps'][2]['args'], {'promotion_ids': [2], 'opt_status': 'ENABLE'})
        self.assertEqual(plan['steps'][3]['args'], {'project_ids': [200], 'opt_status': 'ENABLE'})

    def test_invalid_destination_is_rejected_before_any_switch(self):
        self.inv['ads'] = [self.inv['ads'][0]]
        with self.assertRaises(ValueError):ads.make_plan(self.inv, 'switch', ['V02', 'V05'])

    def test_keep_only_never_enables_or_deletes_kept_project(self):
        plan = ads.make_plan(self.inv, 'keep-only', ['V02'])
        self.assertEqual([s['op'] for s in plan['steps']], ['delete_ads', 'delete_projects', 'inventory'])
        self.assertEqual(plan['steps'][0]['args'], {'promotion_ids': [2]})
        self.assertEqual(plan['steps'][1]['args'], {'project_ids': [200]})
        self.inv['managed_project_ids'] = [100]
        with self.assertRaises(ValueError):ads.make_plan(self.inv, 'keep-only', ['V02'])

    def test_final_readback_checks_deleted_ids_and_switches(self):
        with self.assertRaises(RuntimeError):ads.verify_inventory(self.inv, {'deleted_project_ids': [200]})
        with self.assertRaises(RuntimeError):ads.verify_inventory(self.inv, {'keep_only': 100})
        with self.assertRaises(RuntimeError):ads.verify_inventory(self.inv, {'project_status': {'100': 'DISABLE'}})
        ads.verify_inventory(self.inv, {'project_status': {'100': 'ENABLE'}})

    def test_lost_submission_resumes_same_idempotent_job_and_does_not_repeat_success(self):
        c = Client();c.fail_submit_once = True
        p = {'steps': [{'op': 'set_account_budget', 'args': {'budget': 1000}}]}
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            with self.assertRaises(TimeoutError):ads.execute_plan(p, 'unit-operation', directory=directory, client=c)
            receipt = ads.execute_plan(p, 'unit-operation', directory=directory, client=c)
            self.assertEqual(receipt['status'], 'done');self.assertEqual(len(c.jobs), 1)
            self.assertEqual(c.calls[0][2], c.calls[1][2])
            ads.execute_plan(p, 'unit-operation', directory=directory, client=c)
            self.assertEqual(len(c.calls), 2)
            with self.assertRaises(ValueError):ads.execute_plan({'steps': []}, 'unit-operation', directory=directory, client=c)

    def test_uncertain_job_stops_later_steps_and_is_not_resubmitted(self):
        c = Client();c.failure = True
        p = {'steps': [{'op': 'delete_ads', 'args': {'promotion_ids': [2]}}, {'op': 'delete_projects', 'args': {'project_ids': [200]}}]}
        with tempfile.TemporaryDirectory() as temp:
            for i in range(2):
                with self.assertRaises(RuntimeError):ads.execute_plan(p, 'unit-uncertain', directory=Path(temp), client=c)
            self.assertEqual(len(c.calls), 1)

    def test_operation_receipt_cannot_be_replayed_in_another_account(self):
        first = Client();first.account_id = 12345
        second = Client();second.account_id = 67890
        plan = {'steps': [{'op': 'set_project_budget', 'args': {'project_id': 100, 'budget': 300}}]}
        with tempfile.TemporaryDirectory() as directory:
            ads.execute_plan(plan, 'account-bound-request', directory=Path(directory), client=first)
            with self.assertRaises(ValueError):
                ads.execute_plan(plan, 'account-bound-request', directory=Path(directory), client=second)
            self.assertEqual(second.calls, [])

    def test_ladder_creation_validates_whole_batch_before_execution(self):
        rows = [{'name': 'V%02d' % i, 'video_id': 'video-%d' % i, 'cover_id': 'cover-%d' % i} for i in range(1, 21)]
        items = ads.batch_items(rows, 300, roi_start=0.5, roi_end=0.6, prefix='AI_')
        plan = ads.creation_plan(items, 'new-ladder-request')
        goals = [s['args']['project']['roi_goal'] for s in plan['steps']]
        self.assertEqual((goals[0], goals[-1], len(set(goals))), (0.5, 0.6, 20))
        self.assertTrue(plan['create_paused_only'])
        self.assertEqual(len({s['args']['creation_id'] for s in plan['steps']}), 20)
        items[-1]['project']['roi_goal'] = 0.12345
        with self.assertRaises(ValueError): ads.creation_plan(items, 'new-ladder-request')

    def test_batch_product_image_defaults_overrides_and_full_validation(self):
        rows=[{'name':'one','video_id':'video-one','cover_id':'cover-one'},
              {'name':'two','video_id':'video-two','cover_id':'cover-two','product_image_id':'account-image-two'}]
        before=copy.deepcopy(rows)
        items=ads.batch_items(rows,300,roi_start=.5,roi_end=.6,product_image_id='account-image-default')
        plan=ads.creation_plan(items,'batch-image-test')
        self.assertEqual([s['args']['ad']['product_image_id'] for s in plan['steps']],['account-image-default','account-image-two'])
        self.assertEqual(rows,before);self.assertTrue(plan['create_paused_only'])
        items[-1]['ad']['product_image_id']=''
        with self.assertRaises(ValueError):ads.creation_plan(items,'batch-image-test')


if __name__ == '__main__':unittest.main()


class AdoptedCleanupTests(unittest.TestCase):
    """keep-only must not remove projects the tool never created."""

    def inventory(self):
        return {'projects': [{'project_id': 100, 'name': 'mine', 'opt_status': 'ENABLE'},
                             {'project_id': 200, 'name': 'theirs', 'opt_status': 'DISABLE'}],
                'ads': [{'promotion_id': 1, 'project_id': 100, 'opt_status': 'ENABLE'},
                        {'promotion_id': 2, 'project_id': 200, 'opt_status': 'DISABLE'}],
                'managed_project_ids': [100, 200], 'adopted_project_ids': [200]}

    def test_keep_only_requires_confirmation_for_adopted_projects(self):
        from ads import make_plan
        with self.assertRaises(ValueError) as error:
            make_plan(self.inventory(), 'keep-only', ['mine'])
        self.assertIn('adopted', str(error.exception))

    def test_confirmed_delete_marks_the_step_and_without_adopted_is_unchanged(self):
        from ads import make_plan
        plan = make_plan(self.inventory(), 'keep-only', ['mine'], options={'confirm_adopted': True})
        deletes = [s for s in plan['steps'] if s['op'] == 'delete_projects']
        self.assertTrue(deletes[0]['args']['confirm_adopted'])
        self.assertEqual(deletes[0]['args']['project_ids'], [200])
        inv = self.inventory(); inv['adopted_project_ids'] = []
        plain = [s for s in make_plan(inv, 'keep-only', ['mine'])['steps'] if s['op'] == 'delete_projects']
        self.assertNotIn('confirm_adopted', plain[0]['args'])

    def test_status_summary_exposes_managed_and_adopted_projects(self):
        import ads
        inv = self.inventory(); inv['adopted_project_ids'] = [200]; inv['account_budget'] = {}
        summary = ads.summary(inv)
        self.assertEqual(summary['managed_project_ids'], [100, 200])
        self.assertEqual(summary['adopted_project_ids'], [200])


class RoiWindowTests(unittest.TestCase):
    """Both IAA retrieval windows must pass the client schema and survive batching."""

    def project_args(self, mode):
        return {'creation_id': 'roi-window-test-01',
                'project': {'name': 'AI_win', 'budget': 300, 'roi_goal': .55, 'roi_mode': mode}}

    def test_both_windows_are_accepted_and_others_rejected(self):
        import creation_schema
        for mode in ('7d', '30d'):
            creation_schema.validate('new_project', self.project_args(mode))
        for mode in ('14d', '30', 'thirty', '', None, True):
            with self.assertRaises(ValueError):
                creation_schema.validate('new_project', self.project_args(mode))

    def test_batch_manifest_carries_each_rows_window(self):
        import ads
        rows = [{'name': 'r7', 'video_id': 'v7', 'cover_id': 'c7', 'roi_mode': '7d'},
                {'name': 'r30', 'video_id': 'v30', 'cover_id': 'c30', 'roi_mode': '30d'}]
        items = ads.batch_items(rows, 300, roi_start=.5, roi_end=.6)
        plan = ads.creation_plan(items, 'roi-window-batch-01')
        modes = [step['args']['project']['roi_mode'] for step in plan['steps']]
        self.assertEqual(modes, ['7d', '30d'])

    def test_cli_exposes_both_window_choices(self):
        """Assert against the parsed CLI, not its source text."""
        import subprocess, sys
        from pathlib import Path
        ads_py = Path(__file__).resolve().parent.parent / 'skills/oceanengine-ads/scripts/ads.py'
        out = subprocess.run([sys.executable, str(ads_py), 'new-project', '--help'],
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn('7d', out.stdout)
        self.assertIn('30d', out.stdout)
