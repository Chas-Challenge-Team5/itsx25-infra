# Intern HTTPS för company-website

Appens namn är `company-website.team5.arpa` och adressen `10.0.5.3`.
Åtkomsten ligger kvar i tailnätet. DNS ändras inte och appen exponeras inte
publikt. Arbetet hör till company-website #37 och måste verifieras före PR #36.

```text
Skolprofil i Firefox (publikt rotcertifikat)
  -> Tailscale / befintlig subnet-router
  -> primary 10.0.5.3:443 / ingress-nginx
  -> company-website i Kubernetes

cert-manager -> utfärdar och förnyar ingressens servercertifikat
               med separat utfärdarnyckel i Kubernetes

Skolkonton -> GCP Secret Manager -> CA-backup för återställning
              (utanför appens normala trafik och certifikatförnyelse)
```

## Ansvar och certifikat

Infra förvaltar TCP/443, Headscale-policyn, ingress-controllern, cert-manager
och `platform/company-tls.yaml`. App-repot förvaltar ingressen och CI:s
läsning av Certificate-status. CI får inte läsa Secrets eller ändra utfärdaren.

En separat rotnyckel signerar utfärdaren. Rotnyckeln finns i en skyddad
återställningsbackup i skolprojektets Secret Manager, inte i klustret. Endast
utfärdarnyckeln finns i `default/company-website-ca` i Kubernetes.
Utfärdarcertifikatet har `pathlen:0` och en kritisk DNS-begränsning till
`company-website.team5.arpa` och dess underdomäner enligt X.509.
Det ersätter inte RBAC: cert-manager kontrollerar inte namnbegränsningen vid
utfärdande, utan klienten måste verifiera kedjan. Cluster-admin kan läsa
utfärdarnyckeln. Installera aldrig CA:ns privata nycklar på klienterna.

Rotcertifikatet gäller i fem år, utfärdaren i två år. Servercertifikatet gäller
i 90 dagar och förnyas 30 dagar före utgång med ny nyckel (`rotationPolicy: Always`).
CA-certifikaten förnyas inte automatiskt. Ansvarig för #37 behöver bevaka deras
utgång minst månadsvis och planera utfärdarbyte minst 120 dagar före utgång.
Cert-manager garanterar inte att servercertifikatet löper ut före CA:n.
Vid rotbyte måste klienternas trust stores uppdateras före serverbytet.

CA Issuer har ingen inbyggd CRL/OCSP-tjänst. Vid komprometterad CA krävs ny
kedja, nytt servercertifikat och borttagning av den gamla roten på klienterna.
Windows curl/Schannel kan neka kedjan med okänd spärrstatus även när CA-filen
anges. Använd inte `-k` eller webbläsarundantag. Verifiera varje faktisk
webbläsare före cutover; detta är en intern labb-PKI med manuell CA-hantering.

## Första införande

Samordna deployer i båda reporna. Spara privat backup av ingress, deployer-Role,
Headscale-policy och aktuell Helm-revision. Kontrollera IAP/SSH, apphälsa,
ledigt minne och port 443. Ingen VM-omstart behövs. Noden har 2 GB RAM;
kontrollera även minnet efter installation.

1. Skapa CA-materialet på Linux/WSL:s privata filsystem utanför repot:

   ```bash
   python3 scripts/create-company-ca.py --directory "$HOME/.local/share/team5-company-ca" \
     --password-file /PRIVATE/PATH/root-passphrase
   ```

   Passfrasfilen ska innehålla minst 24 slumpmässiga tecken, vara ägd av
   operatören och ha mode 0600. Scriptet vägrar ersätta en befintlig CA.
   Spara krypterad backup och verifiera återläsning. Lämna inte passfras eller
   okrypterad utfärdarnyckel i repo, shellhistorik, loggar eller tillfälliga filer.
2. Granska och applicera Terraform-planen för primary-regelns TCP/443 med
   oförändrade källnät/måltaggar. Ändra developer-regeln i Headscale-policyn
   till `10.0.5.3:80,443`, kör `headscale policy check --file ...` och ladda
   om tjänsten. Bevara övriga regler.
3. Kör som administratör på primary:

   ```bash
   sudo bash scripts/k3s-platform.sh install-cert-manager
   sudo bash scripts/k3s-platform.sh install-ingress
   ```

   Cert-manager-chart v1.21.2 är SHA-256-låst. Ingress-versionen är oförändrad.
   Cert-manager körs i egen namespace utan appens signaturpolicy och är ett
   betrott klusterverktyg med breda rättigheter. Uppgradera separat efter granskning.
4. Importera endast `issuer.key.pem` och `issuer-chain.crt` som TLS Secret
   `company-website-ca` i `default`, via krypterad överföring/stdin. Använd
   `kubectl create` och ersätt aldrig en befintlig CA blint. Root-nyckeln får
   inte skickas till klustret. Ta bort tillfälliga privata kopior efter kontroll.
5. Applicera `platform/company-tls.yaml` och kör:

   ```bash
   sudo kubectl wait -n default --for=condition=Ready certificate/company-website --timeout=120s
   ```

   Applicera appens uppdaterade `k8s/github-permissions.yaml` som administratör.
   Deployer får endast `get` på det namngivna Certificate-objektet.
6. Lägg till TLS från appens ingressmanifest, men använd tillfälligt
   `nginx.ingress.kubernetes.io/ssl-redirect: "false"` tills klienterna
   verifierat förtroendet. Den slutliga versionshanterade ingressen har
   `"true"`; den får inte deployas innan klienterna är redo.

