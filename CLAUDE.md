# itsx25-infra — Team 5

Terraform/GCP-infra för säkerhetskursen ITSX25. Ett Headscale-tailnet på en
jumphost, en k3s-nod (primary), och en pipeline som deployar appen
`company-website` bakom ingress med signerade images.

## Två repon

- **itsx25-infra** (detta): GCP via Terraform, Headscale, k3s-plattformen
  (ingress-nginx, Sigstore-signaturpolicy), och CI-workflows.
- **company-website** (separat repo): Flask-appen. Den är **avsiktligt sårbar** —
  det är en del av kursen. Sårbarheter rapporteras som issues; från Workshop 7
  patchas de också med AI-hjälp. Issues som spårar arbetet ligger i **detta** repo
  (som #108), medan koden och PR:erna ligger i company-website.

## Konventioner som inte syns i en enskild fil

- **GitHub Actions pinnas på commit-SHA**, inte flyttbara taggar.
- **Images signeras med cosign** (keyless OIDC) och verifieras. k3s har en
  `ClusterImagePolicy` (Sigstore policy-controller) som bara släpper in signerade
  images i namespace som opt-in:ats. SBOM attesteras med `cosign attest` (CycloneDX).
- **Headscale-versionen pinnas** i `headscale/setup.py` (`VERSION` +
  `PACKAGE_SHA256`). Workflowen *Headscale release monitor* föreslår uppgraderingar
  som PR automatiskt; själva serveruppgraderingen görs **manuellt** under ett
  underhållsfönster enligt `docs/headscale-updates.md`.
- **`reconfigure` i `headscale/setup.py` kräver att installerad version matchar
  `VERSION`.** Merga därför en versions-PR i *samma* fönster som serveruppgraderingen,
  aldrig fristående — annars slutar `reconfigure` fungera tills servern är uppe i takt.
- **Stora delar av k3s-plattformen bootstrappas manuellt på primary** (helm,
  ingress-nginx, policy-controller), inte via pipelinen. Merge av en infra-PR ändrar
  alltså inte det som körs live. Ordningen finns i `docs/workshop-ingress-signatures.md`.

## Test och CI

- `pr-checks.yml` kör de isolerade testerna: `headscale/check.py`,
  `platform/check.py` (renderar charten offline och validerar `image-policy.yaml`
  mot CRD:t) och tester under `tests/`. Kör dem lokalt innan PR.
- **Terraform: `plan` innan `apply`.** Applies körs av en människa, inte av en agent.
  Sparade planer kan innehålla känsliga värden (se `.gitignore`).

## Nät och drift

- `team5-jumphost` = `10.0.5.2` (Headscale/Tailscale, extern IP, nås via IAP).
- `team5-primary` = `10.0.5.3` (k3s, ingen extern IP — nås via IAP eller genom
  jumphosten som ProxyJump).
- Systemloggar från båda VM:arna skeppas till Cloud Logging (`journald`).
  oslogin-loggarna (inloggningsspårning) är Data Access-loggar och kräver rollen
  `logging.privateLogViewer` för att läsas — vanlig `logging.viewer` visar dem inte.

## Var saker ligger

- `docs/` — driftrutiner (Headscale-uppgradering/backup, os-login, systemloggar,
  ingress/signatur, Spectre-tailnet). Läs den relevanta innan du rör en tjänst.
- `bootstrap/`, `access/`, `iap-access/`, `*.tf` — Terraform.
- `headscale/`, `platform/`, `scripts/` — Headscale-installer, k3s-plattform,
  bootstrap- och bevakningsskript.

## Ton på det som postas

Issues, PR-texter, commits och kommentarer skrivs på svenska, rakt, utan
AI-register och utan attributionsrader. Nämn inte andra lag eller deras repon.
