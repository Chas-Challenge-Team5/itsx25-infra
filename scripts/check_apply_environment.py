"""Fail closed unless the public repository's apply environment is protected.

Public REST reads do not need a token with repository administration rights.
API errors, rate limits and unexpected responses stop the workflow before auth.
"""

import json
import os
import sys
from urllib.request import Request, urlopen


def check(environment, branches):
    rules = environment.get("protection_rules", [])
    reviewers = any(
        rule.get("type") == "required_reviewers"
        and rule.get("prevent_self_review") is True
        and bool(rule.get("reviewers"))
        for rule in rules
    )
    return (
        reviewers
        and environment.get("can_admins_bypass") is False
        and environment.get("deployment_branch_policy") == {
            "protected_branches": False, "custom_branch_policies": True,
        }
        and branches.get("total_count") == 1
        and len(branches.get("branch_policies", [])) == 1
        and branches["branch_policies"][0].get("name") == "main"
        and branches["branch_policies"][0].get("type") == "branch"
    )


def get(url):
    request = Request(url, headers={"Accept": "application/vnd.github+json"})
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def main():
    repo = os.environ["GITHUB_REPOSITORY"]
    api = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    url = f"{api}/repos/{repo}/environments/terraform-apply"
    if not check(get(url), get(f"{url}/deployment-branch-policies")):
        raise ValueError("Apply environment protection is incomplete.")
    print("Apply environment protection verified.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"::error::Cannot verify apply environment: {error}", file=sys.stderr)
        sys.exit(1)
