"""Real pinned binary, synthetic data and a loopback-only network namespace."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("restore", ROOT.parent / "scripts/headscale-restore-check.py")
restore = importlib.util.module_from_spec(spec)
spec.loader.exec_module(restore)
spec = importlib.util.spec_from_file_location("setup", ROOT / "setup.py")
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class RestoreBinaryTests(unittest.TestCase):
    def test_offline_server_and_post_health_abort(self):
        self.assertEqual(os.geteuid(), 0, "Run through sudo python3 headscale/check.py.")
        for abort in (False, True):
            with self.subTest(abort=abort), tempfile.TemporaryDirectory(prefix="restore-binary-test-") as directory:
                work = Path(directory)
                (work / "etc").mkdir()
                (work / "data").mkdir()
                shutil.copy2(os.environ["HEADSCALE_TEST_BINARY"], work / "headscale")
                shutil.copy2(ROOT / "policy.hujson", work / "etc/policy.hujson")
                config = setup.configuration("https://hs.example.invalid", "test.example.invalid", "100.64.0.2")
                (work / "test-config.json").write_text(json.dumps(restore.test_configuration(config, work)))
                (work / "derp.yaml").write_text(restore.offline_derp_map())
                for path in [work, *work.rglob("*")]:
                    os.chown(path, 65534, 65534)
                    path.chmod(0o700 if path.is_dir() or path.name == "headscale" else 0o600)
                command = ["unshare", "--net", "--pid", "--fork", "--kill-child=KILL", "--mount-proc",
                           "python3", str(ROOT.parent / "scripts/headscale-restore-check.py"),
                           "--inside", str(work), "--original-netns", os.readlink("/proc/self/ns/net")]
                if abort:
                    command.append("--abort-after-start")
                result = subprocess.run(command, capture_output=True, text=True, timeout=90)
                if abort:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("INJECTED_ABORT_AFTER_HEALTH", result.stderr)
                else:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(json.loads(result.stdout)["health"], "pass")
