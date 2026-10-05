#!/bin/sh
# Körs i alpine-containern (busybox sh). Hämtar SBOM-attesteringen för varje
# image som körs i company-website-poddarna, verifierar den, scannar med Trivy
# och postar resultatet till Discord. Verktygen pinnas på version + sha256.
# Webhook-URL:en skrivs aldrig ut: ingen set -x och inga ekade curl-kommandon.
set -eu

TRIVY_VERSION=0.74.0
TRIVY_SHA256=2ae6fe3ee734b7fdf11335663e18c75ea12dccc76062f09f164a3b0f8be4371a
COSIGN_VERSION=2.6.4
COSIGN_SHA256=309779b0c4e409186b0a80daba99041fe2cf65a920ce645013901df6211895a9

# Secret skapad från fil kan ha avslutande radbrytning.
WEBHOOK_URL=$(printf %s "$WEBHOOK_URL" | tr -d ' \r\n')

# Standardvärdena gäller i klustret. Testerna pekar om dem till en tillfällig katalog.
WORK=${WORK:-/tmp/scan}
SA_DIR=${SA_DIR:-/var/run/secrets/kubernetes.io/serviceaccount}
KUBE_API=${KUBE_API:-https://kubernetes.default.svc}
mkdir -p "$WORK/bin"
export PATH="$WORK/bin:$PATH"
export TRIVY_CACHE_DIR="$WORK/trivy-cache"

post_embed() { # titel, beskrivning, färg
  jq -n --arg t "$1" --arg d "$2" --argjson c "$3" \
    '{embeds:[{title:$t, description:$d, color:$c, footer:{text:"k3s Trivy CronJob"}}]}' \
    | curl -sS --fail --max-time 30 -H 'Content-Type: application/json' -d @- "$WEBHOOK_URL" >/dev/null
}

# Tystnad får aldrig läsas som "allt är rent": ett avbrott ska också synas.
# Når inte Discord avslutas jobbet ändå med felkod och syns som Failed i kubectl.
FAIL_REASON=
fail_alert() {
  rc=$?
  [ "$rc" -eq 0 ] && return
  post_embed "Supply chain-scan misslyckades" \
    "${FAIL_REASON:-Jobbet avslutades med felkod $rc.} Se loggen: kubectl logs -n security-tools job/<jobb>." 15158332 || true
  exit "$rc"
}
trap fail_alert EXIT

fetch_checked() { # url, sha256, mål
  curl -sSfL --connect-timeout 15 --max-time 180 "$1" -o "$3"
  printf '%s  %s\n' "$2" "$3" | sha256sum -c -
}

# Checksummorna gäller amd64-binärerna. CronJob:en har en nodeSelector med samma krav.
if [ "$(uname -m)" != x86_64 ]; then
  FAIL_REASON="Scannern stöder bara amd64, noden är $(uname -m)."
  exit 1
fi

apk add --no-cache curl jq >/dev/null
fetch_checked "https://github.com/aquasecurity/trivy/releases/download/v${TRIVY_VERSION}/trivy_${TRIVY_VERSION}_Linux-64bit.tar.gz" \
  "$TRIVY_SHA256" "$WORK/trivy.tgz"
tar -xzf "$WORK/trivy.tgz" -C "$WORK/bin" trivy
fetch_checked "https://github.com/sigstore/cosign/releases/download/v${COSIGN_VERSION}/cosign-linux-amd64" \
  "$COSIGN_SHA256" "$WORK/bin/cosign"
chmod +x "$WORK/bin/cosign"

echo "[*] Letar efter poddar i '${TARGET_NAMESPACE}' med '${LABEL_SELECTOR}'"
curl -sSf --max-time 30 --cacert "$SA_DIR/ca.crt" -H "Authorization: Bearer $(cat "$SA_DIR/token")" \
  "${KUBE_API}/api/v1/namespaces/${TARGET_NAMESPACE}/pods?labelSelector=${LABEL_SELECTOR}" > "$WORK/pods.json"
# Alla containrar i alla körande poddar, unika digests. Under en utrullning kan två images köra samtidigt.
jq -r '[.items[] | select(.status.phase=="Running") | .status.containerStatuses[]?.imageID
        | select(. != null and . != "")] | unique | .[]' "$WORK/pods.json" > "$WORK/images.txt"
if [ ! -s "$WORK/images.txt" ]; then
  echo "[!] Ingen körande pod hittades" >&2
  FAIL_REASON="Hittade ingen körande pod med \`${LABEL_SELECTOR}\` i \`${TARGET_NAMESPACE}\`. Ingenting scannades."
  exit 1
fi

HIGH_CRITICAL='[.Results[]?.Vulnerabilities[]? | select(.Severity=="HIGH" or .Severity=="CRITICAL")]'

scan_image() { # imageID (repo@sha256:...), arbetskatalog
  image=${1#*://}
  dir=$2
  mkdir -p "$dir"
  echo "[+] Scannar: $image"

  # verify-attestation kontrollerar signaturen mot vår pipeline-identitet, inte bara att en SBOM finns.
  # Egen rad först: busybox sh saknar pipefail, så ett misslyckat cosign hade annars kunnat passera.
  FAIL_REASON="SBOM-attesteringen för \`$image\` kunde inte verifieras mot pipelinens identitet."
  cosign verify-attestation "$image" --type cyclonedx \
    --certificate-identity "$CERT_IDENTITY" --certificate-oidc-issuer "$CERT_OIDC_ISSUER" \
    > "$dir/attestation.jsonl"
  jq -rs '.[0].payload' < "$dir/attestation.jsonl" | base64 -d | jq .predicate > "$dir/sbom.json"
  FAIL_REASON=

  # Inget --ignore-unfixed: en HIGH/CRITICAL utan rättning ska också larma, vi behöver känna till den.
  # --no-progress: förloppsindikatorn för databasnedladdningen fyller annars jobbloggen.
  # --skip-version-check: versionen är pinnad ovan och uppdateras enligt docs, inte på Trivys notis.
  trivy sbom "$dir/sbom.json" --no-progress --skip-version-check --format json -o "$dir/report.json"
  total=$(jq "$HIGH_CRITICAL | length" "$dir/report.json")
  unfixed=$(jq "$HIGH_CRITICAL | map(select((.FixedVersion // \"\") == \"\")) | length" "$dir/report.json")

  if [ "$total" -eq 0 ]; then
    post_embed "Supply chain-scan: inga fynd" \
      "Inga High/Critical-sårbarheter i körande image:
\`$image\`" 3066993
    return
  fi

  trivy sbom "$dir/sbom.json" --no-progress --skip-version-check --severity HIGH,CRITICAL > "$dir/report.txt"
  jq -n --arg d "Hittade **$total** High/Critical-sårbarheter i körande image, varav **$unfixed** saknar rättning ännu:
\`$image\`
Rapport bifogad." \
    '{embeds:[{title:"Supply chain-larm: sårbarheter hittade", description:$d, color:15158332, footer:{text:"k3s Trivy CronJob"}}]}' > "$dir/payload.json"
  curl -sS --fail --max-time 60 -F "payload_json=<$dir/payload.json" -F "file=@$dir/report.txt" "$WEBHOOK_URL" >/dev/null
}

n=0
while read -r image_id; do
  n=$((n + 1))
  scan_image "$image_id" "$WORK/image-$n" < /dev/null
done < "$WORK/images.txt"
echo "[+] Klart, $n image(s) scannade"
