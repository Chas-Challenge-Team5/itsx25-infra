"""Render pinned charts and validate our policy against their actual CRD, offline."""

from pathlib import Path
import subprocess

import jsonschema
import yaml

ROOT = Path(__file__).resolve().parents[1]


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
    assert [port["port"] for port in service["spec"]["ports"]] == [80]
    webhooks = [hook for doc in documents
                if doc["kind"] in ("ValidatingWebhookConfiguration", "MutatingWebhookConfiguration")
                for hook in doc["webhooks"] if hook["name"] == "policy.sigstore.dev"]
    assert webhooks, "Policy admission webhooks are missing"
    for hook in webhooks:
        assert hook["failurePolicy"] == "Fail"
        assert hook["namespaceSelector"]["matchExpressions"] == [
            {"key": "policy.sigstore.dev/include", "operator": "In", "values": ["true"]}]
    print(f"Validated {len(documents)} rendered resources, HTTP service, opt-in admission and policy CRD.")


if __name__ == "__main__":
    main()
