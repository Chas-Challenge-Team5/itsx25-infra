"""Guards that matter when testing a backup containing production identities."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("restore", ROOT / "scripts/headscale-restore-check.py")
restore = importlib.util.module_from_spec(spec)
spec.loader.exec_module(restore)
spec = importlib.util.spec_from_file_location("setup", ROOT / "headscale/setup.py")
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class RestoreTests(unittest.TestCase):
    def test_test_config_preserves_identity_dns_and_original(self):
        original = setup.configuration("https://team5.itsx25.chas-lab.dev", "team5.arpa", "100.64.0.2")
        saved = json.loads(json.dumps(original))
        target = restore.test_configuration(original, Path("/var/tmp/restore-test"))
        self.assertEqual(original, saved)
        for key in ("server_url", "dns", "prefixes", "trusted_proxies"):
            self.assertEqual(target[key], original[key])
        self.assertEqual(target["derp"]["urls"], [])
        self.assertFalse(target["derp"]["server"]["enabled"])
        self.assertFalse(target["derp"]["auto_update_enabled"])
        self.assertTrue(target["disable_check_updates"])
        for key in ("listen_addr", "grpc_listen_addr", "metrics_listen_addr"):
            self.assertTrue(target[key].startswith("127.0.0.1:"))
        for value in (target["database"]["sqlite"]["path"], target["noise"]["private_key_path"],
                      target["policy"]["path"], target["unix_socket"]):
            self.assertTrue(value.startswith("/var/tmp/restore-test/"))

    def test_reject_external_database_and_unexpected_paths(self):
        for section, key, value in (("database", "type", "postgres"),
                                    ("noise", "private_key_path", "/outside/noise.key"),
                                    ("policy", "path", "/outside/policy.hujson")):
            config = setup.configuration("https://team5.itsx25.chas-lab.dev", "team5.arpa", "100.64.0.2")
            config[section][key] = value
            with self.assertRaises(ValueError):
                restore.test_configuration(config, Path("/var/tmp/restore-test"))

    def test_reject_snapshot_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config").write_text("test")
            restore.regular_tree(root)
            (root / "link").symlink_to(root / "config")
            with self.assertRaises(ValueError):
                restore.regular_tree(root)

    def test_reject_host_namespace(self):
        import os
        with self.assertRaisesRegex(ValueError, "separate network namespace"):
            restore.inside_namespace(Path("/nonexistent"), False, os.readlink("/proc/self/ns/net"))


if __name__ == "__main__":
    unittest.main()