## Klienternas förtroende

Distribuera bara `root.crt`. Kontrollera ämne, giltighet och certifikatets
SHA-256-fingerprint över en redan betrodd kanal. Fingerprint avser DER-data,
inte PEM-filens hash. Använd en separat skolprofil i Firefox eller en skol-VM.
Installera inte roten i det privata Windowskontots certifikatlager eller den
vanliga webbläsarprofilen. Ingen privat Microsoft-/Mozilla-inloggning behövs.

Skapa en tom profil med en uttrycklig katalog, exempelvis från infra-repot:

```powershell
& 'C:\Program Files\Mozilla Firefox\firefox.exe' --no-remote --profile "$PWD\local\school-firefox" https://company-website.team5.arpa
```

Importera bara den publika roten i skolprofilen under Inställningar → Sekretess
och säkerhet → Certifikat → Visa certifikat → Certifikatutfärdare, med förtroende
för webbplatser. Kontrollera profilen under `about:profiles` först. Logga inte in
i Firefox Sync. En separat profil skiljer certifikat/cookies från privat surfning,
men är inte en separat dator eller säkerhetsgräns mot det lokala Windowskontot.
Vill man helt undvika skoldata på den privata datorn behövs en separat skol-VM/dator.

Linux/WSL och andra enheter har separata trust stores. Ett avgränsat prov kan
använda Python `ssl.create_default_context(cafile="root.crt")` utan att ändra
datorns trust store; det ersätter inte webbläsarprovet.

Verifiera HTTPS till `/`, `/login` och `/healthz` utan varningar från alla
avsedda klienter. Testa inloggning, autentiserade anrop, CSRF och utloggning
med cookieinställningarna i PR #36. Kontrollera fortsatt Spectre/DNS/IAP.
Därefter införs slutlig HTTP→HTTPS-omdirigering och sedan PR #36.

## Förnyelse och återställning

Följ Ready, `status.notAfter`, `status.renewalTime` och `status.revision`.
Ett kontrollerat prov använder `cmctl renew company-website -n default`.
Verifierad provversion är cmctl v2.6.1 linux_amd64, SHA-256
`0af054c26a2b64ce286fa868d029164867695a93c3eb893662ce16f35e708db0`.
Bekräfta högre revision, ny nyckel/certifikat och fortsatt HTTPS utan omstart.
Det provar förnyelsevägen, inte att den framtida timerkörningen har skett.
Radera inte TLS Secret för att tvinga förnyelse. Klienterna behöver inte
importera roten igen vid servercertifikatets normala förnyelse.

CA-backupen finns i Secret Manager: projekt `itsx25-lab`, secret
`team5-company-ca-backup`. `pki-backup/` förvaltar endast metadata och fem
skolkontons villkorade läsrättigheter. Terraform använder ett separat GCS-prefix
`terraform/pki-backup-state`; secret-versionens innehåll får aldrig gå genom
Terraform, state, Git eller CI. Root-deploy applicerar inte denna modul.

Granska `pki-backup/terraform.tfvars.example`, skapa en ignorerad tfvars med
teamets skolkonton och granska plan innan separat apply. Secret har deletion
protection och prevent_destroy. Projekt-IAM-villkoret omfattar bara detta
secrets kanoniska resursnamn och dess versioner. Befintliga överordnade
administratörsrättigheter kvarstår; detta isolerar inte backupen från dem.

Backupen är portabel JSON med root/issuer-nycklar, certifikat och rotens passfras.
GCP krypterar lagringen och skol-IAM styr hämtning. Eftersom passfrasen finns i
samma bundle är den inte ett oberoende krypteringsskydd mot en behörig läsare.
Detta är inte en offline-rot. CI och VM-kontona får ingen ny läsrättighet här.

Vid återställning använder en skoloperatör sin GCP-inloggning på en betrodd
administrationsdator och hämtar vald version via Secret Manager API. Hantera
svaret endast i minne eller privat tmpfs, utan utskrift eller shellspårning.
Verifiera rotens fingerprint, båda nycklarnas matchning mot certifikaten och
utfärdarens kedja. Importera sedan endast utfärdarnyckeln och kedjan i klustret
enligt steg 4; ingen rotprivatnyckel ska dit. Rensa temporära privata filer.

Den 29 september verifierades byte-för-byte-återläsning och Linux-återställning
med skolautentisering utan DPAPI. Lokala privata CA-filer togs därefter bort.
CA-expiry-bevakning och teamets faktiska klienttester kvarstår.

Vid misslyckat införande: återlägg sparad ingress/policy och använd sparad
Helm-revision vid behov. Återställ portändringen med granskad Terraform-plan.
Radera inte PVC eller CA/TLS Secrets. Återgång till HTTP måste samordnas med
cookieversionen: Secure-cookies fungerar inte där. Inaktivera inte Secure som
en tyst återställningsåtgärd.

Källor: [CA Issuer](https://cert-manager.io/docs/configuration/ca/),
[certifikat och förnyelse](https://cert-manager.io/docs/usage/certificate/),
[Firefox-profiler via kommandorad](https://firefox-source-docs.mozilla.org/browser/CommandLineParameters.html),
[CA-förtroende i Firefox](https://support.mozilla.org/en-US/kb/setting-certificate-authorities-firefox).
