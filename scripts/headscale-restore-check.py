"""Test a mounted backup on a disposable Linux VM; never run on production.

No packages/services are installed. The verified binary runs in a network namespace
with only loopback. Snapshot files are read-only; all writes use a temporary copy.
Only aggregate results are printed. Logs and copied keys stay private until cleanup.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen


def run(*args, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, text=True, **kwargs)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def regular_tree(path):
    """Reject links and special files before copying secret material."""
    for item in [path, *path.rglob("*")]:
        if item.is_symlink() or not (item.is_file() or item.is_dir()):
            raise ValueError("Backup contains a link or special file; review it separately.")


def inventory(database):
    # Always inspect the writable COPY, so SQLite can process a saved WAL safely.
    with sqlite3.connect(database) as db:
        if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ValueError("SQLite integrity check failed.")
        result = {}
        for table, wanted in {
            "users": ("id", "name"),
            "nodes": ("id", "user_id", "machine_key", "node_key", "given_name", "ipv4", "ipv6", "approved_routes"),
        }.items():
            columns = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
            if not set(wanted).issubset(columns):
                raise ValueError("Unexpected database schema; use a version-specific restore plan.")
            result[table] = db.execute(f"SELECT {','.join(wanted)} FROM {table} ORDER BY id").fetchall()
        return result


def test_configuration(config, work):
    """Preserve identity/DNS/policy; relocate files and disable external DERP fetches."""
    config = json.loads(json.dumps(config))
    if (config["database"]["type"] != "sqlite" or
        config["database"]["sqlite"]["path"] != "/var/lib/headscale/db.sqlite" or
        config["noise"]["private_key_path"] != "/var/lib/headscale/noise_private.key" or
        config["policy"] != {"mode": "file", "path": "/etc/headscale/policy.hujson"}):
        raise ValueError("Unexpected backup paths or database/policy type.")
    config["database"]["sqlite"]["path"] = str(work / "data/db.sqlite")
    config["noise"]["private_key_path"] = str(work / "data/noise_private.key")
    config["policy"]["path"] = str(work / "etc/policy.hujson")
    config["unix_socket"] = str(work / "headscale.sock")
    config["listen_addr"] = "127.0.0.1:18080"
    config["metrics_listen_addr"] = "127.0.0.1:19090"
    config["grpc_listen_addr"] = "127.0.0.1:15043"
    config["disable_check_updates"] = True
    config["derp"] = {"server": {"enabled": False}, "urls": [],
                      "paths": [str(work / "derp.yaml")], "auto_update_enabled": False}
    return config


def offline_derp_map():
    # Local files use YAML with integer keys, unlike the HTTP JSON API.
    return """regions:
  999:
    regionid: 999
    regioncode: restore-test
    regionname: Isolated restore test
    nodes:
      - name: test
        regionid: 999
        hostname: derp.invalid
        ipv4: 127.0.0.1
