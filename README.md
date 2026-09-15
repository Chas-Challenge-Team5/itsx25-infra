# ITSX25 – Infrastruktur

[![Deploy](https://github.com/Chas-Challenge-Team5/itsx25-infra/actions/workflows/deploy.yml/badge.svg?branch=main&event=push)](https://github.com/Chas-Challenge-Team5/itsx25-infra/actions/workflows/deploy.yml)
[![PR-kontroller](https://github.com/Chas-Challenge-Team5/itsx25-infra/actions/workflows/pr-checks.yml/badge.svg?event=pull_request)](https://github.com/Chas-Challenge-Team5/itsx25-infra/actions/workflows/pr-checks.yml)
[![Terraform 1.16.1](https://img.shields.io/badge/Terraform-1.16.1-844FBA?logo=terraform&logoColor=white)](.github/workflows/deploy.yml)
[![Öppna issues](https://img.shields.io/github/issues/Chas-Challenge-Team5/itsx25-infra?label=issues)](https://github.com/Chas-Challenge-Team5/itsx25-infra/issues)
[![Öppna PR:er](https://img.shields.io/github/issues-pr/Chas-Challenge-Team5/itsx25-infra?label=pull%20requests)](https://github.com/Chas-Challenge-Team5/itsx25-infra/pulls)

Terraform för Team 5:s labbmiljö i Google Cloud. Infrastrukturen förvaltas genom GitHub Actions, med Terraform-state i Google Cloud Storage.

Planerat arbete, säkerhetsfynd och verifieringsresultat finns i [Issues](https://github.com/Chas-Challenge-Team5/itsx25-infra/issues). Ändringar granskas i [Pull requests](https://github.com/Chas-Challenge-Team5/itsx25-infra/pulls).

## Miljön

Miljön ligger i regionen `europe-north2` i GCP-projektet `itsx25-lab`, som delas med andra team. Terraform använder den befintliga VPC:n `team5-vpc` och förvaltar subnätet `10.0.5.0/24`.

Jumphosten `team5-jumphost` har privat IP `10.0.5.2`, extern IP och IP-forwarding/NAT för teamets subnät. Teamet ansluter med SSH via Google IAP på TCP/22. Instruktörens SSH tillåts från det konfigurerade instruktörsnätet. Jumphosten startas 08:00 och stoppas 00:00 enligt tidszonen `Europe/Stockholm`.

Routes för interna maskiner använder jumphosten som nästa hopp. `primary` är fortfarande utkommenterad och ingår inte i den aktiva Terraform-konfigurationen.

## Nätverkskarta

Kartan visar konfigurationen i Terraform. Prickade linjer visar förberedda vägar för `primary`, som ännu är utkommenterad. Den är inte en liveinventering av miljön.

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
|  |                             |           | TCP/UDP alla portar |
|  |  +----------------------+   |           | samt ICMP           |
|  |  | team5-jumphost       |<--------------+                     |
|  |  | 10.0.5.2             |   |                                 |
|  |  | SSH, forwarding, NAT |   |                                 |
|  |  | Extern IP            |--------> Internet                   |
|  |  +----------------------+   |                                 |
|  |             ^               |                                 |
|  |             :               |                                 |
|  |             : Route         |                                 |
|  |             : 0.0.0.0/0     |                                 |
|  |  +----------------------+   |                                 |
|  |  | primary: 10.0.5.3    |   |                                 |
|  |  | UTKOMMENTERAD        |   |                                 |
|  |  | Ingen extern IP      |   |                                 |
|  |  +----------------------+   |                                 |
|  +-----------------------------+                                 |
+------------------------------------------------------------------+
```

Den interna brandväggsregeln tillåter TCP/UDP på alla portar samt ICMP från teamets och instruktörens subnät till taggarna `jumphost` och `primary`. Pilen från instruktörsnätet visar tillåten trafik; nätkopplingen till instruktörens VPC förvaltas inte i denna Terraform-konfiguration.

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
| `access/` | Instansspecifik OS Login- och sudoåtkomst samt mockade tester |
| `iap-access/` | Teamets villkorade IAP-behörigheter och mockade tester |
| `scripts/` | Kontroll av deploygodkännande och manuell förberedelse för Secure Boot |
| `tests/` | Tester för WIF-villkoret och kontrollen av deploygodkännande |
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

Backend-konfigurationen förutsätter att state-bucketen redan finns. En helt ny miljö kräver därför separat etablering av backend.

IAP-tilldelningarna gäller jumphostens privata IP och TCP/22. De ger tunnelåtkomst. OS Login hanterar SSH-inloggningen genom användarens Google-konto och publika SSH-nyckel i OS Login-profilen. `access/` tilldelar de fem användarna OS Admin Login på jumphosten, vilket ger sudo där.

Verifiera IAM-tilldelningarna och användarnas OS Login-profiler innan OS Login aktiveras. Kontrollera instansens IAM vid VM-ersättning och IAP-tilldelningarna vid byte eller återanvändning av IP-adress. Införande och återställning beskrivs i [OS Login-underlaget](docs/os-login.md).

Secure Boot är avstängt som standard. Det kräver separat förberedelse av en signerad kärna och verifierad uppstart innan Terraform-inställningen aktiveras. Scriptet i `scripts/prepare-secure-boot.sh` körs manuellt; en deploy installerar ingen kärna. Den nuvarande grundimagen måste också förberedas vid återskapande.

## CI/CD

GitHub Actions autentiserar mot GCP genom Workload Identity Federation. Repo-variablerna `WORKLOAD_IDENTITY_PROVIDER` och `CICD_SERVICE_ACCOUNT` anger provider och servicekonto. Värdena hämtas från bootstrap-modulens utdata.

Alla PR:er mot main, även Dependabots, kör formatkontroll, validering och tester utan GCP-autentisering eller backendåtkomst. Kontrollerna omfattar de fyra Terraform-rötterna, mockade åtkomsttester, WIF- och godkännandetester samt syntaxkontroll av Secure Boot-scriptet. PR-jobbet kör ingen plan mot miljön.

Vid push till main skapar deploy-workflowen en plan i den privata state-bucketen, under `terraform/deploy-plans/`. Körningens sammanfattning visar commit, planens adress och SHA-256. En annan granskare granskar planen och godkänner `terraform-apply` innan samma sparade plan appliceras. Planens SHA-256 kontrolleras före apply och planobjektet tas bort efter lyckad apply. Planfiler publiceras inte som GitHub-artifacts.

Deploy kan även startas manuellt från main. Körningarna serialiseras med `concurrency`. Godkännandemiljön kontrolleras före GCP-autentisering och ska kräva granskare, förbjuda självgodkännande och admin-bypass samt endast tillåta main. CI-kontot behöver åtkomst till både rotmodulens state och planobjekten; granskarna behöver kunna läsa planen. Avbrutna eller avvisade planer städas av en behörig användare.

WIF-villkoret i bootstrap begränsar autentiseringen till rätt repo och numeriska repo-/organisations-ID:n, main, deploy-workflowen och händelserna push eller manuell start. Det behöver appliceras separat och samordnas med workflow-ändringar; en merge uppdaterar inte WIF i GCP. Bootstrap, access och IAP-modulen appliceras inte av deploy-jobbet.

Godkända CI-kontroller behöver kompletteras med funktionstest vid exempelvis ändrad SSH-, proxy- eller nätverksåtkomst.

## Arbetssätt

Beskriv arbetet i en issue, gör ändringarna på en branch och öppna en PR mot main. Granska ändringen och CI-resultatet före merge. Dokumentera lösning, verifiering och kvarstående arbete i tillhörande issue eller PR.

Main skyddas av ett aktivt ruleset som kräver två godkännanden och godkänd `Format & Validate`. Nya ändringar kräver förnyad granskning, inklusive godkännande från någon annan än den som senast pushade. GitHub Actions är låsta till fullständiga commit-SHA:er och Dependabot bevakar beroenden. Deploy använder WIF för kortlivade inloggningsuppgifter.

README beskriver hur projektet används. Aktuell arbetsstatus och säkerhetsfynd förvaltas i GitHub Issues.

## Team

Mattej (Product Owner), Viktor (Scrum Master), Abdi, Adam och Armin.
