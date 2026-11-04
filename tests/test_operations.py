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


if __name__ == '__main__':unittest.main()
