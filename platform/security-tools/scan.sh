#!/bin/sh
# Körs i alpine-containern (busybox sh). Hämtar SBOM-attesteringen för den
# körande company-website-imagen, verifierar den, scannar med Trivy och
# postar resultatet till Discord. Verktygen pinnas på version + sha256.
set -eu

TRIVY_VERSION=0.74.0
TRIVY_SHA256=2ae6fe3ee734b7fdf11335663e18c75ea12dccc76062f09f164a3b0f8be4371a
COSIGN_VERSION=2.6.4
COSIGN_SHA256=309779b0c4e409186b0a80daba99041fe2cf65a920ce645013901df6211895a9

# Secret skapad från fil kan ha avslutande radbrytning.
WEBHOOK_URL=$(printf %s "$WEBHOOK_URL" | tr -d ' \r\n')

WORK=/tmp/scan
mkdir -p "$WORK/bin"
export PATH="$WORK/bin:$PATH"
export TRIVY_CACHE_DIR="$WORK/trivy-cache"

post_embed() { # titel, beskrivning, färg
  jq -n --arg t "$1" --arg d "$2" --argjson c "$3" \
    '{embeds:[{title:$t, description:$d, color:$c, footer:{text:"k3s Trivy CronJob"}}]}' \
    | curl -sS --fail --max-time 30 -H 'Content-Type: application/json' -d @- "$WEBHOOK_URL" >/dev/null
}

# Tystnad får aldrig läsas som "allt är rent": ett avbrott ska också synas.
FAIL_REASON=
fail_alert() {
  rc=$?
  [ "$rc" -eq 0 ] && return
  post_embed "Supply chain-scan misslyckades" \
    "${FAIL_REASON:-Jobbet avslutades med felkod $rc.} Se loggen: kubectl logs -n security-tools job/<jobb>." 15158332 || true
}
trap fail_alert EXIT

fetch_checked() { # url, sha256, mål
  curl -sSfL --connect-timeout 15 --max-time 180 "$1" -o "$3"
  printf '%s  %s\n' "$2" "$3" | sha256sum -c -
}

apk add --no-cache curl jq >/dev/null
fetch_checked "https://github.com/aquasecurity/trivy/releases/download/v${TRIVY_VERSION}/trivy_${TRIVY_VERSION}_Linux-64bit.tar.gz" \
  "$TRIVY_SHA256" "$WORK/trivy.tgz"
tar -xzf "$WORK/trivy.tgz" -C "$WORK/bin" trivy
fetch_checked "https://github.com/sigstore/cosign/releases/download/v${COSIGN_VERSION}/cosign-linux-amd64" \
  "$COSIGN_SHA256" "$WORK/bin/cosign"
chmod +x "$WORK/bin/cosign"

SA=/var/run/secrets/kubernetes.io/serviceaccount
echo "[*] Letar efter poddar i '${TARGET_NAMESPACE}' med '${LABEL_SELECTOR}'"
PODS=$(curl -sSf --max-time 30 --cacert "$SA/ca.crt" -H "Authorization: Bearer $(cat "$SA/token")" \
  "https://kubernetes.default.svc/api/v1/namespaces/${TARGET_NAMESPACE}/pods?labelSelector=${LABEL_SELECTOR}")
IMAGE_ID=$(printf '%s' "$PODS" | jq -r '[.items[] | select(.status.phase=="Running")][0].status.containerStatuses[0].imageID // empty')
if [ -z "$IMAGE_ID" ]; then
  echo "[!] Ingen körande pod hittades" >&2
  FAIL_REASON="Hittade ingen körande pod med \`${LABEL_SELECTOR}\` i \`${TARGET_NAMESPACE}\`. Ingenting scannades."
  exit 1
fi
IMAGE=${IMAGE_ID#*://}
echo "[+] Scannar: $IMAGE"

# verify-attestation kontrollerar signaturen mot vår pipeline-identitet, inte bara att en SBOM finns.
cosign verify-attestation "$IMAGE" --type cyclonedx \
  --certificate-identity "$CERT_IDENTITY" --certificate-oidc-issuer "$CERT_OIDC_ISSUER" \
  | jq -rs '.[0].payload' | base64 -d | jq .predicate > "$WORK/sbom.json"

trivy sbom "$WORK/sbom.json" --format json --ignore-unfixed -o "$WORK/report.json"
COUNT=$(jq '[.Results[]?.Vulnerabilities[]? | select(.Severity=="HIGH" or .Severity=="CRITICAL")] | length' "$WORK/report.json")

if [ "${COUNT:-0}" -eq 0 ]; then
  post_embed "Supply chain-scan: inga fynd" \
    "Inga High/Critical-sårbarheter i körande image:
\`$IMAGE\`" 3066993
else
  trivy sbom "$WORK/sbom.json" --severity HIGH,CRITICAL --ignore-unfixed > "$WORK/report.txt"
  jq -n --arg d "Hittade **$COUNT** High/Critical-sårbarheter i körande image:
\`$IMAGE\`
Rapport bifogad." \
    '{embeds:[{title:"Supply chain-larm: sårbarheter hittade", description:$d, color:15158332, footer:{text:"k3s Trivy CronJob"}}]}' > "$WORK/payload.json"
  curl -sS --fail --max-time 60 -F "payload_json=<$WORK/payload.json" -F "file=@$WORK/report.txt" "$WEBHOOK_URL" >/dev/null
fi
echo "[+] Klart"
