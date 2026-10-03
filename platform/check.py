"""Render pinned charts and validate our policy against their actual CRD, offline."""

from pathlib import Path
import re
import subprocess

import jsonschema
import yaml

ROOT = Path(__file__).resolve().parents[1]


def check_security_scanner():
    """Scannern ska vara namespace-begränsad, pinnad och utan webhook i git."""
    directory = ROOT / "platform/security-tools"
    docs = {name: list(yaml.safe_load_all((directory / name).read_text()))
            for name in ("namespace.yaml", "rbac.yaml", "cronjob.yaml")}
    namespace = docs["namespace.yaml"][0]
    assert namespace["metadata"]["name"] == "security-tools"
    assert "policy.sigstore.dev/include" not in namespace["metadata"].get("labels", {})
    kinds = {doc["kind"] for doc in docs["rbac.yaml"]}
    assert kinds == {"ServiceAccount", "Role", "RoleBinding"}, "Ingen ClusterRole/ClusterRoleBinding"
    role = next(doc for doc in docs["rbac.yaml"] if doc["kind"] == "Role")
    assert role["metadata"]["namespace"] == "default"
    assert role["rules"] == [{"apiGroups": [""], "resources": ["pods"], "verbs": ["get", "list"]}]
    cronjob = docs["cronjob.yaml"][0]
    pod = cronjob["spec"]["jobTemplate"]["spec"]["template"]["spec"]
    container = pod["containers"][0]
    assert re.search(r"@sha256:[0-9a-f]{64}$", container["image"]), "Basimagen måste pinnas på digest"
    env = {item["name"]: item for item in container["env"]}
    secret = env["WEBHOOK_URL"]["valueFrom"]["secretKeyRef"]
    assert secret == {"name": "sbom-vulnerability-scanner-secrets", "key": "discord-webhook-url"}
    assert env["TARGET_NAMESPACE"]["value"] == "default", "Role gäller bara default"
    assert pod["serviceAccountName"] == "sbom-scanner-sa"
    assert cronjob["spec"]["concurrencyPolicy"] == "Forbid"
    assert pod["volumes"][0]["configMap"]["name"] == "scanner-script"
    script = (directory / "scan.sh").read_text()
    for tool in ("TRIVY", "COSIGN"):
        assert re.search(rf"^{tool}_VERSION=\d+\.\d+\.\d+$", script, re.M), f"{tool} måste pinnas"
        assert re.search(rf"^{tool}_SHA256=[0-9a-f]{{64}}$", script, re.M), f"{tool} saknar sha256"
    assert "install.sh | sh" not in script, "Ingen overifierad installation"
    assert "verify-attestation" in script and "download attestation" not in script
    assert not re.search(r"^\s*trivy .*--ignore-unfixed", script, re.M), "Fynd utan rättning ska också larma"
    assert not re.search(r"^\s*set\s+-[a-z]*x", script, re.M), "set -x skulle skriva ut webhook-URL:en"
    security = container["securityContext"]
    assert security["allowPrivilegeEscalation"] is False
    assert security["capabilities"]["drop"] == ["ALL"]
    assert pod["nodeSelector"] == {"kubernetes.io/arch": "amd64"}, "Checksummorna gäller amd64"
    job = cronjob["spec"]["jobTemplate"]["spec"]
    assert job["activeDeadlineSeconds"] and job["backoffLimit"] is not None and job["ttlSecondsAfterFinished"]
    # Hela repot, inte bara scannerns katalog. Exemplet i docs (ID/TOKEN) matchar inte.
    webhook = re.compile(r"discord(?:app)?\.com/api/webhooks/\d+/[\w-]{20,}")
    tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, check=True,
                             capture_output=True, text=True).stdout.splitlines()
    for name in filter(None, tracked):
        path = ROOT / name
        if path.is_file():
            assert not webhook.search(path.read_text(errors="ignore")), f"Webhook i git: {name}"
    subprocess.run(["sh", "-n", str(directory / "scan.sh")], check=True)


def main():
    rendered = subprocess.run(
        ["bash", str(ROOT / "scripts/k3s-platform.sh"), "render"],
        check=True, capture_output=True, text=True,
    ).stdout
    documents = [doc for doc in yaml.safe_load_all(rendered) if doc]
    crd = next(doc for doc in documents if doc["kind"] == "CustomResourceDefinition"
               and doc["metadata"]["name"] == "clusterimagepolicies.policy.sigstore.dev")
    schema = next(v["schema"]["openAPIV3Schema"] for v in crd["spec"]["versions"]
                  if v["name"] == "v1beta1")
    policy = yaml.safe_load((ROOT / "platform/image-policy.yaml").read_text())
    jsonschema.validate(policy, schema)
    service = next(doc for doc in documents if doc["kind"] == "Service"
                   and doc["metadata"]["name"] == "ingress-nginx-controller")
    assert service["spec"]["type"] == "LoadBalancer"
    assert [port["port"] for port in service["spec"]["ports"]] == [80, 443]
    for resource in yaml.safe_load_all((ROOT / "platform/company-tls.yaml").read_text()):
        definition = next(doc for doc in documents if doc["kind"] == "CustomResourceDefinition"
                          and doc["spec"]["names"]["kind"] == resource["kind"]
                          and doc["spec"]["group"] == "cert-manager.io")
        tls_schema = next(v["schema"]["openAPIV3Schema"] for v in definition["spec"]["versions"]
                          if v["name"] == "v1")
        jsonschema.validate(resource, tls_schema)
    webhooks = [hook for doc in documents
                if doc["kind"] in ("ValidatingWebhookConfiguration", "MutatingWebhookConfiguration")
                for hook in doc["webhooks"] if hook["name"] == "policy.sigstore.dev"]
    assert webhooks, "Policy admission webhooks are missing"
    for hook in webhooks:
        assert hook["failurePolicy"] == "Fail"
        assert hook["namespaceSelector"]["matchExpressions"] == [
            {"key": "policy.sigstore.dev/include", "operator": "In", "values": ["true"]}]
    check_security_scanner()
    print(f"Validated {len(documents)} rendered resources, HTTP/HTTPS service, TLS resources, security scanner and policy CRD.")


if __name__ == "__main__":
    main()
