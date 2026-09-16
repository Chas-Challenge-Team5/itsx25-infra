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


class ConfigurationTests(unittest.TestCase):
    def test_rejects_invalid_endpoints(self):
        for url in ("http://hs.example.com", "https://user:secret@hs.example.com",
                    "https://hs.example.com/path", "https://hs.example.com:8080",
                    "https://hs.example.com/", "https://127.0.0.1"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                SETUP.configuration(url, "tail.example.com")

    def test_requires_distinct_dns_domain(self):
        for domain in ("hs.example.com", "tail.example.com.", "bad domain", "a;touch.x"):
            with self.subTest(domain=domain), self.assertRaises(ValueError):
                SETUP.configuration("https://hs.example.com", domain)

    def test_admin_interfaces_and_dns_are_limited(self):
        config = SETUP.configuration("https://hs.example.com", "tail.example.com")
        self.assertEqual(config["listen_addr"], "0.0.0.0:8080")
        self.assertTrue(config["grpc_listen_addr"].startswith("127.0.0.1:"))
        self.assertTrue(config["metrics_listen_addr"].startswith("127.0.0.1:"))
        self.assertFalse(config["grpc_allow_insecure"])
        self.assertFalse(config["dns"]["override_local_dns"])
        self.assertEqual(config["trusted_proxies"], ["10.0.0.2/32"])

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
            config = SETUP.configuration("https://hs.example.invalid", "tail.example.invalid")
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
            config = SETUP.configuration("https://hs.example.invalid", "tail.example.invalid")
            config["noise"]["private_key_path"] = directory + "/noise.key"
            config["database"]["sqlite"]["path"] = directory + "/db.sqlite"
            config["unix_socket"] = directory + "/headscale.sock"
            config["listen_addr"] = "127.0.0.1:0"
            config["metrics_listen_addr"] = ""
            config["grpc_listen_addr"] = "127.0.0.1:0"
            path = Path(directory) / "config.yaml"
            path.write_text(json.dumps(config), encoding="utf-8")
            SETUP.run(binary, "--config", str(path), "configtest")
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
