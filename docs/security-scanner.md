# Supply chain-scanner (Trivy + cosign)

Ett CronJob i namespace `security-tools` scannar dagligen kl. 12:00
(Europe/Stockholm) de *körande* company-website-imagerna. Jobbet frågar
k8s-API:t efter poddarna med `app=company-website` och tar image-digesten för
varje container i varje körande podd (unika, så en utrullning med två images
scannar båda). För varje digest verifieras SBOM-attesteringen med
`cosign verify-attestation`, Trivy scannar SBOM:en och resultatet postas till en
Discord-webhook, en post per image. Inget fynd ger en grön post, High/Critical
ger en röd post med rapporten bifogad, och ett avbrott (ingen pod,
verifieringen misslyckas, manipulerad nedladdning, Trivy kraschar) ger en röd
felpost. Tystnad ska aldrig betyda "rent".

Fynd **utan** rättning räknas också. Trivy körs utan `--ignore-unfixed`, så en
HIGH/CRITICAL som ännu saknar uppdatering ger rött larm i stället för grönt.
Posten anger hur många av fynden som saknar rättning.

Manifesten ligger i `platform/security-tools/` och installeras manuellt på
primary, precis som cert-manager. Merge av en PR ändrar alltså inte det som körs.

## Säkerhetsval

- **Namespace-begränsad RBAC.** `Role`/`RoleBinding` i `default`, bara `get`/`list`
  på poddar. Ingen `ClusterRole`. Ändrar du `TARGET_NAMESPACE` måste rollen flyttas med.
- **Utanför signaturpolicyn.** `security-tools` saknar etiketten
  `policy.sigstore.dev/include`, eftersom `alpine` inte är signerad. Namespacet
  har Pod Security `baseline`.
- **Webhooken ligger aldrig i git.** Den skapas från en lokal fil som `.gitignore` redan
  täcker (`/security-scanner-webhook.txt`). `platform/check.py` failar om en
  webhook-URL hittas i någon versionshanterad fil i repot. `scan.sh` kör aldrig
  `set -x` och skriver aldrig ut URL:en eller curl-kommandot, vilket testerna kontrollerar.
- **Pinnat.** Basimagen är `alpine:3.24@sha256:…`. Trivy och cosign hämtas från
  GitHub Releases med version och sha256 i `scan.sh`, kontrollerade med `sha256sum -c`
  före körning. Cosign är samma version (2.6.4) som company-websites deploy-workflow signerar med.
- **Verifierad SBOM.** `verify-attestation` kontrollerar signaturen mot samma
  identitet som `ClusterImagePolicy` (`deploy.yml@refs/heads/main`). En SBOM som
  någon annan lagt upp scannas inte.
- **Ingen fallback-image.** Kursmaterialet faller tillbaka på `:latest` när ingen pod
  hittas. Det scannar något som inte körs, så här larmar jobbet i stället.

## Kända begränsningar

- `apk add curl jq` hämtar paket från Alpines signerade repo vid varje körning.
  Paketversionerna är inte pinnade, bara basimagens digest. Det kräver också att
  containern kör som root, så `runAsNonRoot` och `readOnlyRootFilesystem` går inte.
  Containern har ändå `allowPrivilegeEscalation: false` och alla Linux-capabilities
  borttagna. En egen image med verktygen inbakade skulle lösa båda, men kräver en
  egen bygg- och signeringskedja.
- Checksummorna gäller amd64-binärerna. CronJob:en har `nodeSelector`
  `kubernetes.io/arch: amd64` och skriptet avbryter på annan arkitektur.
- Bara containrar i `status.containerStatuses` scannas, inte init-containrar.
- Felposten kommer från `scan.sh` självt. Fel som inträffar innan skriptet kör, eller
  som dödar det utifrån, ger ingen Discord-post och syns bara i `kubectl get jobs` och
  `kubectl get pods -n security-tools`:
  - `Pending` om ingen amd64-nod finns (`nodeSelector`).
  - `ImagePullBackOff` om alpine-imagen inte går att hämta.
  - Deadline-kill efter 900 s (`activeDeadlineSeconds`). Skalet kör som PID 1 och
    ignorerar SIGTERM, så EXIT-trappen hinner inte posta innan SIGKILL.
  - `OOMKilled` om minnesgränsen överskrids.

  Att fånga dem kräver något som bevakar jobbet utifrån, till exempel ett larm på
  misslyckade jobb. Det finns inte här.

## Nätverksberoenden vid körning

Jobbet behöver utgående trafik till:

