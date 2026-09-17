"""Check the sshd and resolved hardening from #86 without touching this host.

sshd -T runs against a private configuration as a normal user. The helper script
runs with fake sshd and systemctl in a temporary directory.
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
SSHD = shutil.which("sshd") or ("/usr/sbin/sshd" if Path("/usr/sbin/sshd").exists() else None)
BASH = shutil.which("bash") if os.name == "posix" else None


def rendered_helper():
    # Same substitutions as templatefile() in main.tf.
    text = (TEMPLATES / "team-host-hardening.sh.tftpl").read_text(encoding="utf-8")
    for name, source in (("sshd_config", "sshd-team5.conf"), ("resolved_config", "resolved-team5.conf")):
        encoded = base64.b64encode((TEMPLATES / source).read_bytes()).decode()
        text = text.replace("${" + name + "}", encoded)
    assert "${" not in text.replace("$${", ""), "Unrendered template variable"
    return text.replace("$${", "${")


class SshdPrecedenceTests(unittest.TestCase):
    def setUp(self):
        if not SSHD:
            if os.environ.get("CI"):
                self.fail("sshd is required in CI")
            self.skipTest("sshd is not installed")

    def effective(self, user):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "sshd_config.d").mkdir()
            shutil.copy(TEMPLATES / "sshd-team5.conf", root / "sshd_config.d/10-team5.conf")
            subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(root / "host_key")],
                           check=True)
            # Mirrors Debian's sshd_config and the guest agent: include first,
            # permissive defaults later, per-user Match blocks for OS Login last.
            (root / "sshd_config").write_text(f"""Include {root}/sshd_config.d/*.conf
HostKey {root}/host_key
X11Forwarding yes
AllowAgentForwarding yes
AuthorizedKeysFile .ssh/authorized_keys .ssh/authorized_keys2
AuthorizedKeysCommand /usr/bin/google_authorized_keys
AuthorizedKeysCommandUser root
Match User oslogin-user
    AuthorizedKeysFile /dev/null
""", encoding="utf-8")
            result = subprocess.run(
                [SSHD, "-T", "-f", str(root / "sshd_config"),
                 "-C", f"user={user},host=client.example,addr=100.64.0.10"],
                check=True, text=True, capture_output=True)
        values = {}
        for line in result.stdout.splitlines():
            key, _, value = line.partition(" ")
            values[key] = value
        return values

    def test_drop_in_wins_for_local_accounts(self):
        values = self.effective("local-user")
        self.assertEqual(values["authorizedkeysfile"], "none")
        self.assertEqual(values["x11forwarding"], "no")
        self.assertEqual(values["allowagentforwarding"], "no")
        self.assertEqual(values["authorizedkeyscommand"], "/usr/bin/google_authorized_keys")
        # ssh -J to primary needs TCP forwarding on the jumphost.
        self.assertEqual(values["allowtcpforwarding"], "yes")

    def test_os_login_users_keep_the_guest_agent_setting(self):
        values = self.effective("oslogin-user")
        self.assertEqual(values["authorizedkeysfile"], "/dev/null")
        self.assertEqual(values["x11forwarding"], "no")
        self.assertEqual(values["allowagentforwarding"], "no")


@unittest.skipUnless(BASH, "Requires bash")
class HelperTests(unittest.TestCase):
    def run_helper(self, sshd_ok=True, resolved_active=True, previous=None):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        etc = root / "etc"
        (etc / "ssh").mkdir(parents=True)
        (etc / "ssh/sshd_config").write_text("Include /etc/ssh/sshd_config.d/*.conf\n")
        if previous is not None:
            (etc / "ssh/sshd_config.d").mkdir()
            (etc / "ssh/sshd_config.d/10-team5.conf").write_text(previous)
        calls = root / "calls"
        fake_sshd = root / "sshd"
        fake_sshd.write_text(f'#!/bin/sh\necho "sshd $*" >> "{calls}"\nexit {0 if sshd_ok else 1}\n')
        fake_systemctl = root / "systemctl"
        fake_systemctl.write_text(
            f'#!/bin/sh\necho "systemctl $*" >> "{calls}"\n'
            f'[ "$1" = is-active ] && exit {0 if resolved_active else 3}\nexit 0\n')
        for fake in (fake_sshd, fake_systemctl):
            fake.chmod(0o755)
        script = root / "helper.sh"
        script.write_text(rendered_helper(), encoding="utf-8")
        result = subprocess.run(
            [BASH, str(script)], text=True, capture_output=True,
            env=os.environ | {"TEAM_ETC": str(etc), "TEAM_SSHD": str(fake_sshd),
                              "TEAM_SYSTEMCTL": str(fake_systemctl)})
        log = calls.read_text().splitlines() if calls.exists() else []
        return result, etc, log

    def test_writes_both_files_and_reloads_after_validation(self):
        result, etc, log = self.run_helper()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((etc / "ssh/sshd_config.d/10-team5.conf").read_bytes(),
                         (TEMPLATES / "sshd-team5.conf").read_bytes())
        self.assertEqual((etc / "systemd/resolved.conf.d/10-team5.conf").read_bytes(),
                         (TEMPLATES / "resolved-team5.conf").read_bytes())
        self.assertEqual((etc / "ssh/sshd_config.d/10-team5.conf").stat().st_mode & 0o777, 0o644)
        self.assertEqual(log, [
            f"sshd -t -f {etc}/ssh/sshd_config",
            "systemctl reload ssh.service",
            "systemctl is-active --quiet systemd-resolved.service",
            "systemctl restart systemd-resolved.service",
        ])

    def test_invalid_configuration_removes_new_file_and_skips_reload(self):
        result, etc, log = self.run_helper(sshd_ok=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(list((etc / "ssh/sshd_config.d").iterdir()), [])
        self.assertFalse((etc / "systemd/resolved.conf.d").exists())
        self.assertEqual(log, [f"sshd -t -f {etc}/ssh/sshd_config"])

    def test_invalid_configuration_restores_previous_file(self):
        result, etc, log = self.run_helper(sshd_ok=False, previous="# earlier version\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((etc / "ssh/sshd_config.d/10-team5.conf").read_text(), "# earlier version\n")
        self.assertEqual([p.name for p in (etc / "ssh/sshd_config.d").iterdir()], ["10-team5.conf"])
        self.assertNotIn("systemctl reload ssh.service", log)

    def test_existing_drop_in_is_replaced_without_leftovers(self):
        result, etc, _ = self.run_helper(previous="# earlier version\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((etc / "ssh/sshd_config.d/10-team5.conf").read_bytes(),
                         (TEMPLATES / "sshd-team5.conf").read_bytes())
        self.assertEqual([p.name for p in (etc / "ssh/sshd_config.d").iterdir()], ["10-team5.conf"])

    def test_resolved_only_restarts_when_active(self):
        result, etc, log = self.run_helper(resolved_active=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("systemctl restart systemd-resolved.service", log)
        self.assertTrue((etc / "systemd/resolved.conf.d/10-team5.conf").exists())


if __name__ == "__main__":
    unittest.main()
