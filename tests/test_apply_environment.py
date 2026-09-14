"""Verify approval checks fail closed when a protection is removed."""

from copy import deepcopy
import unittest

from scripts.check_apply_environment import check


ENVIRONMENT = {
    "can_admins_bypass": False,
    "protection_rules": [{
        "type": "required_reviewers", "prevent_self_review": True,
        "reviewers": [{"type": "User"}],
    }],
    "deployment_branch_policy": {
        "protected_branches": False, "custom_branch_policies": True,
    },
}
BRANCHES = {"total_count": 1, "branch_policies": [{"name": "main", "type": "branch"}]}


class ApplyEnvironmentTests(unittest.TestCase):
    def test_configured_environment_passes(self):
        self.assertTrue(check(ENVIRONMENT, BRANCHES))

    def test_missing_or_weakened_protection_fails(self):
        for field in ENVIRONMENT:
            environment = deepcopy(ENVIRONMENT)
            del environment[field]
            with self.subTest(missing=field):
                self.assertFalse(check(environment, BRANCHES))
        for field, value in (("prevent_self_review", False), ("reviewers", [])):
            environment = deepcopy(ENVIRONMENT)
            environment["protection_rules"][0][field] = value
            self.assertFalse(check(environment, BRANCHES))
        self.assertFalse(check(ENVIRONMENT | {"can_admins_bypass": True}, BRANCHES))

    def test_other_branches_and_tags_fail(self):
        for policy in ({"name": "*", "type": "branch"}, {"name": "main", "type": "tag"}):
            self.assertFalse(check(ENVIRONMENT, {"total_count": 1, "branch_policies": [policy]}))
        self.assertFalse(check(ENVIRONMENT, BRANCHES | {"total_count": 2}))
        self.assertFalse(check(ENVIRONMENT, {}))
