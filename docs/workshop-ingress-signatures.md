# Workshop 3.5–4: DNS, ingress och signerade images

Infra förvaltar DNS, controllers och signaturpolicy. `company-website` förvaltar
Ingress, appens RBAC och build/sign/deploy. Merge av infra startar inte dessa
manuella bootstrapsteg. Inga nya GCP-brandväggsportar behövs för HTTP på primary.

Ingress-nginx används enligt användarens uttryckliga labbval den 24 september
2026 trots att projektet pensionerats. Helm 3.19.0, ingress-chart 4.15.1 och
policy-controller-chart 0.10.8 hämtas med låsta SHA-256-kontroller i scriptet.
Helm packas upp tillfälligt, vilket ersätter workshopens globala APT-installation.
Versionsuppgraderingar ska granskas separat.

## Före införande

Samordna ett tidsfönster utan parallella deployer. Kontrollera aktuell appimage,
pods, ledigt minne/CPU, fungerande IAP/SSH och klientåtkomst. Spara privat backup
av Headscale-konfiguration och en konsekvent backup av appens SQLite/PVC-data.
Inventera alla workloads/images i `default`, inklusive init-containrar. Förbered
den aktuella manifestversionen och image-referensen för återställning.

Lokalt kan controllers renderas utan Kubernetes-åtkomst:

```bash
bash scripts/k3s-platform.sh render > /tmp/team5-platform.yaml
```

## DNS på jumphosten

```bash
python3 headscale/setup.py render \
  --server-url https://team5.itsx25.chas-lab.dev \
  --base-domain team5.arpa --split-dns-resolver 100.64.0.2 \
  --company-website-ip 10.0.5.3 --output /tmp/headscale-workshop.json
sudo python3 headscale/setup.py reconfigure --config /tmp/headscale-workshop.json
```

Render vägrar skriva över en befintlig fil. Reconfigure bevarar backup och vägrar
orelaterade ändringar. Den nuvarande installeraren kräver JSON-konfiguration
(även när filen heter `.yaml`); en manuellt ändrad YAML-fil måste jämföras först.
Headscale 0.29.3 laddar bara om ACL vid SIGHUP, inte inline `extra_records`.
Därför behövs en kort tjänsteomstart, ingen VM-omstart. Rollback återlägger den
sparade konfigurationen vid fel. Bekräfta DNS från en Tailscale-klient med
`Resolve-DnsName company-website.team5.arpa` och fortsatt Spectre-åtkomst.
Källa: https://github.com/juanfont/headscale/blob/v0.29.3/hscontrol/app.go

## Byt port 80 till ingress på primary

1. Granska och applicera app-repots uppdaterade `k8s/github-permissions.yaml`
   manuellt som administratör. Kontrollera CI-tokenens giltighet. Ingen
   cluster-admin-rättighet ges till appens deploykonto.
2. Under tidsfönstret: deploya appversionen utan `hostPort: 80`, med Ingress och
   fungerande `ClusterIP` Service på 7000. Behåll PVC och `Recreate` för SQLite.
   HTTP-åtkomst kan vara nere tills controllern är redo.
3. Kör `sudo bash scripts/k3s-platform.sh install-ingress` från infra-repot på
   primary. Scriptet vägrar om någon pod fortfarande reserverar hostPort 80.
   K3s ServiceLB måste vara aktiverad. Controllerns Service exponerar endast HTTP;
   detta steg inför inte TLS för appen.
4. Kontrollera `sudo kubectl get pods,svc -n ingress-nginx` och
   `sudo kubectl get deploy,pods,svc,ingress -n default`.
5. Testa `curl -H 'Host: company-website.team5.arpa' http://127.0.0.1/` på primary
   och `http://company-website.team5.arpa` från klienterna. Kontrollera även
   inloggning, databevarande och befintlig NetworkPolicy.

Vid återställning: avinstallera ingress-releasen och invänta att ServiceLB-poddarna
släppt port 80, återlägg sedan tidigare appmanifest/image med hostPort. Radera
inte PVC:n. Använd signerad återställningsimage om signaturkravet redan är på.

## Signaturkravet införs sist

1. Appens pipeline ska först bygga, pusha, signera och verifiera en image samt
   deploya dess exakta digest. Verifiera även att init-containern använder samma
   signerade digest. Spara den som återställningsversion.
2. Installera med `sudo bash scripts/k3s-platform.sh install-policy` och invänta
   att samtliga controller/webhook-pods är redo i `cosign-system`.
3. Granska och applicera `sudo kubectl apply -f platform/image-policy.yaml`.
   Policyn kräver exakt apprepo, deploy.yml och refs/heads/main. Registry-sökvägen
   är gemener, medan GitHub-identiteten behåller organisationens verkliga stavning.
4. Skapa ett temporärt namespace `workshop-signature-check` och lägg på etiketten
   `policy.sigstore.dev/include=true`. Kör nedanstående prov där. Default ska
   fortfarande vara utan den etiketten.
5. När proven passerar och alla images i default är inventerade/signaturgodkända:
   `sudo kubectl label namespace default policy.sigstore.dev/include=true --overwrite`.
   Kontrollera en ny appdeploy och en ny podstart. Etiketten påverkar även andra
   workloads i default. Redan körande pods avlägsnas inte automatiskt.

Prov med verklig signerad digest (ersätt värdet):

```bash
sudo kubectl run test-signed --namespace=workshop-signature-check \
  --image=ghcr.io/chas-challenge-team5/company-website@sha256:REPLACE_WITH_SIGNED_DIGEST \
  --restart=Never --dry-run=server --command -- echo check
sudo kubectl run test-no-policy --namespace=workshop-signature-check \
  --image=alpine:latest --restart=Never --dry-run=server --command -- echo check
```

Det första ska accepteras och det andra nekas med `no matching policies`.
Prova dessutom en känd osignerad digest under **samma appimage-sökväg** och en
image signerad med annan identitet: båda ska nekas på signaturkontrollen.
Alpine-provet ensamt bevisar inte detta. DNS-/registry-/webhookfel räknas inte
som ett godkänt negativt signaturprov. Dry-run skapar inga testpods. Ta bort
testnamnrymden när proven är klara, efter att ha kontrollerat att den är tom.

Vid fel efter aktivering: administratören kan tillfälligt återgå till tidigare
läge med `sudo kubectl label namespace default policy.sigstore.dev/include-`.
Det tar bort signaturkravet för default tills felet rättats; notera avsteget.
Ge aldrig denna rättighet till CI-kontot.

Källor: https://docs.sigstore.dev/policy-controller/overview/ och
https://docs.sigstore.dev/policy-controller/installation/

## Klart när

- Namnet fungerar från samtliga klienter och appen nås genom ingress.
- Ny pipelinekörning signerar, verifierar och deployar samma digest.
- Rätt signatur accepteras; osignerad/fel signerad appimage nekas.
- Ny app-pod startar, befintlig data finns kvar och återställningen är dokumenterad.
