"""Check the Ops Agent helper and configuration from #92 without installing anything.

The helper runs with fake apt-get, dpkg-query and systemctl in a temporary directory.
"""

import base64
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "templates"
CONFIG = TEMPLATES / "ops-agent-config.yaml"
BASH = shutil.which("bash") if os.name == "posix" else None


def rendered_helper():
    # Same substitutions as templatefile() in main.tf.
    text = (TEMPLATES / "team-ops-agent.sh.tftpl").read_text(encoding="utf-8")
    text = text.replace("${config}", base64.b64encode(CONFIG.read_bytes()).decode())
    assert "${" not in text.replace("$${", ""), "Unrendered template variable"
    return text.replace("$${", "${")


class ConfigTests(unittest.TestCase):
    def test_only_the_journal_is_sent_and_metrics_are_off(self):
        lines = [line.rstrip() for line in CONFIG.read_text().splitlines()
                 if line.strip() and not line.lstrip().startswith("#")]
        self.assertEqual(lines, [
            "logging:",
            "  receivers:",
            "    journald:",
            "      type: systemd_journald",
            "  service:",
            "    pipelines:",
            "      default_pipeline:",
            "        receivers: [journald]",
            "metrics:",
            "  service:",
            "    pipelines:",
            "      default_pipeline:",
            "        receivers: []",
        ])


@unittest.skipUnless(BASH, "Requires bash")
class HelperTests(unittest.TestCase):
    def run_helper(self, installed=False, previous_config=None, keyring=True, codename="trixie"):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        etc = root / "etc"
        (etc / "apt/keyrings").mkdir(parents=True)
        if keyring:
            (etc / "apt/keyrings/google-keyring.gpg").write_bytes(b"key")
        (etc / "os-release").write_text(f'ID=debian\nVERSION_CODENAME={codename}\n')
        if previous_config is not None:
            (etc / "google-cloud-ops-agent").mkdir()
            (etc / "google-cloud-ops-agent/config.yaml").write_bytes(previous_config)
        calls = root / "calls"
        fakes = {
            "apt-get": "exit 0",
            "dpkg-query": f'[ {int(installed)} = 1 ] && printf "install ok installed"; exit {0 if installed else 1}',
            "systemctl": "exit 0",
        }
        env = dict(os.environ, TEAM_ETC=str(etc))
        for name, body in fakes.items():
            fake = root / name
            fake.write_text(f'#!/bin/sh\necho "{name} $*" >> "{calls}"\n{body}\n')
            fake.chmod(0o755)
            env["TEAM_" + name.upper().replace("-", "_")] = str(fake)
        script = root / "helper.sh"
        script.write_text(rendered_helper(), encoding="utf-8")
        result = subprocess.run([BASH, str(script)], text=True, capture_output=True, env=env)
        log = calls.read_text().splitlines() if calls.exists() else []
        return result, etc, log

    def test_fresh_install_writes_config_first_and_restarts(self):
        result, etc, log = self.run_helper()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((etc / "google-cloud-ops-agent/config.yaml").read_bytes(), CONFIG.read_bytes())
        self.assertEqual((etc / "apt/sources.list.d/google-cloud-ops-agent.list").read_text(),
                         "deb [signed-by=/etc/apt/keyrings/google-keyring.gpg] "
                         "https://packages.cloud.google.com/apt google-cloud-ops-agent-trixie-all main\n")
        self.assertEqual([line.split()[0] for line in log],
                         ["dpkg-query", "apt-get", "apt-get", "systemctl", "systemctl"])
        self.assertIn("--force-confold", log[2])
        self.assertTrue(log[2].endswith("google-cloud-ops-agent"))
        self.assertEqual(log[3:], ["systemctl enable google-cloud-ops-agent.service",
                                   "systemctl restart google-cloud-ops-agent.service"])
        self.assertFalse((etc / "google-cloud-ops-agent/config.yaml.new").exists())

    def test_unchanged_installation_is_left_running(self):
        result, _, log = self.run_helper(installed=True, previous_config=CONFIG.read_bytes())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("apt-get", " ".join(log))
        self.assertEqual(log[-1], "systemctl enable google-cloud-ops-agent.service")

    def test_changed_configuration_restarts_without_reinstalling(self):
        result, etc, log = self.run_helper(installed=True, previous_config=b"logging: {}\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("apt-get", " ".join(log))
        self.assertEqual(log[-1], "systemctl restart google-cloud-ops-agent.service")
        self.assertEqual((etc / "google-cloud-ops-agent/config.yaml").read_bytes(), CONFIG.read_bytes())

    def test_missing_key_or_odd_codename_stops_before_touching_apt(self):
        for kwargs in (dict(keyring=False), dict(codename="trixie main"), dict(codename="")):
            with self.subTest(**kwargs):
                result, etc, log = self.run_helper(**kwargs)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(log, [])
                self.assertFalse((etc / "apt/sources.list.d").exists())


if __name__ == "__main__":
    unittest.main()
