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

Jumphosten annonserar subnätet `10.0.5.0/24` som en Tailscale-rutt, tillsammans med värdrutten till Spectre (`10.0.0.2/32`) — båda annonseras i samma `tailscale set`-anrop, annars skriver den senare över den tidigare. Anslutna klienter använder `--accept-routes` för att ta emot annonserade rutter från jumphosten, och rutterna måste godkännas separat på Headscale-servern innan de blir aktiva.

SNAT för vidarebefordrad tailnet-trafik är avstängt (`--snat-subnet-routes=false`), så interna tjänster ser klientens faktiska Tailscale-IP i stället för jumphostens.

`team5-primary` nås antingen direkt över tailnätets subnet-rutt för ping och TCP/8000, eller via jumphosten (`ssh -J`) för SSH, när en klient anslutit till Headscale och fått rutten godkänd.

Klienter når Spectre (`10.0.0.2`) via den annonserade rutten, och `itsx25.chas-lab.dev` slås upp via Split DNS och dnsmasq på jumphosten (#51, #96, #97). Se [docs/spectre-tailnet.md](docs/spectre-tailnet.md) för införande, verifiering och återställning.

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
```

## Repots struktur

| Fil eller katalog | Innehåll |
|---|---|
| `main.tf`, `variables.tf`, `outputs.tf` | Root-modulen: VPC, subnät, jumphost, primary, brandvägg, NAT, startup-script |
| `access/` | OS Login- och Service Account User-tilldelningar (egen state) |
| `config/` | Delad konfiguration, t.ex. `headscale_proxy_cidr`, `lab_dns_zone` |
| `templates/` | Renderade hjälpscript, t.ex. `team-nat-firewall.sh.tftpl` |
| `docs/` | Fördjupande dokumentation, se nedan |
| `tests/` | Terraform- och nätverkstester |

## Dokumentation

- [docs/internal-firewall.md](docs/internal-firewall.md) – intern brandvägg och NAT
- [docs/os-login.md](docs/os-login.md) – OS Login-underlaget, se även säkerhetsärendena i [Issues](https://github.com/Chas-Challenge-Team5/itsx25-infra/issues?q=is%3Aissue)
- [docs/spectre-tailnet.md](docs/spectre-tailnet.md) – Spectre, Split DNS och tailnätets rutter
- [docs/headscale-backup.md](docs/headscale-backup.md) – backup av Headscale (#85)

Team: Mattej, Adam, Armin, Viktor, Abdi
