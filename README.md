Ja — problemet är att jag lade Markdown-filen i ett skrivblock, vilket gör att GitHub inte får exakt den råa `.md`-strukturen vid kopiering.

 Här är den **råa Markdown-källan**. Kopiera allt från `# ITSX25` till slutet och klistra direkt in i `README.md`:

````
# ITSX25 – Infrastruktur

[![Deploy](https://github.com/Chas-Challenge-Team5/itsx25-infra/actions/workflows/deploy.yml/badge.svg?branch=main&event=push)](https://github.com/Chas-Challenge-Team5/itsx25-infra/actions/workflows/deploy.yml)
[![PR-kontroller](https://github.com/Chas-Challenge-Team5/itsx25-infra/actions/workflows/pr-checks.yml/badge.svg?event=pull_request)](https://github.com/Chas-Challenge-Team5/itsx25-infra/actions/workflows/pr-checks.yml)
[![Terraform 1.16.1](https://img.shields.io/badge/Terraform-1.16.1-844FBA?logo=terraform&logoColor=white)](.github/workflows/deploy.yml)
[![Öppna issues](https://img.shields.io/github/issues/Chas-Challenge-Team5/itsx25-infra?label=issues)](https://github.com/Chas-Challenge-Team5/itsx25-infra/issues)
[![Öppna PR:er](https://img.shields.io/github/issues-pr/Chas-Challenge-Team5/itsx25-infra?label=pull%20requests)](https://github.com/Chas-Challenge-Team5/itsx25-infra/pulls)

Terraform för Team 5:s labbmiljö i Google Cloud. Infrastrukturen förvaltas genom GitHub Actions, med Terraform-state i Google Cloud Storage.

Planerat arbete, säkerhetsfynd och verifieringsresultat finns i [Issues](https://github.com/Chas-Challenge-Team5/itsx25-infra/issues?q=is%3Aissue). Ändringar granskas i [Pull requests](https://github.com/Chas-Challenge-Team5/itsx25-infra/pulls).

## Miljön

Miljön ligger i regionen `europe-north2` i GCP-projektet `itsx25-lab`, som delas med andra team. Terraform använder den befintliga VPC:n `team5-vpc` och förvaltar subnätet `10.0.5.0/24`.

Jumphosten `team5-jumphost` har privat IP `10.0.5.2`, extern IP och IP-forwarding/NAT för teamets subnät. Teamet ansluter med SSH via Google IAP på TCP/22. Instruktörens SSH tillåts från det konfigurerade instruktörsnätet. Jumphosten startas 08:00 och stoppas 00:00 enligt tidszonen `Europe/Stockholm`.

Den interna instansen `team5-primary` har privat IP `10.0.5.3` och ingen extern IP. Ping och TCP/8000 når primary direkt över subnet-rutten från tailnätet, men SSH gör det inte. Eftersom SNAT är avstängt släpper `team5-allow-internal` inte in TCP/22 från tailnätet till primary. SSH till primary görs därför med `ssh -J` via jumphosten. Primary går ut mot internet genom jumphostens NAT. Routes för interna maskiner använder jumphosten som nästa hopp.

## Tailnätet

Headscale körs på jumphosten (`team5-jumphost`) och exponeras på `https://team5.itsx25.chas-lab.dev`. MagicDNS-domänen är `team5.arpa`. Registrerade användare motsvarar teamets medlemmar (Mattej, Viktor, Abdi, Adam, Armin).

Jumphosten annonserar subnätet `10.0.5.0/24` som en Tailscale-rutt, tillsammans med värdrutten till Spectre (`10.0.0.2/32`) när den läggs till (#51) — båda måste annonseras i samma `tailscale set`-anrop, annars skriver den senare över den tidigare. Anslutna klienter använder `--accept-routes` för att ta emot annonserade rutter från jumphosten, och rutterna måste godkännas separat på Headscale-servern innan de blir aktiva.

SNAT för vidarebefordrad tailnet-trafik är avstängt (`--snat-subnet-routes=false`), så interna tjänster ser klientens faktiska Tailscale-IP i stället för jumphostens.

`team5-primary` nås antingen direkt över tailnätets subnet-rutt för ping och TCP/8000, eller via jumphosten (`ssh -J`) för SSH, när en klient anslutit till Headscale och fått rutten godkänd.

> **Ofärdigt:** Split DNS för zonen `itsx25.chas-lab.dev` och dnsmasq som DNS-proxy mot GCP:s interna DNS är under arbete (#51). Detta avsnitt kompletteras när #51 och #52 är klara.

## Nätverkskarta

Kartan visar konfigurationen i Terraform. Den är inte en liveinventering av miljön.

```text
Klient
SSH / Firefox via SOCKS
        |
        v
Google IAP
35.235.240.0/20
        |
        | TCP/22
        v
+------------------------------------------------------------------+
| GCP-projekt: itsx25-lab                                          |
|                                                                  |
|  +-----------------------------+     Instruktörsnät              |
|  | team5-vpc                   |     10.0.0.0/24                 |
|  | Subnät: 10.0.5.0/24         |           |                     |
|  |                             |           | TCP/22 (SSH)        |
|  |  +----------------------+   |           |                     |
|  |  | team5-jumphost       |<--------------+                     |
|  |  | 10.0.5.2             |   |                                 |
|  |  | SSH, forwarding, NAT |   |                                 |
|  |  | Extern IP            |--------> Internet                   |
|  |  +----------------------+   |                                 |
|  |             ^               |                                 |
|  |             |               |                                 |
|  |             | Route         |                                 |
|  |             | 0.0.0.0/0     |                                 |
|  |  +----------------------+   |                                 |
|  |  | team5-primary        |   |                                 |
|  |  | 10.0.5.3             |   |                                 |
|  |  | Ingen extern IP      |   |                                 |
|  |  +----------------------+   |                                 |
|  +-----------------------------+                                 |
+------------------------------------------------------------------+
````

 Den interna brandväggsregeln (`team5-allow-internal`) tillåter TCP/22 (SSH) från teamets och instruktörens subnät till både jumphost och primary. Den släpper alltså in TCP/22 till både jumphosten och primary, inte bara till jumphosten. Eftersom SNAT för tailnet-trafik är avstängt släpper regeln däremot inte in TCP/22 från tailnätet till primary.

 En separat regel (`team5-allow-primary-services`) tillåter TCP/8000 och ICMP från teamets subnät och tailnätet till taggen `primary`. En tredje regel (`team5-allow-forwarded-nat`) tillåter TCP/80 och TCP/443 från teamets subnät, vidarebefordrat genom jumphosten mot internet. En fjärde regel (`team5-allow-headscale-proxy`) tillåter TCP/8080 från instruktörens proxy till jumphosten. Pilen från instruktörsnätet visar tillåten trafik; nätkopplingen till instruktörens VPC förvaltas inte i denna Terraform-konfiguration.

 Routes för `0.0.0.0/0` och `100.64.0.0/10` pekar på jumphosten för maskiner med taggen `no-external-ip`. Tailnet-routen finns i koden, men visar inte i sig att ett fungerande tailnät är etablerat.

 ## Repots struktur

 | Fil eller katalog | Innehåll |
| --- | --- |
| `main.tf` | Subnät, routes, jumphost, driftschema, intern brandvägg och startup-script |
| `firewall-imported.tf` | SSH-regler för IAP och instruktörsnätet samt import-block |
| `variables.tf`, `terraform.tfvars` | Variabeldefinitioner och miljöns värden |
| `terraform.tfvars.example` | Exempel på indata |
| `outputs.tf` | Utdata från rotmodulen |
| `backend.tf` | Rotmodulens GCS-backend |
| `bootstrap/` | CI-servicekonto, IAM, WIF och state-bucket |
| `access/` | OS Login/sudo på jumphosten och primary, åtkomst till jumphostens tjänstekonto och mockade tester |
| `iap-access/` | Teamets villkorade IAP-behörigheter och mockade tester |
| `headscale/` | Headscale-serverkonfiguration och `setup.py` (#77) |
| `templates/` | `team-nat-firewall.sh.tftpl`, renderas in i jumphostens startup-script |
| `.tflint.hcl` | Gemensam TFLint-konfiguration (google-pluginet) som används för alla fyra Terraform-rötter via `--config` |
| `scripts/` | Kontroll av deploygodkännande och manuell förberedelse för Secure Boot |
| `tests/` | Tester för WIF, CI:s objektåtkomst och kontrollen av deploygodkännande |
| `.github/workflows/` | PR-kontroller och deploy |
| `.github/dependabot.yml` | Bevakning av GitHub Actions, Terraform i roten och bootstrap samt Python-testberoenden |
| `docs/` | Fördjupande underlag |

## State och separat förvaltade moduler

 Alla fyra Terraform-rötter använder bucketen `team5-tfstate-f7036a24`, med egna state-prefix:

 | Terraform-rot | State-prefix | Införande |
| --- | --- | --- |
| Reporoten | `terraform/state` | Deploy-workflow |
| `bootstrap/` | `terraform/bootstrap-state` | Manuellt av behörig operatör |
| `access/` | `terraform/access-state` | Manuellt av behörig operatör |
| `iap-access/` | `terraform/iap-access` | Manuellt av behörig operatör |

Bootstrap, OS Login-åtkomst och IAP-åtkomst förvaltas separat. Deploy-workflowen applicerar endast rotmodulen, efter att en granskare har godkänt dess sparade plan. Granska en plan i respektive katalog inför ändringar i de separat förvaltade modulerna; en plan utan ändringar kräver ingen ny apply.

 Bootstrap-konfigurationen begränsar CI-kontots objektåtkomst till `terraform/state/` och `terraform/deploy-plans/`. Kontot får också lista objekt i hela bucketen, men listningsrollen ger ingen åtkomst till deras innehåll. Bucketpolicyn införs genom separat bootstrap-apply.

 Backend-konfigurationen förutsätter att state-bucketen redan finns. En helt ny miljö kräver därför separat etablering av backend.

 IAP-tilldelningarna gäller jumphostens privata IP och TCP/22. De ger tunnelåtkomst. OS Login hanterar SSH-inloggningen genom användarens Google-konto och publika SSH-nyckel i OS Login-profilen. `access/` tilldelar de fem användarna OS Admin Login på jumphosten och på primary, vilket ger sudo där. Jumphosten har ett särskilt tjänstekonto kopplat till sig; `access/` tilldelar även den Service Account User-behörighet som användarna behöver för att logga in på en VM med tjänstekonto.

 Verifiera IAM-tilldelningarna och användarnas OS Login-profiler innan OS Login aktiveras. Kontrollera instansens IAM vid VM-ersättning och IAP-tilldelningarna vid byte eller återanvändning av IP-adress. Införande och återställning beskrivs i OS Login-underlaget.

 Secure Boot är aktiverat för både jumphost och primary sedan kärnbytet är verifierat (#76, #81). Aktiveringen krävde separat förberedelse av en signerad kärna och verifierad uppstart innan Terraform-inställningen sattes. Scriptet i `scripts/prepare-secure-boot.sh` användes för detta engångsbyte; en ny grundimage vid återskapande av en instans måste fortfarande förberedas på samma sätt innan Secure Boot kan förbli aktiverat.

 `enable_secure_boot` har fortfarande standardvärdet `false` och sätts till `true` i `terraform.tfvars`. En ny instans från labbimagen startar inte med Secure Boot förrän kärnan har bytts och uppstartsfelet som beskrivs i #63 har åtgärdats. Secure Boot är alltså inte aktiverat som standard för nya instanser.

 ## CI/CD

 GitHub Actions autentiserar mot GCP genom Workload Identity Federation. Repo-variablerna `WORKLOAD_IDENTITY_PROVIDER` och `CICD_SERVICE_ACCOUNT` anger provider och servicekonto. Värdena hämtas från bootstrap-modulens utdata.

 Alla PR:er mot main, även Dependabots, kör formatkontroll, validering och tester utan GCP-autentisering eller backendåtkomst. Kontrollerna omfattar de fyra Terraform-rötterna, mockade åtkomsttester, tester av WIF- och lagringsvillkor, godkännandeskydd, syntaxkontroll av Secure Boot-scriptet samt TFLint (med google-pluginet) och Checkov för samtliga rötter (#82). PR-jobbet kör ingen plan mot miljön.

 Vid push till main skapar deploy-workflowen en plan i den privata state-bucketen, under `terraform/deploy-plans/`. Körningens sammanfattning visar commit, planens adress och SHA-256. En annan granskare granskar planen och godkänner `terraform-apply` innan samma sparade plan appliceras. Planens SHA-256 kontrolleras före apply och planobjektet tas bort efter lyckad apply. Planfiler publiceras inte som GitHub-artifacts.

 Deploy kan även startas manuellt från main. Körningarna serialiseras med `concurrency`. Godkännandemiljön kontrolleras före GCP-autentisering och ska kräva granskare, förbjuda självgodkännande och admin-bypass samt endast tillåta main. CI-kontot behöver åtkomst till både rotmodulens state och planobjekten; granskarna behöver kunna läsa planen. Avbrutna eller avvisade planer städas av en behörig användare.

 WIF-villkoret i bootstrap begränsar autentiseringen till rätt repo och numeriska repo-/organisations-ID:n, main, deploy-workflowen och händelserna push eller manuell start. Det behöver appliceras separat och samordnas med workflow-ändringar; en merge uppdaterar inte WIF i GCP. Bootstrap, access och IAP-modulen appliceras inte av deploy-jobbet.

 Godkända CI-kontroller behöver kompletteras med funktionstest vid exempelvis ändrad SSH-, proxy- eller nätverksåtkomst.

 ## Arbetssätt

 Beskriv arbetet i en issue, gör ändringarna på en branch och öppna en PR mot main. Granska ändringen och CI-resultatet före merge. Dokumentera lösning, verifiering och kvarstående arbete i tillhörande issue eller PR.

 Main skyddas av ett aktivt ruleset som kräver minst ett godkännande och godkänd `Format & Validate`. Nya ändringar kräver förnyad granskning, inklusive godkännande från någon annan än den som senast pushade. GitHub Actions är låsta till fullständiga commit-SHA:er och Dependabot bevakar beroenden. Deploy använder WIF för kortlivade inloggningsuppgifter.

 Säkerhetsfynd, åtgärder och verifieringsresultat finns samlade bland säkerhetsärendena i GitHub Issues. Länken visar både öppna och stängda ärenden. Varje issue beskriver risken, arbetet och vad som har verifierats; aktuell status följs där.

 ## Team

 Mattej (Product Owner), Viktor (Scrum Master), Abdi, Adam och Armin. Jumphosten är registrerad under användaren `admin`.

 _Senast uppdaterad: 17 september 2026._

