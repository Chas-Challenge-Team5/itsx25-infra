#!/usr/bin/env bash
# Manual bootstrap on primary. 'render' requires no cluster or credentials.
set -euo pipefail

repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
action=${1:-}
case "$action" in
  render|install-ingress|install-policy) ;;
  *) echo 'Usage: bash scripts/k3s-platform.sh render|install-ingress|install-policy' >&2; exit 2 ;;
esac

if [[ "$action" != render ]]; then
  export KUBECONFIG=${KUBECONFIG:-/etc/rancher/k3s/k3s.yaml}
  # Never bootstrap a different cluster by accidentally using the current context.
  node=$(kubectl get nodes -o jsonpath='{.items[*].metadata.name}')
  [[ "$node" == team5-primary ]] || { echo "Expected only team5-primary, found: $node" >&2; exit 1; }
  if [[ "$action" == install-ingress ]]; then
    # Exclude this release's namespace so a repeated install can upgrade its
    # own ServiceLB pods, while refusing conflicting app/other-controller pods.
    ports=$(kubectl get pods -A -o jsonpath='{range .items[?(@.metadata.namespace!="ingress-nginx")]}{range .spec.containers[*].ports[*]}{.hostPort}{"\n"}{end}{end}')
    if grep -qx 80 <<< "$ports"; then
      echo 'Port 80 is still reserved by a pod. Complete the coordinated hostPort cutover first.' >&2
      exit 1
    fi
  fi
fi

scratch=$(mktemp -d -t team5-platform-XXXXXXXX)
trap 'rm -rf -- "$scratch"' EXIT
fetch_checked() {
  local url=$1 checksum=$2 destination=$3
  curl --fail --silent --show-error --location --connect-timeout 15 --max-time 180 "$url" -o "$destination"
  printf '%s  %s\n' "$checksum" "$destination" | sha256sum --check --status
}

# The pinned CLI is extracted temporarily; no system-wide Helm installation.
[[ $(uname -m) == x86_64 ]] || { echo 'Linux amd64 is required.' >&2; exit 1; }
fetch_checked https://get.helm.sh/helm-v3.19.0-linux-amd64.tar.gz \
  a7f81ce08007091b86d8bd696eb4d86b8d0f2e1b9f6c714be62f82f96a594496 "$scratch/helm.tgz"
tar -xzf "$scratch/helm.tgz" -C "$scratch" linux-amd64/helm
helm_bin="$scratch/linux-amd64/helm"

install_chart() {
  local release=$1 namespace=$2 version=$3 url=$4 checksum=$5 values=$6
  local archive="$scratch/$release.tgz"
  fetch_checked "$url" "$checksum" "$archive"
  if [[ "$action" == render ]]; then
    "$helm_bin" template "$release" "$archive" --namespace "$namespace" --include-crds -f "$values"
  else
    "$helm_bin" upgrade --install "$release" "$archive" --namespace "$namespace" \
      --create-namespace --atomic --wait --timeout 5m -f "$values"
    echo "Installed $release chart $version. Verify resource usage and readiness."
  fi
}

if [[ "$action" == render || "$action" == install-ingress ]]; then
  install_chart ingress-nginx ingress-nginx 4.15.1 \
    https://github.com/kubernetes/ingress-nginx/releases/download/helm-chart-4.15.1/ingress-nginx-4.15.1.tgz \
    3eff0bd18151d6e6b1c441463410571443dda1ac78292cb189346628de784f0c \
    "$repo_root/platform/ingress-nginx-values.yaml"
fi
if [[ "$action" == render || "$action" == install-policy ]]; then
  install_chart policy-controller cosign-system 0.10.8 \
    https://github.com/sigstore/helm-charts/releases/download/policy-controller-0.10.8/policy-controller-0.10.8.tgz \
    71ecc9f1168dd7ad04b2f7456c2d492b5ca3e09a31883bb71f6369213ceeb814 \
    "$repo_root/platform/policy-controller-values.yaml"
fi
# Intentionally separate: review/apply image-policy.yaml and test a signed image
# before opting default into enforcement. Installation alone does not opt it in.
