# Supply chain-scanner (Trivy + cosign)

Ett CronJob i namespace `security-tools` scannar dagligen kl. 12:00
(Europe/Stockholm) den *körande* company-website-imagen. Jobbet frågar
k8s-API:t efter podden med `app=company-website`, tar dess image-digest,
verifierar SBOM-attesteringen med `cosign verify-attestation`, scannar med
Trivy och postar resultatet till en Discord-webhook. Inget fynd ger en grön
post, High/Critical ger en röd post med rapporten bifogad, och ett avbrott
(ingen pod, verifieringen misslyckas, Trivy kraschar) ger en röd felpost.
Tystnad ska aldrig betyda "rent".

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
  webhook-URL hittas under `platform/security-tools/`.
- **Pinnat.** Basimagen är `alpine:3.24@sha256:…`. Trivy och cosign hämtas från
  GitHub Releases med version och sha256 i `scan.sh`, kontrollerade med `sha256sum -c`
  före körning. Cosign är samma version (2.6.4) som company-websites deploy-workflow signerar med.
- **Verifierad SBOM.** `verify-attestation` kontrollerar signaturen mot samma
  identitet som `ClusterImagePolicy` (`deploy.yml@refs/heads/main`). En SBOM som
  någon annan lagt upp scannas inte.
- **Ingen fallback-image.** Kursmaterialet faller tillbaka på `:latest` när ingen pod
  hittas. Det scannar något som inte körs, så här larmar jobbet i stället.

`apk add curl jq` hämtar fortfarande paket från Alpines signerade repo vid varje körning.
Paketversionerna är alltså inte pinnade, bara basimagens digest.

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

Förväntat: en post i Discord-kanalen och jobbet i status `Completed`. Radera alltid
testjobbet efteråt. Första körningen laddar Trivy-databasen och tar några minuter.

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
- **Ingen post alls:** kontrollera `kubectl get cronjob -n security-tools` och att VM:en
  var uppe kl. 12:00. En körning som missas när noden är nere körs inte i efterhand.
