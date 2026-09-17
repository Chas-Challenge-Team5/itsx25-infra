"""Exercise the APT parser and unattended-upgrades matcher without upgrading packages."""

import importlib.machinery
import importlib.util
from pathlib import Path
import re
import tempfile
from types import SimpleNamespace
import unittest

import apt_pkg


POLICY = Path(__file__).resolve().parents[2] / "config/apt/52team5-tailscale-updates"
LOADER = importlib.machinery.SourceFileLoader("unattended_policy_test", "/usr/bin/unattended-upgrade")
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
UPGRADES = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(UPGRADES)


class UpdatePolicyTests(unittest.TestCase):
    def setUp(self):
        # A private configuration object: never read or change this host's APT policy.
        self.config = apt_pkg.Configuration()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".conf") as baseline:
            baseline.write('''
Unattended-Upgrade::Origins-Pattern {
    "origin=Debian,codename=trixie,label=Debian";
    "origin=Debian,codename=trixie-security,label=Debian-Security";
};
Unattended-Upgrade::Package-Blacklist { "existing-exclusion"; };
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
Unattended-Upgrade::Automatic-Reboot "false";
''')
            baseline.flush()
            apt_pkg.read_config_file(self.config, baseline.name)
        self.before = {key: self.config[key] for key in self.config.keys()
                       if not key.startswith("Unattended-Upgrade::Origins-Pattern")
                       and not key.startswith("Unattended-Upgrade::Package-Blacklist")}
        apt_pkg.read_config_file(self.config, str(POLICY))
        self.patterns = self.config.value_list("Unattended-Upgrade::Origins-Pattern")
        # Use Debian metadata even when the test runs on Ubuntu in CI.
        UPGRADES.DISTRO_CODENAME = "trixie"
        UPGRADES.DISTRO_ID = "Debian"

    def origin(self, **overrides):
        fields = dict(origin="Tailscale", label="Tailscale", site="pkgs.tailscale.com",
                      codename="trixie", component="main", archive="")
        return SimpleNamespace(**(fields | overrides))

    def test_tailscale_and_existing_debian_updates_are_allowed(self):
        for origin in (self.origin(),
                       self.origin(origin="Debian", label="Debian", site="deb.debian.org"),
                       self.origin(origin="Debian", label="Debian-Security",
                                   site="security.debian.org", codename="trixie-security")):
            with self.subTest(origin=origin):
                self.assertTrue(UPGRADES.is_allowed_origin(origin, self.patterns))

    def test_other_sources_and_distribution_releases_are_rejected(self):
        for change in (dict(origin="Other"), dict(label="Other"),
                       dict(site="untrusted.example"), dict(codename="bookworm"),
                       dict(component="other"),
                       dict(origin="cloud-sdk-trixie", label="cloud-sdk-trixie",
                            site="packages.cloud.google.com", codename="cloud-sdk-trixie")):
            with self.subTest(change=change):
                self.assertFalse(UPGRADES.is_allowed_origin(self.origin(**change), self.patterns))

    def test_headscale_is_excluded_without_excluding_tailscale(self):
        blacklist = self.config.value_list("Unattended-Upgrade::Package-Blacklist")
        self.assertIn("existing-exclusion", blacklist)
        self.assertTrue(any(re.match(pattern, "headscale") for pattern in blacklist))
        self.assertFalse(any(re.match(pattern, "tailscale") for pattern in blacklist))

    def test_periodic_updates_and_reboot_policy_are_preserved(self):
        after = {key: self.config[key] for key in self.config.keys()
                 if not key.startswith("Unattended-Upgrade::Origins-Pattern")
                 and not key.startswith("Unattended-Upgrade::Package-Blacklist")}
        self.assertEqual(after, self.before)


if __name__ == "__main__":
    unittest.main()
