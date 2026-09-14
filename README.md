# itsx25-infra

Terraform för team 5:s miljö i GCP. Ett jumphost-baserat nät i `itsx25-lab`, deployat genom GitHub Actions mot en delad state-bucket.

Repot började som en stack skriven för att fungera, inte för att vara säker. Arbetet här är säkerhetsgranskningen av den och härdningen som följde.

## Arkitektur

En VPC per lag med ett `/24`-subnät (`10.0.5.0/24`). En jumphost med extern IP är enda vägen in, resten av nätet går ut via den med NAT och `ip_forward`. Instanserna startas 08:00 och stoppas 00:00 via en resource policy för att hålla nere kostnad.

- `main.tf` nät, routes, brandvägg, jumphost
- `backend.tf` GCS-backend för state
- `bootstrap/` service account för CI/CD, state-bucketen och Workload Identity Federation
- `docs/` skriftliga underlag från granskningen
- `.github/workflows/` PR-checkar och deploy

## Så körs det

Bootstrap ligger utanför pipelinen och appliceras manuellt en gång. Den skapar bucketen som pipelinen sedan lagrar state i, så den kan inte deploya sig själv.

```bash
cd bootstrap
terraform init && terraform apply
```

Sätt sedan repo-variablerna `WORKLOAD_IDENTITY_PROVIDER` och `CICD_SERVICE_ACCOUNT` från outputen. Därefter sköter pipelinen resten: vanliga PR:er körs genom `fmt`, `validate` och `plan`, och merge till `main` kör `apply`. Dependabots PR:er kör `fmt` och `validate` med backend avstängd, utan GCP-inloggning eller plan mot miljön.

Bootstrap appliceras aldrig av pipelinen. PR-checkarna kör `init` och `validate` mot `bootstrap/` så en trasig fil fångas, men ingen `plan`, eftersom bootstrap läser IAM och kräver API:er påslagna på kvotprojektet som pipelinen inte ska röra. En admin i teamet kör `terraform plan` och sedan `terraform apply` i `bootstrap/` för hand efter att en PR som rör den mappen har mergats. Skälet är hönan och ägget: bootstrap skapar bucketen pipelinen lagrar sitt state i, så den kan inte köras av något som redan förutsätter den. Att hålla den utanför CI betyder också att pipelinen aldrig får rätten att skriva om IAM, WIF eller state-bucketen på egen hand.

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

CI/CD autentiserar mot GCP med Workload Identity Federation. Ingen nyckel finns kvar, varken i repot, i state eller som secret. Poolen är låst till det här repot med ett attribute condition, så en fork kan inte hämta en token.

Öppna fynd med lägre risk ligger kvar som issues: [#8](../../issues/8) till [#14](../../issues/14). Genomgången av nyckelrisken finns i [docs/service-account-nyckel.md](docs/service-account-nyckel.md).

## Arbetssätt

Issue, branch, PR, två godkännanden, merge. `main` är skyddad med branch protection, och `Format & Validate` är obligatorisk status check. Secret scanning och push protection är på.

Repot är publikt. Det är ett medvetet val: branch protection kräver det på GitHub Free, och exponeringen stängdes innan flippen.

## Team

Mattej Petrovic (Product Owner), Viktor (Scrum Master), Abdi, Adam, Armin.
