# itsx25-infra

Terraform för team 5:s miljö i GCP. Ett jumphost-baserat nät i `itsx25-lab`, deployat genom GitHub Actions mot en delad state-bucket.

Repot började som en stack skriven för att fungera, inte för att vara säker. Arbetet här är säkerhetsgranskningen av den och härdningen som följde.

## Arkitektur

En VPC per lag med ett `/24`-subnät (`10.0.5.0/24`). En jumphost med extern IP är enda vägen in, resten av nätet går ut via den med NAT och `ip_forward`. Instanserna startas 08:00 och stoppas 00:00 via en resource policy för att hålla nere kostnad.

- `main.tf` nät, routes, brandvägg, jumphost
- `backend.tf` GCS-backend för state
- `bootstrap/` service account för CI/CD, state-bucketen och Workload Identity Federation
- `iap-access/` separat förvaltade, villkorade IAP-tilldelningar för teamet; state-prefix `terraform/iap-access`, ingen automatisk apply. Tilldelningen gäller jumphostens privata IP och TCP/22. Kontrollera IP-återanvändning/överlappning innan apply. Befintlig SSH och OS Login hanteras separat.
- `docs/` skriftliga underlag från granskningen
- `.github/workflows/` PR-checkar och deploy

## Så körs det

Bootstrap ligger utanför pipelinen och appliceras manuellt en gång. Den skapar bucketen som pipelinen sedan lagrar state i, så den kan inte deploya sig själv.

```bash
cd bootstrap
terraform init && terraform apply
```

Alla PR:er kör formatkontroll, backendfri validering och tester utan GCP-inloggning. Deploy på `main` skapar en plan i den privata GCS-bucketen. Planens adress och SHA-256 visas i körningens sammanfattning; en annan granskare granskar planen och godkänner environment `terraform-apply` innan samma sparade plan appliceras. Inga planfiler publiceras som GitHub-artifacts.

Bootstrap appliceras separat. WIF-ändringen behöver appliceras samordnat med workflow-ändringarna; merge uppdaterar inte WIF i GCP. Environment måste ha reviewers, förbud mot självgodkännande, endast `main` och avstängd admin-bypass. Avbrutna planobjekt behöver städas av en behörig användare.

Rotmodulen lokalt:

```bash
terraform init
terraform plan
```

`terraform.tfvars` är committad eftersom uppgiften kräver det. State är det inte, och ska inte bli det.

## Säkerhet

Fyra fynd prioriterade på risk och åtgärdade genom PR-flödet.

| Fynd | Risk | Status |
| --- | --- | --- |
| State-bucketen läsbar för alla Google-konton på internet ([#3](../../issues/3)) | P0 | Åtgärdat |
| Brandväggen släppte in alla protokoll från hela internet ([#6](../../issues/6)) | P0 | Åtgärdat |
| Långlivad service account-nyckel i klartext i state ([#11](../../issues/11)) | P0 | Åtgärdat, migrerat till WIF |
| SSH-nycklar saknades i `ssh_users` ([#1](../../issues/1)) | P2 | Åtgärdat |

CI/CD använder Workload Identity Federation. Efter separat bootstrap-apply krävs rätt repo och numeriska repo-/organisations-ID:n, `main`, `deploy.yml` samt push eller manuell start. Skyddet begränsar denna autentiseringsväg; CI-kontots roller hanteras separat.

Öppna fynd med lägre risk ligger kvar som issues: [#8](../../issues/8) till [#14](../../issues/14). Genomgången av nyckelrisken finns i [docs/service-account-nyckel.md](docs/service-account-nyckel.md).

## Arbetssätt

Issue, branch, PR, två godkännanden, merge. `main` är skyddad med branch protection, och `Format & Validate` är obligatorisk status check. Secret scanning och push protection är på.

Repot är publikt. Det är ett medvetet val: branch protection kräver det på GitHub Free, och exponeringen stängdes innan flippen.

## Team

Mattej Petrovic (Product Owner), Viktor (Scrum Master), Abdi, Adam, Armin.
