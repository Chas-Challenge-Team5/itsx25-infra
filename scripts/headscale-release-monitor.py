"""Propose a reviewed Headscale upgrade; never install or execute release assets.

Default mode is read-only. --output-dir writes a local preview; --publish is
restricted to the main-branch GitHub Actions workflow in this repository.
"""

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.request import urlopen

REPOSITORY = "Chas-Challenge-Team5/itsx25-infra"
UPSTREAM = "juanfont/headscale"
SOURCE_PATH = "headscale/setup.py"
ROOT = Path(__file__).resolve().parents[1]
VERSION_PATTERN = r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"


def version(value):
    if not re.fullmatch(VERSION_PATTERN, value):
        raise ValueError(f"Invalid stable version: {value!r}")
    return tuple(map(int, value.split(".")))


def read_pins(source):
    versions = re.findall(r'^VERSION = "([^"]+)"$', source, re.MULTILINE)
    hashes = re.findall(r'^PACKAGE_SHA256 = "([0-9a-f]{64})"$', source, re.MULTILINE)
    if len(versions) != 1 or len(hashes) != 1:
        raise ValueError("Expected exactly one VERSION and PACKAGE_SHA256 assignment.")
    version(versions[0])
    return versions[0], hashes[0]


def choose_release(current, releases):
    """Prefer remaining patches, then the next minor. Never skip a minor."""
    installed = version(current)
    stable = {}
    for release in releases:
        tag = release.get("tag_name", "")
        if release.get("draft") or release.get("prerelease"):
            continue
        if re.fullmatch("v" + VERSION_PATTERN, tag):
            stable[version(tag[1:])] = release
    newer = [item for item in stable if item > installed]
    if not newer:
        return None
    patches = [item for item in newer if item[:2] == installed[:2]]
    next_minor = [item for item in newer if item[:2] == (installed[0], installed[1] + 1)]
    candidates = patches or next_minor
    if not candidates:
        raise ValueError("New releases exist, but the next minor is missing or a major upgrade needs review.")
    return stable[max(candidates)]


def github(endpoint, method="GET", payload=None, paginate=False):
    command = ["gh", "api", "--hostname", "github.com", "--method", method, endpoint]
    if paginate:
        command += ["--paginate", "--slurp"]
    if payload is not None:
        command += ["--input", "-"]
    result = subprocess.run(
        command, input=json.dumps(payload) if payload is not None else None,
        text=True, encoding="utf-8", capture_output=True, check=True, timeout=120,
    )
    data = json.loads(result.stdout)
    return [item for page in data for item in page] if paginate else data


def read_url(url, limit):
    with urlopen(url, timeout=60) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Release asset exceeds the allowed size.")
    return data


def verified_checksum(release):
    target = release["tag_name"][1:]
    version(target)
    filename = f"headscale_{target}_linux_amd64.deb"
    names = [asset["name"] for asset in release["assets"]]
    if names.count(filename) != 1 or names.count("checksums.txt") != 1:
        raise ValueError("Release must contain exactly one amd64 Debian package and checksums.txt.")
    # Construct upstream URLs; do not follow URLs supplied in release text.
    base = f"https://github.com/{UPSTREAM}/releases/download/v{target}/"
    checksums = read_url(base + "checksums.txt", 1024 * 1024).decode("utf-8")
    matches = re.findall(
        rf"^([0-9a-f]{{64}}) [ *]{re.escape(filename)}\r?$", checksums, re.MULTILINE,
    )
    if len(matches) != 1:
        raise ValueError("Missing, ambiguous or invalid package checksum.")
    package = read_url(base + filename, 128 * 1024 * 1024)
    if hashlib.sha256(package).hexdigest() != matches[0]:
        raise ValueError("Downloaded package does not match the published checksum.")
    return matches[0]


def render_source(source, target, checksum):
    read_pins(source)
    version(target)
    if not re.fullmatch(r"[0-9a-f]{64}", checksum):
        raise ValueError("Invalid package checksum.")
    result = re.sub(r'^VERSION = "[^"]+"$', f'VERSION = "{target}"', source, flags=re.MULTILINE)
    return re.sub(
        r'^PACKAGE_SHA256 = "[0-9a-f]{64}"$', f'PACKAGE_SHA256 = "{checksum}"',
        result, flags=re.MULTILINE,
    )


