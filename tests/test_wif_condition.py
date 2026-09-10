"""Evaluate the Terraform-rendered trust condition using CEL, without GCP access.

Requires terraform on PATH and pip install -r tests/requirements.txt.
These tests verify policy logic, not live token exchange or IAM configuration.
"""

import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from celpy import CELEvalError, Environment, json_to_cel


REPOSITORY = "Chas-Challenge-Team5/itsx25-infra"
WORKFLOW = f"{REPOSITORY}/.github/workflows/deploy.yml@refs/heads/main"
VALID = {
    "repository": REPOSITORY,
    "repository_id": "1360159280",
    "repository_owner_id": "326026601",
    "ref": "refs/heads/main",
    "workflow_ref": WORKFLOW,
    "event_name": "push",
}


class WifConditionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        template = Path(__file__).resolve().parents[1] / "bootstrap/github-wif-condition.cel.tftpl"
        parameters = {
            "repository": json.dumps(REPOSITORY),
            "repository_id": json.dumps(VALID["repository_id"]),
            "owner_id": json.dumps(VALID["repository_owner_id"]),
            "workflow_ref": json.dumps(WORKFLOW),
        }
        # Terraform renders the real template in an empty directory, with no backend.
        expression = f"jsonencode(templatefile({json.dumps(template.as_posix())}, {json.dumps(parameters)}))"
        with tempfile.TemporaryDirectory(prefix="wif-condition-") as directory:
            result = subprocess.run(
                ["terraform", "console", "-no-color"], input=expression + "\n",
                cwd=directory, text=True, capture_output=True, check=True,
            )
        source = json.loads(json.loads(result.stdout.strip()))
        environment = Environment()
        cls.policy = environment.program(environment.compile(source))

    def allowed(self, claims):
        try:
            return self.policy.evaluate({"assertion": json_to_cel(claims)}) == True
        except CELEvalError:
            # Missing claims/type errors must never grant access.
            return False

    def test_main_deploy_events_are_allowed(self):
        for event in ("push", "workflow_dispatch"):
            with self.subTest(event=event):
                self.assertTrue(self.allowed(VALID | {"event_name": event}))

    def test_other_events_are_denied_even_with_main_ref(self):
        for event in ("pull_request", "pull_request_target", "workflow_run", "schedule", "dynamic"):
            with self.subTest(event=event):
                self.assertFalse(self.allowed(VALID | {"event_name": event}))

    def test_pr_and_branch_workflows_are_denied(self):
        for ref in ("refs/pull/28/merge", "refs/heads/feature", "refs/tags/main"):
            for event in ("push", "workflow_dispatch", "pull_request"):
                with self.subTest(ref=ref, event=event):
                    self.assertFalse(self.allowed(VALID | {
                        "ref": ref, "event_name": event,
                        "workflow_ref": f"{REPOSITORY}/.github/workflows/deploy.yml@{ref}",
                    }))

    def test_each_trust_boundary_is_enforced_independently(self):
        overrides = {
            "repository": "someone/itsx25-infra",
            "repository_id": "999999999",
            "repository_owner_id": "999999999",
            "ref": "refs/heads/feature",
            "workflow_ref": f"{REPOSITORY}/.github/workflows/other.yml@refs/heads/main",
            "event_name": "pull_request_target",
        }
        for field, value in overrides.items():
            with self.subTest(field=field):
                self.assertFalse(self.allowed(VALID | {field: value}))

    def test_missing_claims_are_denied(self):
        for field in VALID:
            with self.subTest(field=field):
                self.assertFalse(self.allowed({key: value for key, value in VALID.items() if key != field}))


if __name__ == "__main__":
    unittest.main()