"""


def inside_namespace(work, abort_after_start, original_netns):
    if not original_netns or os.readlink("/proc/self/ns/net") == original_netns:
        raise ValueError("Refusing to run without a separate network namespace.")
    if {link["ifname"] for link in json.loads(run("ip", "-json", "link", "show").stdout)} != {"lo"}:
        raise ValueError("The test namespace must contain only loopback.")
    run("ip", "link", "set", "lo", "up")
    # This process and the server run as nobody after setting up the namespace.
    os.setgroups([])
    os.setgid(65534)
    os.setuid(65534)
    for address in ("10.0.5.2", "100.64.0.2", "169.254.169.254", "1.1.1.1"):
        try:
            with socket.create_connection((address, 443), timeout=1):
                raise ValueError("Unexpected network reachability from isolated namespace.")
        except OSError:
            pass
    config = work / "test-config.json"
    binary = work / "headscale"
    run(str(binary), "--config", str(config), "configtest", timeout=30)
    with (work / "server.log").open("w") as log:
        server = subprocess.Popen([str(binary), "--config", str(config), "serve"], stdout=log, stderr=log)
        try:
            for _ in range(45):
                if server.poll() is not None:
                    raise ValueError("Restored Headscale exited before the health check passed.")
                try:
                    with urlopen("http://127.0.0.1:18080/health", timeout=1) as response:
                        if response.status == 200 and json.load(response).get("status") == "pass":
                            break
                except OSError:
                    pass
                time.sleep(1)
            else:
                raise ValueError("Restored Headscale health timed out.")
            if abort_after_start:
                raise RuntimeError("INJECTED_ABORT_AFTER_HEALTH")
            # Exercise the restored server's API, not only direct SQLite reads.
            for command in (("users", "list"), ("nodes", "list"), ("nodes", "list-routes")):
                output = run(str(binary), "--config", str(config), *command, "--output", "json", timeout=15)
                json.loads(output.stdout)
            print(json.dumps({"health": "pass", "api_reads": "pass", "network_isolation": "pass"}))
        finally:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)


def check_backup(args):
    if os.geteuid() != 0 or not socket.gethostname().startswith("team5-restore-129-"):
        raise ValueError("Run as root only on the dedicated team5-restore-129-* test VM.")
    root = args.snapshot_root.resolve()
    mount = json.loads(run("findmnt", "--json", "--target", str(root)).stdout)["filesystems"][0]
    options = set(mount["options"].split(","))
    if (Path(mount["target"]) != root or mount["fstype"] != "ext4" or "ro" not in options
            or not options.intersection({"noload", "norecovery"})):
        raise ValueError("The snapshot root must be a separate ro,noload ext4 mount.")
    source_binary = root / "usr/bin/headscale"
    if source_binary.is_symlink() or digest(source_binary) != args.binary_sha256:
        raise ValueError("Snapshot binary does not match the independently verified package binary.")
    for path in (root / "etc/headscale", root / "var/lib/headscale", root / "var/lib/tailscale"):
        regular_tree(path)
        if not path.is_dir() or not any(path.iterdir()):
            raise ValueError("Required backup directory is missing or empty.")
    os.umask(0o077)
    with tempfile.TemporaryDirectory(prefix="headscale-restore-129-", dir="/var/tmp") as directory:
        work = Path(directory)
        try:
            shutil.copytree(root / "etc/headscale", work / "etc")
            shutil.copytree(root / "var/lib/headscale", work / "data")
            shutil.copytree(root / "var/lib/tailscale", work / "tailscale")
            shutil.copy2(source_binary, work / "headscale")
            # Compare every copied regular file before any process can migrate/change it.
            for source, target in ((root / "etc/headscale", work / "etc"),
                                   (root / "var/lib/headscale", work / "data"),
                                   (root / "var/lib/tailscale", work / "tailscale")):
                if any(digest(path) != digest(target / path.relative_to(source))
                       for path in source.rglob("*") if path.is_file()):
                    raise ValueError("Copied backup differs from the mounted source.")
            config = json.loads((work / "etc/config.yaml").read_text())
            modified = test_configuration(config, work)
            (work / "test-config.json").write_text(json.dumps(modified))
            # A local static map avoids contacting production/public DERP servers.
            (work / "derp.yaml").write_text(offline_derp_map())
            before = inventory(work / "data/db.sqlite")
            key_before = digest(work / "data/noise_private.key")
            for path in [work, *work.rglob("*")]:
                os.chown(path, 65534, 65534)
                path.chmod(0o700 if path.is_dir() or path.name == "headscale" else 0o600)
            command = ["unshare", "--net", "--pid", "--fork", "--kill-child=KILL", "--mount-proc",
                       sys.executable, str(Path(__file__).resolve()), "--inside", str(work),
                       "--original-netns", os.readlink("/proc/self/ns/net")]
            if args.abort_after_start:
                command.append("--abort-after-start")
            result = subprocess.run(command, capture_output=True, text=True, timeout=120)
            if args.abort_after_start:
                if result.returncode == 0 or "INJECTED_ABORT_AFTER_HEALTH" not in result.stderr:
                    raise ValueError("Expected post-health abort was not observed.")
            elif result.returncode:
                raise ValueError("Isolated server test failed: " + result.stderr[-1200:])
            else:
                print(result.stdout.strip())
                if inventory(work / "data/db.sqlite") != before or digest(work / "data/noise_private.key") != key_before:
                    raise ValueError("Restored identities, routes or Noise key changed.")
            print(json.dumps({"backup_copy": "identical", "sqlite_integrity": "ok",
                              "users": len(before["users"]), "nodes": len(before["nodes"]),
                              "abort_test": args.abort_after_start, "source_read_only": True}))
        finally:
            # TemporaryDirectory deletes only its own newly created directory.
            # Children die with the PID namespace, including on timeout/interruption.
            pass
    if work.exists():
        raise ValueError("Temporary data cleanup failed.")
    print(json.dumps({"private_copy_cleanup": "pass"}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-root", type=Path)
    parser.add_argument("--binary-sha256")
    parser.add_argument("--abort-after-start", action="store_true")
    parser.add_argument("--inside", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--original-netns", help=argparse.SUPPRESS)
    arguments = parser.parse_args()
    if arguments.inside:
        inside_namespace(arguments.inside, arguments.abort_after_start, arguments.original_netns)
    elif arguments.snapshot_root and arguments.binary_sha256:
        check_backup(arguments)
    else:
        parser.error("Supply --snapshot-root and the independently verified --binary-sha256.")
