import base64
import copy
import json
import unittest

import operation_output as output


class OutputTests(unittest.TestCase):
    def test_preview_omits_binary_even_with_full_output_and_preserves_replay_input(self):
        encoded = base64.b64encode(b"content" * 100000).decode()
        plan = {"steps": [{"args": {"filename": "视频.mp4", "base64": encoded}}]}
        before = copy.deepcopy(plan)
        for full in (False, True):
            view = output.visible(plan, full)
            self.assertNotIn(encoded[:100], json.dumps(view))
            self.assertEqual(view["steps"][0]["args"]["upload_bytes"], 700000)
            self.assertLess(len(json.dumps(view)), 1000)
        self.assertEqual(plan, before)

    def test_large_queries_are_explicitly_bounded(self):
        data = {"accounts": [{"id": i} for i in range(1920)]}
        view = output.visible(data)
        self.assertEqual(len(view["accounts"]), 11)
        self.assertEqual(view["accounts"][-1]["total_items"], 1920)
        self.assertEqual(output.visible(data, full=True), data)

    def test_partial_creation_exposes_existing_id_and_pending_step(self):
        receipt = {"run_id": "original-run", "status": "uncertain", "steps": [
            {"job_id": "job-1", "status": "uncertain", "response": {"result": {
                "code": -1, "message": "Readback unavailable", "data": {
                    "creation_id": "original-creation",
                    "stages": {"project": {"project_id": 123}}
                }
            }}},
            {"status": "submitting"}
        ]}
        view = output.outcome(receipt)
        self.assertEqual(view["results"][0]["project_id"], 123)
        self.assertEqual(view["results"][0]["creation_id"], "original-creation")
        self.assertFalse(view["results"][0]["verified"])
        self.assertEqual(view["results"][1]["status"], "submitting")