def pr_body(current, target, checksum):
    return f"""## Headscale release update

Proposes **{current} → {target}**. The linux_amd64 Debian package was downloaded
and its SHA-256 checked against the upstream release's checksums.txt:
`{checksum}`.

[Release notes](https://github.com/{UPSTREAM}/releases/tag/v{target})

Only VERSION and PACKAGE_SHA256 in headscale/setup.py are changed. Review
configuration compatibility and test changes required by this release.
Merge does **not** upgrade the running jumphost. The installer refuses to
upgrade an existing version; reconfigure also requires the pinned version.
Until the planned upgrade, use the matching old revision for the running server.

- [ ] Run and review CI, including the isolated test with the new binary.
- [ ] Review release notes, client compatibility and every required migration step.
- [ ] Test upgrade and restore with a private copy of the existing data.
- [ ] Verify a fresh backup and arrange a maintenance window before installation.
- [ ] Verify health, nodes, routes, DNS and client access after the manual upgrade.

See docs/headscale-updates.md and #89. No automatic merge or installation.
"""


def publish(source, updated, target, body):
    # Keep a local invocation, fork or dispatch from another branch read-only.
    if not (
        os.environ.get("GITHUB_ACTIONS") == "true"
        and os.environ.get("GITHUB_REPOSITORY") == REPOSITORY
        and os.environ.get("GITHUB_REF") == "refs/heads/main"
        and os.environ.get("GITHUB_EVENT_NAME") in {"schedule", "workflow_dispatch"}
    ):
        raise ValueError("Publication is allowed only from this repository's main workflow.")
    prefix = f"repos/{REPOSITORY}"
    branch = f"automation/headscale-v{target}"
    open_prs = github(f"{prefix}/pulls?state=open&base=main&per_page=100", paginate=True)
    for pr in open_prs:
        head = pr["head"]
        if (head.get("repo") or {}).get("full_name") == REPOSITORY and head["ref"].startswith("automation/headscale-v"):
            return f"Existing update awaits review: {pr['html_url']}"
    previous = github(f"{prefix}/pulls?state=all&head=Chas-Challenge-Team5:{branch}&per_page=100", paginate=True)
    if previous:
        return f"This version already has a PR; reopen it if needed: {previous[0]['html_url']}"

    main = github(f"{prefix}/git/ref/heads/main")["object"]["sha"]
    original = github(f"{prefix}/contents/{SOURCE_PATH}?ref={main}")
    if base64.b64decode(original["content"]).decode("utf-8").replace("\r\n", "\n") != source:
        raise ValueError("main changed since checkout. Retry from current main.")
    refs = github(f"{prefix}/git/matching-refs/heads/{branch}", paginate=True)
    if not any(ref["ref"] == f"refs/heads/{branch}" for ref in refs):
        github(f"{prefix}/git/refs", "POST", {"ref": f"refs/heads/{branch}", "sha": main})
    else:
        comparison = github(f"{prefix}/compare/{main}...{branch}")
        if any(item["filename"] != SOURCE_PATH for item in comparison.get("files", [])):
            raise ValueError("Update branch includes unrelated changes; review it manually.")
    existing = github(f"{prefix}/contents/{SOURCE_PATH}?ref={branch}")
    content = base64.b64decode(existing["content"]).decode("utf-8").replace("\r\n", "\n")
    # Resume an interrupted publication without force-pushing or overwriting edits.
    if content == source:
        github(f"{prefix}/contents/{SOURCE_PATH}", "PUT", {
            "message": f"Update Headscale to {target}", "branch": branch,
            "sha": existing["sha"], "content": base64.b64encode(updated.encode()).decode(),
        })
    elif content != updated:
        raise ValueError("Update branch contains different edits; review it manually.")
    pr = github(f"{prefix}/pulls", "POST", {
        "title": f"Update Headscale to {target}", "head": branch,
        "base": "main", "body": body,
    })
    return f"Opened {pr['html_url']}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--output-dir", type=Path, help="Write a preview outside the tracked source")
    args = parser.parse_args()
    source = (ROOT / SOURCE_PATH).read_text(encoding="utf-8")
    current, _ = read_pins(source)
    releases = github(f"repos/{UPSTREAM}/releases?per_page=100", paginate=True)
    release = choose_release(current, releases)
    if release is None:
        print(f"No newer stable Headscale release than {current}.")
        return
    target = release["tag_name"][1:]
    checksum = verified_checksum(release)
    updated = render_source(source, target, checksum)
    body = pr_body(current, target, checksum)
    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=False)
        (args.output_dir / "setup.py").write_text(updated, encoding="utf-8")
        (args.output_dir / "pr.md").write_text(body, encoding="utf-8")
    print(f"Verified update: {current} -> {target}; SHA-256 {checksum}")
    if args.publish:
        print(publish(source, updated, target, body))
    else:
        print("Preview only. No branch, PR, source pin or running service changed.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(f"Headscale release monitor failed: {error}", file=sys.stderr)
        if isinstance(error, subprocess.CalledProcessError) and error.stderr:
            print(error.stderr.strip(), file=sys.stderr)
        sys.exit(1)
