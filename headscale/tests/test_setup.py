import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("headscale_setup", Path(__file__).resolve().parents[1] / "setup.py")
SETUP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SETUP)
RESOLVER = "100.64.0.2"


class ConfigurationTests(unittest.TestCase):
    def test_rejects_invalid_endpoints(self):
        for url in ("http://hs.example.com", "https://user:secret@hs.example.com",
                    "https://hs.example.com/path", "https://hs.example.com:8080",
                    "https://hs.example.com/", "https://127.0.0.1"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                SETUP.configuration(url, "tail.example.com", RESOLVER)

    def test_requires_distinct_dns_domain(self):
        for domain in ("hs.example.com", "tail.example.com.", "bad domain", "a;touch.x"):
            with self.subTest(domain=domain), self.assertRaises(ValueError):
                SETUP.configuration("https://hs.example.com", domain, RESOLVER)

    def test_admin_interfaces_and_dns_are_limited(self):
        config = SETUP.configuration("https://hs.example.com", "tail.example.com", RESOLVER)
        self.assertEqual(config["listen_addr"], "0.0.0.0:8080")
        self.assertTrue(config["grpc_listen_addr"].startswith("127.0.0.1:"))
        self.assertTrue(config["metrics_listen_addr"].startswith("127.0.0.1:"))
        self.assertFalse(config["grpc_allow_insecure"])
        self.assertFalse(config["dns"]["override_local_dns"])
        self.assertEqual(config["trusted_proxies"], ["10.0.0.2/32"])

    def test_policy_uses_file_mode(self):
        config = SETUP.configuration("https://hs.example.com", "tail.example.com", RESOLVER)
        self.assertEqual(
            config["policy"],
            {
                "mode": "file",
                "path": "/etc/headscale/policy.hujson",
            },
        )

    def test_split_dns_sends_only_the_lab_zone_to_the_jumphost(self):
        config = SETUP.configuration("https://hs.example.com", "tail.example.com", RESOLVER)
        self.assertEqual(config["dns"]["nameservers"],
                         {"global": [], "split": {"itsx25.chas-lab.dev": ["100.64.0.2"]}})
        # MagicDNS stays separate from the lab zone and local DNS is not overridden.
        self.assertTrue(config["dns"]["magic_dns"])
        self.assertEqual(config["dns"]["base_domain"], "tail.example.com")
        self.assertFalse(config["dns"]["override_local_dns"])

    def test_rejects_resolvers_outside_the_tailnet(self):
        for resolver in ("10.0.5.2", "169.254.169.254", "100.64.0.0", "100.128.0.1",
                         "fd7a:115c:a1e0::2", "100.64.0.2/32", ""):
            with self.subTest(resolver=resolver), self.assertRaises(ValueError):
                SETUP.configuration("https://hs.example.com", "tail.example.com", resolver)

    def test_install_and_reconfigure_require_rendered_configuration(self):
        config = SETUP.configuration("https://hs.example.com", "tail.example.com", RESOLVER)
        self.assertEqual(SETUP.expected_configuration(config), config)
        for change in (
            lambda c: c["dns"]["nameservers"]["split"]["itsx25.chas-lab.dev"].append("100.64.0.3"),
            lambda c: c["dns"]["nameservers"]["split"].update({"example.com": [RESOLVER]}),
            lambda c: c["dns"].update({"override_local_dns": True}),
            lambda c: c.update({"listen_addr": "127.0.0.1:8080"}),
        ):
            changed = json.loads(json.dumps(config))
            change(changed)
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                SETUP.expected_configuration(changed)
        missing = json.loads(json.dumps(config))
        missing["dns"]["nameservers"]["split"] = {}
        with self.assertRaises(KeyError):
            SETUP.expected_configuration(missing)

    def test_only_split_dns_may_differ_on_reconfigure(self):
        before = SETUP.configuration("https://hs.example.com", "tail.example.com", RESOLVER)
        before["dns"]["nameservers"]["split"] = {}
        after = SETUP.configuration("https://hs.example.com", "tail.example.com", RESOLVER)
        self.assertEqual(SETUP.without_split_dns(before), SETUP.without_split_dns(after))
        self.assertEqual(before["dns"]["nameservers"]["split"], {}, "The input must not be modified.")
        other = SETUP.configuration("https://hs.example.com", "other.example.com", RESOLVER)
        self.assertNotEqual(SETUP.without_split_dns(before), SETUP.without_split_dns(other))

    @unittest.skipUnless(os.name == "posix" and Path("/run/lock").is_dir(), "Requires the Linux lock directory")
    def test_reconfigure_keeps_backup_and_rolls_back_on_failure(self):
        old = SETUP.configuration("https://hs.example.com", "tail.example.com", RESOLVER)
        old["dns"]["nameservers"]["split"] = {}
        new = SETUP.configuration("https://hs.example.com", "tail.example.com", RESOLVER)
        installed = subprocess.CompletedProcess([], 0, f"install ok installed|{SETUP.VERSION}")
        for restart_fails in (False, True):
            with self.subTest(restart_fails=restart_fails), tempfile.TemporaryDirectory() as directory:
                target = Path(directory) / "config.yaml"
                target.write_text(json.dumps(old), encoding="utf-8")
                source = Path(directory) / "rendered.json"
                source.write_text(json.dumps(new), encoding="utf-8")

                def run(*args, check=True):
                    if args[:2] == ("systemctl", "restart") and check and restart_fails:
                        raise subprocess.CalledProcessError(1, args)
                    return installed

                with patch.object(SETUP, "run", side_effect=run) as calls, \
                        patch.object(SETUP, "validate_as_service_user"), \
                        patch.object(SETUP, "wait_until_ready"), \
                        patch.object(SETUP.os, "geteuid", return_value=0), \
                        patch.object(SETUP.shutil, "chown"):
                    if restart_fails:
                        with self.assertRaises(subprocess.CalledProcessError):
                            SETUP.reconfigure(source, target)
                        self.assertEqual(json.loads(target.read_text()), old)
                        self.assertIn(("systemctl", "restart", "headscale.service"),
                                      [call.args for call in calls.call_args_list])
                    else:
                        SETUP.reconfigure(source, target)
                        self.assertEqual(json.loads(target.read_text()), new)
                        self.assertEqual(target.stat().st_mode & 0o777, 0o640)
                backups = list(Path(directory).glob("config.yaml.*.bak"))
                self.assertEqual(len(backups), 1)
                self.assertEqual(json.loads(backups[0].read_text()), old)
                self.assertFalse(SETUP.candidate_path(target).exists())

    @unittest.skipUnless(os.name == "posix" and Path("/run/lock").is_dir(), "Requires the Linux lock directory")
    def test_reconfigure_refuses_other_changes(self):
        current = SETUP.configuration("https://hs.example.com", "old.example.com", RESOLVER)
        new = SETUP.configuration("https://hs.example.com", "tail.example.com", RESOLVER)
        installed = subprocess.CompletedProcess([], 0, f"install ok installed|{SETUP.VERSION}")
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "config.yaml"
            target.write_text(json.dumps(current), encoding="utf-8")
            source = Path(directory) / "rendered.json"
            source.write_text(json.dumps(new), encoding="utf-8")
            with patch.object(SETUP, "run", return_value=installed), \
                    patch.object(SETUP.os, "geteuid", return_value=0), \
                    self.assertRaises(ValueError):
                SETUP.reconfigure(source, target)
            self.assertEqual(json.loads(target.read_text()), current)
            self.assertEqual(list(Path(directory).glob("*.bak")), [])

    def test_existing_users_are_preserved(self):
        existing = [{"name": name} for name in SETUP.USERS] + [{"name": "someone-else"}]
        with patch.object(SETUP, "run", return_value=subprocess.CompletedProcess([], 0, json.dumps(existing))) as run:
            SETUP.ensure_users()
            self.assertEqual(run.call_count, 1)


@unittest.skipUnless(os.environ.get("HEADSCALE_TEST_BINARY"), "Set HEADSCALE_TEST_BINARY for real binary tests")
class BinaryTests(unittest.TestCase):
    @unittest.skipUnless(hasattr(os, "geteuid") and os.geteuid() == 0, "Requires root to test service-user ownership")
    def test_config_validation_creates_data_as_service_user(self):
        import pwd

        account = pwd.getpwnam("nobody")
        binary = os.environ["HEADSCALE_TEST_BINARY"]
        with tempfile.TemporaryDirectory(prefix="headscale-owner-test-") as directory:
            root = Path(directory)
            root.chmod(0o755)
            data = root / "data"
            data.mkdir(mode=0o750)
            os.chown(data, account.pw_uid, account.pw_gid)
            config = SETUP.configuration("https://hs.example.invalid", "tail.example.invalid", RESOLVER)
            config["noise"]["private_key_path"] = str(data / "noise.key")
            config["database"]["sqlite"]["path"] = str(data / "db.sqlite")
            config["unix_socket"] = str(data / "headscale.sock")
            path = root / "config.yaml"
            path.write_text(json.dumps(config), encoding="utf-8")
            os.chown(path, 0, account.pw_gid)
            path.chmod(0o640)
            SETUP.validate_as_service_user(path, binary, account.pw_name)
            key_before = (data / "noise.key").read_bytes()
            SETUP.validate_as_service_user(path, binary, account.pw_name)
            self.assertEqual((data / "noise.key").read_bytes(), key_before)
            for filename in ("noise.key", "db.sqlite"):
                self.assertEqual((data / filename).stat().st_uid, account.pw_uid)
                self.assertEqual((data / filename).stat().st_mode & 0o007, 0)

    def test_real_config_and_repeatable_user_creation(self):
        binary = os.environ["HEADSCALE_TEST_BINARY"]
        with tempfile.TemporaryDirectory(prefix="headscale-test-") as directory:
            config = SETUP.configuration("https://hs.example.invalid", "tail.example.invalid", RESOLVER)
            config["noise"]["private_key_path"] = directory + "/noise.key"
            config["database"]["sqlite"]["path"] = directory + "/db.sqlite"
            config["unix_socket"] = directory + "/headscale.sock"
            config["listen_addr"] = "127.0.0.1:0"
            config["metrics_listen_addr"] = ""
            config["grpc_listen_addr"] = "127.0.0.1:0"
            path = Path(directory) / "config.yaml"
            path.write_text(json.dumps(config), encoding="utf-8")
            SETUP.run(binary, "--config", str(path), "configtest")
            # reconfigure validates the new file under this name before replacing the old one.
            candidate = SETUP.candidate_path(path)
            candidate.write_text(json.dumps(config), encoding="utf-8")
            SETUP.run(binary, "--config", str(candidate), "configtest")
            candidate.unlink()
            with (Path(directory) / "server.log").open("w+") as log:
                server = subprocess.Popen([binary, "--config", str(path), "serve"], stdout=log, stderr=log)
                try:
                    for attempt in range(30):
                        if server.poll() is not None:
                            log.seek(0)
                            self.fail(log.read())
                        if Path(config["unix_socket"]).exists():
                            break
                        time.sleep(1)
                    else:
                        log.seek(0)
                        self.fail("Server readiness timeout: " + log.read())
                    SETUP.ensure_users(binary, str(path))
                    first = json.loads(SETUP.run(binary, "--config", str(path), "users", "list", "-o", "json").stdout)
                    SETUP.ensure_users(binary, str(path))
                    second = json.loads(SETUP.run(binary, "--config", str(path), "users", "list", "-o", "json").stdout)
                    self.assertEqual(first, second)
                    self.assertEqual({user["name"] for user in second}, set(SETUP.USERS))
                finally:
                    server.terminate()
                    server.wait(timeout=15)


if __name__ == "__main__":
    unittest.main()