- `dl-cdn.alpinelinux.org` (apk), `github.com` och dess release-CDN (Trivy, cosign).
- Sigstore: TUF-roten, Fulcio och Rekor (`*.sigstore.dev`) för `verify-attestation`.
- Trivys sårbarhetsdatabas på `ghcr.io` / `mirror.gcr.io`. Databasen omfattas inte av
  sha256-pinningen, den uppdateras löpande. Rate limiting därifrån är en vanlig orsak
  till röda felposter. Kör om jobbet senare innan du felsöker vidare.
- `discord.com` för posten.

Det finns ingen NetworkPolicy i `security-tools` (kontrollerat 2026-09-30, inga
policies i klustret alls). Läggs default-deny för utgående trafik in senare måste
destinationerna ovan tillåtas.

## Installera

1. Skapa webhooken i Discord (Serverinställningar, Integrationer, Webhooks) och spara
   URL:en i en lokal fil i repots rot. Filen är ignorerad av git:

   ```bash
   printf '%s' 'https://discord.com/api/webhooks/ID/TOKEN' > security-scanner-webhook.txt
   chmod 600 security-scanner-webhook.txt
   ```

2. På primary, i en klon av repot:

   ```bash
   DISCORD_WEBHOOK_FILE=security-scanner-webhook.txt bash scripts/k3s-platform.sh install-security-scanner
   ```

   Åtgärden applicerar namespace, skapar secreten `sbom-vulnerability-scanner-secrets`
   (nyckel `discord-webhook-url`), lägger in `scan.sh` som ConfigMap `scanner-script`
   och applicerar RBAC och CronJob. Utan `DISCORD_WEBHOOK_FILE` återanvänds en befintlig secret.

3. Radera den lokala webhook-filen när secreten är skapad, eller förvara den utanför repot.

## Manuell testkörning

```bash
sudo kubectl create job --from=cronjob/sbom-vulnerability-scanner manual-test-run -n security-tools
sudo kubectl get pods -n security-tools -w
sudo kubectl logs job/manual-test-run -n security-tools
sudo kubectl delete job manual-test-run -n security-tools
```

Förväntat: en post per körande image i Discord-kanalen och jobbet i status `Completed`.
Radera testjobbet efteråt. Gör du inte det tas det bort automatiskt efter sju dagar
(`ttlSecondsAfterFinished`). Första körningen laddar Trivy-databasen och tar några minuter.

## Byta eller rotera webhooken

Skapa en ny webhook i Discord, ersätt innehållet i den lokala filen och kör
installationsåtgärden igen. Ta sedan bort den gamla webhooken i Discord så att den
inte längre fungerar. Är den gamla URL:en läckt ska den tas bort direkt, före rotationen.
Nästa schemalagda körning använder den nya secreten.

## Uppdatera Trivy, cosign eller basimagen

Ändra version och sha256 i `platform/security-tools/scan.sh` (checksummorna finns i
respektive releases `checksums.txt`) eller digest i `cronjob.yaml`, kör
`python3 platform/check.py`, och installera om enligt ovan. Håll cosign på samma
huvudversion som company-website signerar med tills attesteringsformatet är verifierat
för en nyare version.

## Felsökning

- **Röd felpost "ingen körande pod":** appen är nere eller etiketten har ändrats.
  Kontrollera `kubectl get pods -l app=company-website`.
- **Felpost med felkod:** läs jobbets logg. Vanliga orsaker är att primary saknar
  internet, att checksumman inte stämmer efter en versionsuppdatering, eller att
  `verify-attestation` nekar för att workflowen bytt identitet.
- **Ingen post alls:** kontrollera `kubectl get jobs -n security-tools`. Når jobbet inte
  Discord (tjänsten nere eller webhooken återkallad) avslutas det ändå med felkod och
  syns som `Failed` där. Kontrollera också `kubectl get cronjob -n security-tools` och att
  VM:en var uppe kl. 12:00. En körning som missas när noden är nere körs inte i efterhand.
  Ett jobb som hänger stoppas efter 15 minuter (`activeDeadlineSeconds`), så det blockerar
  inte nästa dags körning trots `concurrencyPolicy: Forbid`. Står podden i `Pending`
  eller `ImagePullBackOff` har skriptet aldrig startat, se Kända begränsningar.

## Tester

`tests/security_scanner/test_scan.py` kör `scan.sh` mot stubbade `curl`, `apk`, `cosign`
och `trivy`, med riktiga `jq`, `sha256sum` och `tar`, i både `sh` och `busybox sh`
(samma skal som alpine). Testerna täcker bland annat att fynd utan rättning larmar,
att misslyckad verifiering och manipulerad nedladdning stoppar jobbet, att ett
oåtkomligt Discord ger felkod och att webhook-URL:en aldrig skrivs ut. De körs i
`pr-checks.yml`.
