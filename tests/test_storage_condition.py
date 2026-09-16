"""Verify CI object-access boundaries; live IAM and backend access need deployment tests."""

import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from celpy import CELEvalError, Environment, json_to_cel


BUCKET = "team5-test-state"
OBJECTS = f"projects/_/buckets/{BUCKET}/objects/"


class StorageConditionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        template = Path(__file__).resolve().parents[1] / "bootstrap/cicd-storage-condition.cel.tftpl"
        parameters = {
            "root_state_prefix": json.dumps(OBJECTS + "terraform/state/"),
            "deploy_plans_prefix": json.dumps(OBJECTS + "terraform/deploy-plans/"),
        }
        expression = f"jsonencode(templatefile({json.dumps(template.as_posix())}, {json.dumps(parameters)}))"
        with tempfile.TemporaryDirectory(prefix="storage-condition-") as directory:
            result = subprocess.run(
                ["terraform", "console", "-no-color"], input=expression + "\n",
                cwd=directory, text=True, capture_output=True, check=True,
            )
        source = json.loads(json.loads(result.stdout.strip()))
        environment = Environment()
        cls.policy = environment.program(environment.compile(source))

    def allowed(self, resource):
        try:
            return self.policy.evaluate({"resource": json_to_cel(resource)}) == True
        except CELEvalError:
            return False

    def test_root_state_locks_and_workspaces_are_allowed(self):
        for name in ("default.tfstate", "default.tflock", "test-workspace.tfstate", "test-workspace.tflock"):
            with self.subTest(name=name):
                self.assertTrue(self.allowed({"name": OBJECTS + "terraform/state/" + name}))

    def test_saved_deploy_plans_are_allowed(self):
        for name in ("123/1/deploy.tfplan", "123/2/deploy.tfplan"):
            with self.subTest(name=name):
                self.assertTrue(self.allowed({"name": OBJECTS + "terraform/deploy-plans/" + name}))

    def test_other_states_are_denied(self):
        for prefix in ("bootstrap-state", "access-state", "iap-access", "other"):
            for name in ("default.tfstate", "default.tflock"):
                with self.subTest(prefix=prefix, name=name):
                    self.assertFalse(self.allowed({"name": OBJECTS + f"terraform/{prefix}/{name}"}))

    def test_similar_prefixes_and_unrelated_objects_are_denied(self):
        for path in ("terraform/state-backup/default.tfstate", "terraform/states/default.tfstate",
                     "terraform/deploy-plans-backup/plan", "terraform/state", "terraform/deploy-plans",
                     "other/terraform/state/default.tfstate", "secret.txt"):
            with self.subTest(path=path):
                self.assertFalse(self.allowed({"name": OBJECTS + path}))

    def test_other_bucket_and_bucket_resource_are_denied(self):
        for resource in (f"projects/_/buckets/{BUCKET}",
                         "projects/_/buckets/another-bucket/objects/terraform/state/default.tfstate"):
            with self.subTest(resource=resource):
                self.assertFalse(self.allowed({"name": resource}))

    def test_missing_or_invalid_resource_name_is_denied(self):
        for resource in ({}, {"name": None}, {"name": 123}):
            with self.subTest(resource=resource):
                self.assertFalse(self.allowed(resource))


if __name__ == "__main__":
    unittest.main()
