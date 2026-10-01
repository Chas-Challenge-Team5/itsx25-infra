"""Kör platform/security-tools/scan.sh mot falska verktyg, utan nät eller kluster.

curl, apk, cosign och trivy ersätts med stubbar. jq, sha256sum, tar, base64 och
skalet är riktiga. Testet kör en kopia av skriptet där bara de pinnade
checksummorna är utbytta mot stubbarnas, så att checksumkontrollen faktiskt körs.
Varje test läser vad som postades till den falska webhooken.
"""

import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "platform/security-tools/scan.sh"
WEBHOOK = "https://discord.test/api/webhooks/123/hemlig-token-som-inte-far-synas"
RED, GREEN = 15158332, 3066993

CURL = r'''#!/usr/bin/env python3
import json, os, shutil, sys
args = sys.argv[1:]
url = next(a for a in reversed(args) if a.startswith("http"))
stub = os.environ["STUB_DIR"]
def record(entry):
    with open(os.path.join(stub, "calls.jsonl"), "a") as f:
        f.write(json.dumps(entry) + "\n")
if "/releases/download/" in url:
    out = args[args.index("-o") + 1]
    if url.endswith("cosign-linux-amd64"):
        shutil.copy(os.path.join(stub, "cosign"), out)
    elif os.environ.get("TAMPERED_DOWNLOAD"):
        open(out, "wb").write(b"inte den pinnade filen")
    else:
        shutil.copy(os.path.join(stub, "trivy.tgz"), out)
elif "/api/v1/namespaces/" in url:
    sys.stdout.write(open(os.path.join(stub, "pods.json")).read())
elif url == os.environ["WEBHOOK_URL_EXPECTED"]:
    if os.environ.get("WEBHOOK_FAIL"):
        sys.exit(22)
    if "-d" in args:
        payload = json.load(sys.stdin)
        attached = False
    else:
        form = [args[i + 1] for i, a in enumerate(args) if a == "-F"]
        payload_file = next(f for f in form if f.startswith("payload_json=<"))[len("payload_json=<"):]
        payload = json.load(open(payload_file))
        attached = any(f.startswith("file=@") for f in form)
    record({"webhook": payload, "attached": attached})
else:
    sys.exit(6)
'''

COSIGN = r'''#!/usr/bin/env python3
import base64, json, os, sys
with open(os.path.join(os.environ["STUB_DIR"], "calls.jsonl"), "a") as f:
    f.write(json.dumps({"cosign": sys.argv[1:]}) + "\n")
if os.environ.get("COSIGN_FAIL"):
    sys.exit(1)
predicate = {"predicate": {"bomFormat": "CycloneDX"}}
print(json.dumps({"payload": base64.b64encode(json.dumps(predicate).encode()).decode()}))
'''

# Följer riktiga Trivy: --ignore-unfixed tar bort fynd utan FixedVersion.
TRIVY = r'''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
report = json.load(open(os.path.join(os.environ["STUB_DIR"], "report.json")))
if "--ignore-unfixed" in args:
    for result in report.get("Results", []):
        result["Vulnerabilities"] = [v for v in result.get("Vulnerabilities", []) if v.get("FixedVersion")]
if "--format" in args:
    json.dump(report, open(args[args.index("-o") + 1], "w"))
else:
    print("textrapport")
'''


def vuln(severity, fixed=""):
    return {"VulnerabilityID": f"CVE-{severity}-{fixed or 'x'}", "Severity": severity, "FixedVersion": fixed}


def report(*vulns):
    return {"Results": [{"Target": "sbom", "Vulnerabilities": list(vulns)}]}


def pods(*pod_specs):
    """pod_specs: (phase, [imageID, ...])"""
    return {"items": [{"status": {"phase": phase, "containerStatuses": [{"imageID": i} for i in images]}}
                      for phase, images in pod_specs]}


IMAGE_A = "ghcr.io/chas-challenge-team5/company-website@sha256:" + "a" * 64
IMAGE_B = "ghcr.io/chas-challenge-team5/company-website@sha256:" + "b" * 64


def shells():
    found = [["sh"]]
    # Samma skal som alpine i klustret. Busybox kör sina egna sha256sum och tar
    # före PATH, därför är de riktiga i testet och inte stubbade.
    if shutil.which("busybox"):
        found.append(["busybox", "sh"])
    return found


def executable(path, body):
    path.write_text(body)
    path.chmod(0o755)


class ScanScriptTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="scan-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.stub, self.bin, self.sa = self.tmp / "stub", self.tmp / "bin", self.tmp / "sa"
        for directory in (self.stub, self.bin, self.sa):
            directory.mkdir()
        (self.sa / "token").write_text("token")
        (self.sa / "ca.crt").write_text("ca")
        executable(self.bin / "curl", CURL)
        executable(self.bin / "apk", "#!/bin/sh\nexit 0\n")
        executable(self.stub / "cosign", COSIGN)

        # Trivy levereras som tar.gz med binären "trivy" i roten, precis som releasen.
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
            data = TRIVY.encode()
            member = tarfile.TarInfo("trivy")
            member.size, member.mode = len(data), 0o755
            archive.addfile(member, io.BytesIO(data))
        (self.stub / "trivy.tgz").write_bytes(buffer.getvalue())

        script = SCRIPT.read_text()
        for name, artifact in (("TRIVY", "trivy.tgz"), ("COSIGN", "cosign")):
            digest = hashlib.sha256((self.stub / artifact).read_bytes()).hexdigest()
            script, count = re.subn(rf"^{name}_SHA256=[0-9a-f]{{64}}$", f"{name}_SHA256={digest}",
                                    script, flags=re.M)
            self.assertEqual(count, 1, f"{name}_SHA256 saknas i scan.sh")
        self.script = self.tmp / "scan.sh"
        self.script.write_text(script)

    def run_scan(self, shell, pod_list, vuln_report, **flags):
        (self.stub / "pods.json").write_text(json.dumps(pod_list))
        (self.stub / "report.json").write_text(json.dumps(vuln_report))
        calls = self.stub / "calls.jsonl"
        calls.unlink(missing_ok=True)
        work = self.tmp / "work"
        shutil.rmtree(work, ignore_errors=True)
        env = {
            "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
            "STUB_DIR": str(self.stub), "WORK": str(work), "SA_DIR": str(self.sa),
            "KUBE_API": "https://kube.test", "WEBHOOK_URL": WEBHOOK + "\n",
            "WEBHOOK_URL_EXPECTED": WEBHOOK,
            "TARGET_NAMESPACE": "default", "LABEL_SELECTOR": "app=company-website",
            "CERT_IDENTITY": "identity", "CERT_OIDC_ISSUER": "issuer",
            **{name: "1" for name, enabled in flags.items() if enabled},
        }
        result = subprocess.run([*shell, str(self.script)], env=env, capture_output=True, text=True, timeout=60)
        entries = [json.loads(line) for line in calls.read_text().splitlines()] if calls.exists() else []
        posts = [entry for entry in entries if "webhook" in entry]
        verified = [entry["cosign"][1] for entry in entries if "cosign" in entry]
        self.assertNotIn("hemlig-token", result.stdout + result.stderr, "Webhook-URL:en får aldrig skrivas ut")
        return result, posts, verified

    @staticmethod
    def embed(post):
        return post["webhook"]["embeds"][0]

    def test_unfixed_high_alerts_red(self):
        """Regression: HIGH/CRITICAL utan rättning gav tidigare grönt via --ignore-unfixed."""
        for shell in shells():
            with self.subTest(shell=shell):
                result, posts, _ = self.run_scan(shell, pods(("Running", [IMAGE_A])),
                                                 report(vuln("HIGH"), vuln("CRITICAL")))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(len(posts), 1)
                self.assertEqual(self.embed(posts[0])["color"], RED)
                self.assertIn("**2** High/Critical", self.embed(posts[0])["description"])
                self.assertIn("**2** saknar rättning", self.embed(posts[0])["description"])
                self.assertTrue(posts[0]["attached"])

    def test_fixed_and_unfixed_are_counted_separately(self):
        for shell in shells():
            with self.subTest(shell=shell):
                result, posts, _ = self.run_scan(shell, pods(("Running", [IMAGE_A])),
                                                 report(vuln("HIGH", "1.2"), vuln("HIGH"), vuln("MEDIUM")))
                self.assertEqual(result.returncode, 0, result.stderr)
                description = self.embed(posts[0])["description"]
                self.assertIn("**2** High/Critical", description)
                self.assertIn("**1** saknar rättning", description)

    def test_only_lower_severities_is_green(self):
        for shell in shells():
            with self.subTest(shell=shell):
                result, posts, _ = self.run_scan(shell, pods(("Running", [IMAGE_A])),
                                                 report(vuln("MEDIUM"), vuln("LOW", "2.0")))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual([self.embed(p)["color"] for p in posts], [GREEN])
                self.assertFalse(posts[0]["attached"])

    def test_failed_verification_alerts_and_fails_the_job(self):
        for shell in shells():
            with self.subTest(shell=shell):
                result, posts, _ = self.run_scan(shell, pods(("Running", [IMAGE_A])),
                                                 report(), COSIGN_FAIL=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual([self.embed(p)["color"] for p in posts], [RED])
                self.assertIn("misslyckades", self.embed(posts[0])["title"])
                self.assertIn("kunde inte verifieras", self.embed(posts[0])["description"])

    def test_tampered_download_is_rejected(self):
        for shell in shells():
            with self.subTest(shell=shell):
                result, posts, verified = self.run_scan(shell, pods(("Running", [IMAGE_A])),
                                                        report(), TAMPERED_DOWNLOAD=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(verified, [])
                self.assertEqual([self.embed(p)["color"] for p in posts], [RED])

    def test_no_running_pod_alerts_and_fails_the_job(self):
        for shell in shells():
            with self.subTest(shell=shell):
                result, posts, verified = self.run_scan(shell, pods(("Pending", [IMAGE_A])), report())
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(verified, [])
                self.assertIn("ingen körande pod", self.embed(posts[0])["description"].lower())

    def test_unreachable_discord_fails_the_job(self):
        """Annars syns ett återkallat webhook bara som tystnad."""
        for shell in shells():
            with self.subTest(shell=shell):
                result, posts, _ = self.run_scan(shell, pods(("Running", [IMAGE_A])),
                                                 report(vuln("HIGH")), WEBHOOK_FAIL=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(posts, [])

    def test_every_running_image_is_verified_once(self):
        for shell in shells():
            with self.subTest(shell=shell):
                result, posts, verified = self.run_scan(
                    shell,
                    pods(("Running", [IMAGE_A, "docker-pullable://" + IMAGE_B]),
                         ("Running", [IMAGE_A]), ("Pending", ["ghcr.io/other@sha256:" + "c" * 64])),
                    report())
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(sorted(verified), sorted([IMAGE_A, IMAGE_B]))
                self.assertEqual(len(posts), 2)


if __name__ == "__main__":
    unittest.main()
