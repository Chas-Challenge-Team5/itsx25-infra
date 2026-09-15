"""Verify approval checks fail closed when a protection is removed."""

from copy import deepcopy
from io import StringIO
import json
import os
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from scripts.check_apply_environment import check, main


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


@patch.dict(os.environ, {
    "GITHUB_TOKEN": "test-token",
    "GITHUB_REPOSITORY": "example/infra",
    "GITHUB_API_URL": "https://api.github.com",
})
class AuthenticatedEnvironmentTests(unittest.TestCase):
    @patch("scripts.check_apply_environment.urlopen")
    def test_both_requests_use_the_token(self, urlopen):
        urlopen.side_effect = [StringIO(json.dumps(data)) for data in (ENVIRONMENT, BRANCHES)]
        main()
        expected = "https://api.github.com/repos/example/infra/environments/terraform-apply"
        self.assertEqual(urlopen.call_count, 2)
        for call, url in zip(urlopen.call_args_list, (expected, f"{expected}/deployment-branch-policies")):
            request = call.args[0]
            self.assertEqual(request.full_url, url)
            self.assertEqual(request.get_header("Authorization"), "Bearer test-token")
            self.assertEqual(call.kwargs["timeout"], 30)

    @patch("scripts.check_apply_environment.urlopen")
    def test_missing_or_empty_token_stops_before_api_request(self, urlopen):
        for value in (None, "", " "):
            with self.subTest(token=value), patch.dict(os.environ):
                if value is None:
                    os.environ.pop("GITHUB_TOKEN", None)
                else:
                    os.environ["GITHUB_TOKEN"] = value
                with self.assertRaisesRegex(ValueError, "GITHUB_TOKEN is required"):
                    main()
        urlopen.assert_not_called()

    @patch("scripts.check_apply_environment.urlopen")
    def test_api_errors_stop_verification(self, urlopen):
        for status in (401, 403, 429, 500):
            for failed_request in (0, 1):
                with self.subTest(status=status, failed_request=failed_request):
                    responses = [StringIO(json.dumps(ENVIRONMENT))] if failed_request else []
                    error = HTTPError("https://api.github.com", status, "Test failure", {}, StringIO())
                    self.addCleanup(error.close)
                    urlopen.side_effect = responses + [error]
                    with self.assertRaises(HTTPError):
                        main()

    @patch("scripts.check_apply_environment.urlopen", return_value=StringIO("not JSON"))
    def test_invalid_api_response_stops_verification(self, urlopen):
        with self.assertRaises(json.JSONDecodeError):
            main()
