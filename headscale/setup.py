"""Render configuration, install the initial Headscale control plane or change its Split DNS.

The installer does not upgrade existing versions or overwrite changed configuration.
reconfigure only accepts a Split DNS change and keeps a backup of the previous file.
Neither modifies SSH, OS Login, firewall rules, routing, or existing database files.
"""

import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit
from urllib.request import urlopen

VERSION = "0.29.3"
PACKAGE_SHA256 = "14eccf8d41fd93927ad3fe1fd9e49dbe14d5668a244c4205d940967c442aea0d"
PACKAGE_URL = f"https://github.com/juanfont/headscale/releases/download/v{VERSION}/headscale_{VERSION}_linux_amd64.deb"
USERS = ("admin", "adam", "armin", "abdi", "mattej", "viktor")
# The lab zone is resolved by dnsmasq on the jumphost (#51).
SPLIT_DNS_ZONE = "itsx25.chas-lab.dev"
TAILNET_V4 = ipaddress.ip_network("100.64.0.0/10")
POLICY_SOURCE = Path(__file__).resolve().with_name("policy.hujson")


def domain(value):
    labels = value.split(".")
    if len(value) > 253 or len(labels) < 2 or not all(
        re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
        for label in labels
    ) or labels[-1].isdigit():
        raise ValueError("Use a lowercase fully qualified DNS name without a trailing dot.")
    return value


def split_dns_resolver(value):
    try:
        address = ipaddress.IPv4Address(value)
    except ValueError:
        raise ValueError("The Split DNS resolver must be an IPv4 address.") from None
    if address not in TAILNET_V4 or address == TAILNET_V4.network_address:
        raise ValueError("The Split DNS resolver must be a node address in the tailnet.")
    return str(address)


def configuration(server_url, base_domain, resolver):
    url = urlsplit(server_url)
    hostname = domain(url.hostname or "")
    domain(base_domain)
    resolver = split_dns_resolver(resolver)
    if server_url != f"https://{hostname}" or url.username or url.password:
        raise ValueError("Use the registered HTTPS URL without credentials, port, path or trailing slash.")
    if hostname == base_domain:
        raise ValueError("The MagicDNS base domain must differ from the server hostname.")
    return {
        "server_url": server_url,
        "listen_addr": "0.0.0.0:8080",
        "metrics_listen_addr": "127.0.0.1:9090",
        "grpc_listen_addr": "127.0.0.1:50443",
        "grpc_allow_insecure": False,
        "trusted_proxies": ["10.0.0.2/32"],
        "noise": {"private_key_path": "/var/lib/headscale/noise_private.key"},
        "prefixes": {"v4": "100.64.0.0/10", "v6": "fd7a:115c:a1e0::/48"},
        "derp": {
            "server": {"enabled": False},
            "urls": ["https://controlplane.tailscale.com/derpmap/default"],
            "auto_update_enabled": True, "update_frequency": "3h",
        },
        "database": {"type": "sqlite", "sqlite": {
            "path": "/var/lib/headscale/db.sqlite", "write_ahead_log": True,
        }},
        "policy": {
            "mode": "file",
            "path": "/etc/headscale/policy.hujson",
        },
        "dns": {"magic_dns": True, "base_domain": base_domain,
                "override_local_dns": False, "nameservers": {"global": [], "split": {SPLIT_DNS_ZONE: [resolver]}}},
        "unix_socket": "/var/run/headscale/headscale.sock",
        "unix_socket_permission": "0770",
        "disable_check_updates": True,
        "log": {"level": "info", "format": "text"},
    }


def expected_configuration(config):
    resolvers = config["dns"]["nameservers"]["split"][SPLIT_DNS_ZONE]
    if not isinstance(resolvers, list) or len(resolvers) != 1:
        raise ValueError("Use exactly one Split DNS resolver.")
    expected = configuration(config["server_url"], config["dns"]["base_domain"], resolvers[0])
    if config != expected:
        raise ValueError("Use a fresh configuration produced by the render command.")
    return config


