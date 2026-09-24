import base64
import hashlib
import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location(
    "release_monitor", Path(__file__).resolve().parents[2] / "scripts/headscale-release-monitor.py",
)
MONITOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MONITOR)
SOURCE = 'VERSION = "0.29.3"\nPACKAGE_SHA256 = "' + "a" * 64 + '"\nOTHER = "keep"\n'
CHECKSUM = hashlib.sha256(b"verified package").hexdigest()
UPDATED = MONITOR.render_source(SOURCE, "0.29.4", CHECKSUM)


def release(tag, **overrides):
    return {"tag_name": tag, "draft": False, "prerelease": False, **overrides}


class ReleaseTests(unittest.TestCase):
    def test_only_stable_releases_and_numeric_order(self):
        result = MONITOR.choose_release("0.29.3", [
            release("v0.29.4"), release("v0.29.10"), release("v0.29.11", draft=True),
            release("v0.30.0", prerelease=True), release("v0.30.0-rc.1"), release("bad"),
        ])
        self.assertEqual(result["tag_name"], "v0.29.10")

    def test_remaining_patches_before_next_minor(self):
        result = MONITOR.choose_release("0.28.0", [release("v0.29.4"), release("v0.28.2")])
        self.assertEqual(result["tag_name"], "v0.28.2")

    def test_next_minor_latest_patch_without_skipping(self):
        result = MONITOR.choose_release("0.28.2", [
            release("v0.30.1"), release("v0.29.0"), release("v0.29.4"),
        ])
        self.assertEqual(result["tag_name"], "v0.29.4")

    def test_missing_minor_or_major_requires_review(self):
        for tag in ("v0.31.0", "v1.0.0"):
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                MONITOR.choose_release("0.29.3", [release(tag)])

    def test_no_downgrade_or_change_for_equal_version(self):
        self.assertIsNone(MONITOR.choose_release("0.29.3", [release("v0.29.3"), release("v0.28.0")]))

    def test_verified_download_and_exact_asset(self):
        candidate = release("v0.29.4", assets=[
            {"name": "headscale_0.29.4_linux_amd64.deb"}, {"name": "checksums.txt"},
        ])
        checksums = ("0" * 64 + "  other.deb\n" + CHECKSUM + "  headscale_0.29.4_linux_amd64.deb\n").encode()
        with patch.object(MONITOR, "read_url", side_effect=[checksums, b"verified package"]) as fetch:
            self.assertEqual(MONITOR.verified_checksum(candidate), CHECKSUM)
            self.assertEqual(fetch.call_args.args[0],
                             "https://github.com/juanfont/headscale/releases/download/v0.29.4/headscale_0.29.4_linux_amd64.deb")

    def test_bad_or_duplicate_checksum_and_tampered_package(self):
        candidate = release("v0.29.4", assets=[
            {"name": "headscale_0.29.4_linux_amd64.deb"}, {"name": "checksums.txt"},
        ])
        line = f"{CHECKSUM}  headscale_0.29.4_linux_amd64.deb\n".encode()
        for checksum_file in (b"bad", line + line, line):
            with self.subTest(checksum_file=checksum_file):
                with patch.object(MONITOR, "read_url", side_effect=[checksum_file, b"tampered"]):
                    with self.assertRaises(ValueError):
                        MONITOR.verified_checksum(candidate)

    def test_missing_or_duplicate_asset_fails_before_download(self):
        for names in (["checksums.txt"], ["checksums.txt", "checksums.txt", "headscale_0.29.4_linux_amd64.deb"]):
            with self.subTest(names=names), patch.object(MONITOR, "read_url") as fetch:
                with self.assertRaises(ValueError):
                    MONITOR.verified_checksum(release("v0.29.4", assets=[{"name": name} for name in names]))
                fetch.assert_not_called()

    def test_only_two_pin_lines_change(self):
        self.assertEqual(UPDATED, f'VERSION = "0.29.4"\nPACKAGE_SHA256 = "{CHECKSUM}"\nOTHER = "keep"\n')
        for invalid in (SOURCE + 'VERSION = "0.29.3"\n', SOURCE.replace("PACKAGE_SHA256", "HASH")):
            with self.assertRaises(ValueError):
                MONITOR.render_source(invalid, "0.29.4", CHECKSUM)
        for invalid in ("0.29.4;echo bad", "0.29.4\n", "v0.29.4"):
            with self.assertRaises(ValueError):
                MONITOR.render_source(SOURCE, invalid, CHECKSUM)


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            "GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": MONITOR.REPOSITORY,
            "GITHUB_REF": "refs/heads/main", "GITHUB_EVENT_NAME": "schedule",
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.branch_exists = False
        self.branch_content = SOURCE
        self.main_content = SOURCE
        self.open_prs = []
        self.previous_prs = []
        self.writes = []
        self.fail_create_pr = False
        self.branch_files = [MONITOR.SOURCE_PATH]
        self.api = patch.object(MONITOR, "github", side_effect=self.fake_github)
        self.api.start()
        self.addCleanup(self.api.stop)

    def fake_github(self, endpoint, method="GET", payload=None, paginate=False):
        if method != "GET":
            self.writes.append((endpoint, method, payload))
            if endpoint.endswith("/git/refs"):
                self.branch_exists = True
            elif "/contents/" in endpoint:
                self.branch_content = base64.b64decode(payload["content"]).decode()
            elif endpoint.endswith("/pulls"):
                if self.fail_create_pr:
                    raise OSError("Simulated PR API failure after branch write")
                self.open_prs = [self.pr()]
                return self.pr()
            return {}
        if "/pulls?state=open" in endpoint:
            return self.open_prs
        if "/pulls?state=all" in endpoint:
            return self.previous_prs
        if endpoint.endswith("/git/ref/heads/main"):
            return {"object": {"sha": "main-sha"}}
        if "/git/matching-refs/" in endpoint:
            return [{"ref": "refs/heads/automation/headscale-v0.29.4"}] if self.branch_exists else []
        if "/compare/" in endpoint:
            return {"files": [{"filename": name} for name in self.branch_files]}
        if "/contents/" in endpoint:
            content = self.main_content if endpoint.endswith("ref=main-sha") else self.branch_content
            return {"sha": "blob-sha", "content": base64.b64encode(content.encode()).decode()}
        raise AssertionError(f"Unexpected API call: {endpoint}")

    def pr(self):
        return {"html_url": "https://github.com/example/pull/1", "head": {
            "ref": "automation/headscale-v0.29.4", "repo": {"full_name": MONITOR.REPOSITORY},
        }}

    def run_publish(self):
        return MONITOR.publish(SOURCE, UPDATED, "0.29.4", "Review and install manually")

    def test_creates_only_pin_commit_and_one_pr_rerun_is_noop(self):
        self.assertTrue(self.run_publish().startswith("Opened"))
        self.assertEqual(len(self.writes), 3)
        self.assertEqual(self.branch_content, UPDATED)
        self.assertTrue(self.writes[1][0].endswith("/contents/headscale/setup.py"))
        self.assertEqual(self.writes[2][2]["base"], "main")
        self.assertIn("awaits review", self.run_publish())
        self.assertEqual(len(self.writes), 3)

    def test_closed_pr_is_not_recreated(self):
        self.previous_prs = [self.pr()]
        self.assertIn("reopen", self.run_publish())
        self.assertEqual(self.writes, [])

    def test_other_pending_version_blocks_second_update(self):
        item = self.pr()
        item["head"]["ref"] = "automation/headscale-v0.29.5"
        self.open_prs = [item]
        self.assertIn("awaits review", self.run_publish())
        self.assertEqual(self.writes, [])

    def test_restart_after_partial_publication(self):
        self.fail_create_pr = True
        with self.assertRaises(OSError):
            self.run_publish()
        self.fail_create_pr = False
        self.writes.clear()
        self.assertTrue(self.run_publish().startswith("Opened"))
        self.assertEqual(len(self.writes), 1)
        self.assertTrue(self.writes[0][0].endswith("/pulls"))

    def test_refuses_stale_main_or_changed_branch(self):
        self.main_content = SOURCE + "# changed\n"
        with self.assertRaises(ValueError):
            self.run_publish()
        self.assertEqual(self.writes, [])
        self.main_content = SOURCE
        self.branch_exists = True
        self.branch_content = UPDATED + "# user edit\n"
        with self.assertRaises(ValueError):
            self.run_publish()
        self.assertEqual(self.writes, [])

    def test_refuses_local_fork_pr_or_feature_branch_publication(self):
        for field, value in (
            ("GITHUB_ACTIONS", "false"), ("GITHUB_REPOSITORY", "someone/fork"),
            ("GITHUB_REF", "refs/heads/feature/test"), ("GITHUB_EVENT_NAME", "pull_request"),
        ):
            with self.subTest(field=field), patch.dict(os.environ, {field: value}):
                with self.assertRaises(ValueError):
                    self.run_publish()
        self.assertEqual(self.writes, [])

    def test_refuses_unrelated_changes_on_orphan_branch(self):
        self.branch_exists = True
        self.branch_files.append("main.tf")
        with self.assertRaises(ValueError):
            self.run_publish()
        self.assertEqual(self.writes, [])

    def test_cli_preview_cannot_publish_or_change_source(self):
        candidate = release("v0.29.4")
        tracked = MONITOR.ROOT / MONITOR.SOURCE_PATH
        before = tracked.read_bytes()
        with patch.object(MONITOR, "github", return_value=[candidate]), \
                patch.object(MONITOR, "verified_checksum", return_value=CHECKSUM), \
                patch.object(MONITOR, "publish") as publish, \
                patch("sys.argv", ["headscale-release-monitor.py"]):
            MONITOR.main()
            publish.assert_not_called()
        self.assertEqual(tracked.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
