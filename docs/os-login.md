# OS Login för Team 5 (issue #12)

> **Uppdatering:** Secure Boot är sedan #63 (jumphost) och #79/#81 (primary)
> aktiverat för både jumphost och primary. Texten nedan beskriver läget vid
> ursprunglig verifiering, då Secure Boot var avstängt i väntan på ett
> signerat kärnbyte.

## Verifiering 14 september 2026

OS Login har testats på jumphosten: ny SSH-inloggning via IAP, sudo till root
och Spectre via SOCKS-proxy fungerade med det aktiva teamkontot. De fem
instansspecifika IAM-tilldelningarna har applicerats i `access/`.

Secure Boot-testet misslyckades med den osignerade kärnan på jumphostens bootdisk.
Samma seriella logg innehöll både `prohibited by secure boot policy` och
`bad shim signature`, följt av `Failed to boot both default and fallback entries`.
Felsökningen identifierade en osignerad, låst kärna. En signerad ersättningskärna
testades senare samma dag med Secure Boot på en separat VM, men den ordinarie
jumphosten och grundimagen har ännu inte fått kärnbytet.
Införandet hanteras i [issue #63](https://github.com/Chas-Challenge-Team5/itsx25-infra/issues/63).
`enable_secure_boot` var då som standard `false` så att OS Login kunde införas
separat från kärnbytet. vTPM och integrity monitoring behölls aktiverade genom
hela övergången. Secure Boot är nu aktiverat för båda maskinerna (#63, #79, #81).
Att GCP visar VM:n som RUNNING bevisar inte att operativsystemet har startat.

Efter testet återställdes VM:n till tidigare SSH-metadata och Secure Boot av.
SSH, sudo och SOCKS verifierades igen; root-planen mot main visade inga ändringar.
De fem IAM-tilldelningarna behölls, och `access/` visade också inga ändringar.
OS Login är alltså testat men ännu inte permanent infört. Se även testresultatet
i [issue #12](https://github.com/Chas-Challenge-Team5/itsx25-infra/issues/12).

Alla fem användare får `roles/compute.osAdminLogin` på endast `team5-jumphost`
i `itsx25-lab`, zon `europe-north2-b`. Listan finns i `access/terraform.tfvars`.
Tilldelningen använder `google_compute_instance_iam_member`, som bevarar
andra användares befintliga tilldelningar. Projektets IAM ändras inte.

## Komplettering för jumphostens tjänstekonto

Issue #46 kopplar `team5-jumphost@itsx25-lab.iam.gserviceaccount.com` till VM:n.
När en VM har ett tjänstekonto kräver OS Login även `roles/iam.serviceAccountUser`
på det kontot. `access/` förbereder därför en `google_service_account_iam_member`
för var och en av samma fem användare, begränsad till just jumphostens tjänstekonto.
Modulen förvaltar inte tjänstekontots egna roller eller dess koppling till VM:n.

Dessa fem tilldelningar ingick inte i testet den 14 september. De behöver granskas,
appliceras separat och verifieras innan VM:n samtidigt har OS Login aktiverat och
tjänstekontot anslutet, oavsett i vilken ordning #12 och #46 införs. Kontrollera
också instruktörens motsvarande behörighet. Att mergas till main applicerar inte `access/`.

Kontroll den 15 september 2026 bekräftade att tjänstekontot finns men ännu inte
är kopplat till jumphosten. En verklig access-plan visade fem nya Service Account
User-tilldelningar och inga ändringar av de befintliga OS Admin Login-tilldelningarna.
Det aktiva användarkontot hade `actAs`, `getIamPolicy` och `setIamPolicy` på
tjänstekontot. Planen applicerades inte; inloggning med kombinationen OS Login
och anslutet tjänstekonto behöver verifieras efter införandet.

## Ordning vid införande

1. En behörig användare granskar en färsk plan för `access/` **före merge**.
   OS Admin Login-tilldelningarna applicerades vid tidigare test. Planen behöver nu
   även omfatta de fem tilldelningarna på jumphostens befintliga tjänstekonto.
   Applicera granskade ändringar separat; verifiera därefter att planen saknar ändringar.
   Inför deployflödet i PR #62 före denna ändring. Rotmodulen aktiverar då
   OS Login när den sparade planen har granskats och godkänts i `terraform-apply`.
   Godkänn inte apply innan tilldelningen och användarnas OS Login-profiler är verifierade.
2. Administratören behöver `compute.instances.getIamPolicy` och
   `compute.instances.setIamPolicy` på jumphosten samt åtkomst till state-backenden.
   För tjänstekontot krävs dessutom `iam.serviceAccounts.getIamPolicy` och
   `iam.serviceAccounts.setIamPolicy`. Kontrollera behörigheterna på det aktuella kontot.
   CI-kontot har `compute.instances.setIamPolicy` genom `roles/compute.instanceAdmin.v1`
   (#10) och genom `InstanceIAMManager`, som gäller instanser vars namn börjar med `team`.
   Den effektiva behörigheten har inte funktionstestats som CI-kontot.
   Åtkomstmodulen behåller separat state och appliceras inte av CI. Rotmodulens
   OS Login-ändring använder metadataåtkomst, som CI-kontot har via `roles/compute.instanceAdmin.v1`.
3. Från repots rot, med administratörens egna inloggningsuppgifter:

   ```powershell
   gcloud auth application-default login
   terraform -chdir=access init
   terraform -chdir=access plan -out=access.tfplan
   # Granska även de nya Service Account User-tilldelningarna inför #46.
   # Kör apply endast för granskade ändringar efter uttryckligt godkännande.
   # terraform -chdir=access apply access.tfplan
   gcloud compute instances get-iam-policy team5-jumphost --project=itsx25-lab --zone=europe-north2-b
   gcloud iam service-accounts get-iam-policy team5-jumphost@itsx25-lab.iam.gserviceaccount.com --project=itsx25-lab
   ```

   Kontrollera även `compute.projects.get` för användarnas CLI-inloggning.
   Service Account User på jumphostens tjänstekonto förvaltas nu av modulen.
   Användare från en annan organisation kan behöva OS Login External User,
   som inte delas ut av modulen.
4. Kontrollera att den anpassade Debian-imagen stöder OS Login. Vid den
   ursprungliga övergången lämnades Secure Boot avstängt tills de signerade
   kärnorna infördes och testades (se #63 för jumphost och #79 för primary).
   Granska rotmodulens plan före merge: OS Login aktiveras och metadata-nycklarna
   tas bort. vTPM/integrity monitoring ska behållas. `enable_secure_boot` är
   fortfarande `false` som standard, och labbimagen har ännu den osignerade
   kärnan (#63) — Secure Boot aktiveras inte automatiskt för nya instanser.
   Utred all oväntad VM-ersättning eller stopp/start innan införandet.
5. Samordna införandet med #28/PR #62: det nya deployflödet ska finnas på main
   och kräver granskning av den privata planen och environment-godkännande före apply.
   Behåll access- och IAP-tester när PR-workflowen sammanfogas; återinför inte
   GCP-autentisering i PR-jobbet efter #62. Inför sedan OS Login. Vid den
   ursprungliga övergången skedde detta med `enable_secure_boot = false`,
   eftersom Secure Boot krävde ett separat verifierat införande (nu slutfört
   genom #63, #79 och #81).
   Håll administratören tillgänglig tills alla fem har testat en ny inloggning:

   ```powershell
   gcloud compute ssh team5-jumphost --project=itsx25-lab --zone=europe-north2-b --tunnel-through-iap
   ```

   Kör `sudo whoami` på servern; svaret ska vara `root`.
   OS Login kan ge andra Linux-användarnamn och hemkataloger än tidigare.
   Kontrollera åtkomst till tidigare arbetsfiler separat.

   Använd kommandot ovan först efter att OS Login har aktiverats. Före övergången
   används `start-iap-tunnel` och befintlig SSH-nyckel, så att `gcloud compute ssh`
   inte lägger till nya nycklar i instansmetadata. Efter övergången kan SOCKS-proxyn
   startas genom OS Login och IAP:

   ```powershell
   gcloud compute ssh team5-jumphost --project=itsx25-lab --zone=europe-north2-b --tunnel-through-iap -- -N -D 127.0.0.1:1080 -o ExitOnForwardFailure=yes
   ```

   Firefox använder fortsatt SOCKS v5 på `127.0.0.1:1080` med DNS via proxyn.
   Gamla Linux-användarnamn och nycklar fungerar inte automatiskt via OS Login;
   nyckeln behöver finnas i användarens OS Login-profil. Instruktörens nätregel
   ger endast nätåtkomst: instruktören behöver också OS Login-behörighet och profil.

Om tilldelningen eller kontrollerna misslyckas: stoppa före merge.
Vid problem efter aktivering behöver administratören återställa fungerande
åtkomst, exempelvis genom en granskad återställning av både OS Login-inställningen
och tidigare SSH-metadata. Enbart avstängning av OS Login återför inte borttagen
metadata. Ta inte bort IAM-tilldelningarna medan de behövs för inloggning.

Om det tidigare projektomfattande IAM-förslaget redan har applicerats måste dess
state och tilldelningar inventeras före övergången. Instansmodulen tar inte bort
befintlig projektåtkomst. Granska varje eventuell borttagning i det delade projektet.

## Fortsatt underhåll

Ändringar av användarlistan genomförs av en administratör med plan och apply i
`access/`. Om VM:n ersätts måste dess IAM kontrolleras och vid behov återappliceras
innan användarna kan logga in. Tilldelningen omfattar inte andra eller framtida VM:ar.
Vid byte av tjänstekonto behöver tilldelningen av Service Account User anpassas och
verifieras innan bytet genomförs. Tilldelningarna använder samma användarlista som OS Login.
SSH-brandvägg och CI:s WIF ändras inte av denna lösning.

## Validering utan molnåtkomst

```powershell
terraform -chdir=access init -backend=false -lockfile=readonly
terraform -chdir=access validate
terraform -chdir=access test
```

Testerna använder en mockad provider och ändrar inga resurser i GCP.

Källor: [OS Login](https://docs.cloud.google.com/compute/docs/oslogin/set-up-oslogin),
[instans-IAM i Terraform](https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/compute_instance_iam).

## Kontroll inför PR – 14 september 2026

Efter uppdatering mot main `271872a` visar en verklig root-plan endast update av
jumphostens metadata: ta bort `ssh-keys` och sätta `enable-oslogin = TRUE`.
Ingen VM-ersättning, ändring av startup-script, brandvägg eller Shielded-inställningar
planeras. Access-planen visar inga ändringar och fem instansspecifika grants finns.
Planerna gjordes med ett användarkonto, inte CI-kontot, och har inte applicerats.

Instruktörens synliga Owner-tilldelning innehåller OS Login/OS Admin Login och
compute.projects.get. Detta ersätter inte ett praktiskt test av instruktörens
OS Login-profil och nya inloggning. Behåll denna kontroll inför övergången.

Återställningsunderlag finns lokalt för samma VM-ID; tidigare SSH-nyckelbackup
matchar aktuell metadata och snapshoten är READY. Aktivt användarkonto har
metadata- och instans-IAM-skrivning. Ta en färsk backup och granska en ny plan
med statelås vid det godkända införandet. Testresultat för hela teamet och
instruktören återstår; ingen permanent OS Login-aktivering har gjorts här.