def without_split_dns(config):
    copy = json.loads(json.dumps(config))
    copy["dns"]["nameservers"]["split"] = None
    return copy


def run(*args, check=True):
    return subprocess.run(args, check=check, text=True, capture_output=True)


def download_package(destination):
    with urlopen(PACKAGE_URL, timeout=60) as source, destination.open("wb") as target:
        shutil.copyfileobj(source, target)
    if hashlib.sha256(destination.read_bytes()).hexdigest() != PACKAGE_SHA256:
        raise ValueError("Headscale package checksum does not match the pinned release.")


def ensure_users(binary="/usr/bin/headscale", config="/etc/headscale/config.yaml"):
    result = run(binary, "--config", config, "users", "list", "--output", "json")
    existing = {user["name"] for user in (json.loads(result.stdout) or [])}
    for user in USERS:
        if user not in existing:
            run(binary, "--config", config, "users", "create", user)


def validate_as_service_user(config, binary="/usr/bin/headscale", user="headscale"):
    # configtest creates the Noise key and SQLite database, not just a syntax check.
    # Use the same identity as the service so retries cannot create root-owned data.
    previous_umask = os.umask(0o077)  # Match the package's systemd UMask.
    try:
        return run("runuser", "--user", user, "--", binary, "--config", str(config), "configtest")
    finally:
        os.umask(previous_umask)


def install_policy(config):
    source = POLICY_SOURCE
    target = Path(config["policy"]["path"])
    if not source.is_file():
        raise ValueError(f"Policy file is missing from the repository: {source}")
    policy = source.read_bytes()
    if target.exists():
        if target.read_bytes() != policy:
            raise ValueError("Existing policy differs; back up and review changes separately.")
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(policy)
    shutil.chown(target, user="root", group="headscale")
    target.chmod(0o640)


def install(source):
    import fcntl

    if os.geteuid() != 0:
        raise ValueError("Installation requires root on the intended jumphost.")
    if run("dpkg", "--print-architecture").stdout.strip() != "amd64":
        raise ValueError("This installer supports Debian amd64 only.")
    if not Path("/run/systemd/system").is_dir():
        raise ValueError("A running systemd installation is required.")
    config = expected_configuration(json.loads(source.read_text(encoding="utf-8")))
    if any(config["server_url"].endswith(suffix) for suffix in (".invalid", ".example", ".test")):
        raise ValueError("Register the real Spectre domain before installation.")

    with open("/run/lock/team5-headscale.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        target = Path("/etc/headscale/config.yaml")
        package = run("dpkg-query", "-W", "-f=${Status}|${Version}", "headscale", check=False)
        installed = package.returncode == 0 and package.stdout.startswith("install ok installed|")
        if installed:
            if package.stdout.split("|")[-1].strip() != VERSION:
                raise ValueError("Existing Headscale version differs; plan a separate upgrade with backup.")
            if not target.exists() or json.loads(target.read_text()) != config:
                raise ValueError("Existing configuration differs; back up and review changes separately.")
        else:
            if shutil.which("headscale") or target.exists() or (
                Path("/var/lib/headscale").exists() and any(Path("/var/lib/headscale").iterdir())
            ):
                raise ValueError("Existing Headscale files found; inventory and back up before installation.")
            for port in (8080, 9090, 50443):
                if run("ss", "-H", "-lnt", f"sport = :{port}").stdout.strip():
                    raise ValueError(f"Port {port} is already in use.")
            if "masked" in run("systemctl", "is-enabled", "headscale.service", check=False).stdout:
                raise ValueError("Existing service mask must be reviewed before installation.")
            with tempfile.TemporaryDirectory(prefix="headscale-install-") as directory:
                deb = Path(directory) / "headscale.deb"
                download_package(deb)
                # The package postinst starts the service. Block that until configured.
                run("systemctl", "mask", "--runtime", "headscale.service")
                try:
                    run("dpkg", "--install", str(deb))
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if target.exists():
                        shutil.copy2(target, Path(directory) / "package-config.yaml")
                    target.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
                    shutil.chown(target, user="root", group="headscale")
                    target.chmod(0o640)
                    run("install", "-d", "-m", "0750", "-o", "headscale", "-g", "headscale", "/var/lib/headscale")
                except Exception:
                    run("systemctl", "disable", "--now", "headscale.service", check=False)
                    raise
                finally:
                    run("systemctl", "unmask", "--runtime", "headscale.service")

        install_policy(config)
        validate_as_service_user(target)
        run("systemctl", "enable", "--now", "headscale.service")
        wait_until_ready()
        ensure_users()
        run("systemctl", "is-active", "--quiet", "headscale.service")
        print("Headscale is running; six expected users exist. Verify the public HTTPS endpoint separately.")


def wait_until_ready():
    for attempt in range(30):
        result = run("/usr/bin/headscale", "users", "list", "--output", "json", check=False)
        if result.returncode == 0:
            return
        time.sleep(1)
    raise ValueError("Headscale did not become ready; inspect systemctl and journalctl.")


def candidate_path(target):
    # Headscale picks the parser from the file extension, so keep it last.
    return target.with_name(f".{target.stem}.new{target.suffix}")


def reconfigure(source, target=Path("/etc/headscale/config.yaml")):
    import fcntl

    if os.geteuid() != 0:
        raise ValueError("Reconfiguration requires root on the intended jumphost.")
    config = expected_configuration(json.loads(source.read_text(encoding="utf-8")))
    with open("/run/lock/team5-headscale.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        package = run("dpkg-query", "-W", "-f=${Status}|${Version}", "headscale", check=False)
        if package.returncode != 0 or package.stdout != f"install ok installed|{VERSION}":
            raise ValueError(f"Headscale {VERSION} must already be installed.")
        current = json.loads(target.read_text(encoding="utf-8"))
        if current == config:
            print("Configuration already matches; nothing changed.")
            return
        if without_split_dns(current) != without_split_dns(config):
            raise ValueError("Only the Split DNS resolver may change; review other differences separately.")
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        backup = target.with_name(f"{target.name}.{stamp}.bak")
        candidate = candidate_path(target)
        shutil.copy2(target, backup)
        candidate.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        shutil.chown(candidate, user="root", group="headscale")
        candidate.chmod(0o640)
        try:
            validate_as_service_user(candidate)
            os.replace(candidate, target)
            run("systemctl", "restart", "headscale.service")
            wait_until_ready()
        except Exception:
            candidate.unlink(missing_ok=True)
            shutil.copy2(backup, target)
            run("systemctl", "restart", "headscale.service", check=False)
            raise
        print(f"Split DNS updated and Headscale restarted. Previous configuration: {backup}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    render = commands.add_parser("render")
    render.add_argument("--server-url", required=True)
    render.add_argument("--base-domain", required=True)
    render.add_argument("--split-dns-resolver", required=True,
                        help="Tailnet IPv4 address of the jumphost running dnsmasq")
    render.add_argument("--output", type=Path, required=True)
    deploy = commands.add_parser("install")
    deploy.add_argument("--config", type=Path, required=True)
    change = commands.add_parser("reconfigure")
    change.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "render":
        config = configuration(args.server_url, args.base_domain, args.split_dns_resolver)
        # JSON is a YAML subset and avoids another configuration parser dependency.
        with args.output.open("x", encoding="utf-8") as output:
            json.dump(config, output, indent=2)
            output.write("\n")
        print(f"Configuration written to {args.output}; no server changes made.")
    elif args.command == "reconfigure":
        reconfigure(args.config.resolve(strict=True))
    else:
        install(args.config.resolve(strict=True))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, subprocess.CalledProcessError) as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)