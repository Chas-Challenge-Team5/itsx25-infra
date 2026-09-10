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

Sätt repo-variablerna `WORKLOAD_IDENTITY_PROVIDER` och `CICD_SERVICE_ACCOUNT` från outputen. PR:er kör `fmt`, `validate` och tester av WIF-villkoret utan GCP-inloggning eller stateåtkomst. Den verkliga planen körs av `deploy.yml` på `main`, vid push eller manuell start.

Före införandet måste en GitHub-admin konfigurera environment `terraform-apply` med required reviewers, förhindra självgodkännande och begränsa deployment branches till `main`. Stäng även av administratörers bypass av miljöskyddet. Planjobbet avbryts om API-kontrollen inte kan bekräfta granskare och förbud mot självgodkännande. YAML-filen ensam aktiverar inte dessa skydd.

Planjobbet sparar planen i den befintliga GCS-bucketen under `terraform/deploy-plans/<run-id>/<run-attempt>/deploy.tfplan`. Den publiceras inte som GitHub-artifact eller i planloggen eftersom en binär plan kan innehålla känsliga värden. Granskaren behöver läsåtkomst till objektet i GCP. Bucketens befintliga IAM gäller även här; detta löser inte dess breda åtkomst i #29/#37.

Hämta planens GCS-adress och SHA-256 från körningens sammanfattning. Ladda ned med `gcloud storage cp <GCS-adress> deploy.tfplan`, kontrollera SHA-256 (PowerShell: `Get-FileHash deploy.tfplan -Algorithm SHA256`) och granska med Terraform 1.16.1: `terraform show -no-color deploy.tfplan`. Kontrollera även vilken commit planen gäller innan `terraform-apply` godkänns. Dela inte rå planutdata i publika kommentarer.

Apply-jobbet hämtar samma plan, kontrollerar dess SHA-256 och använder samma commit och providerlåsning. Det gör ingen ny plan. Om state har ändrats kan apply neka en inaktuell plan; skapa då en ny körning och granska den nya planen. Planobjektet tas bort efter lyckad apply. Vid avbruten eller misslyckad körning behöver någon med GCP-behörighet radera just det kvarvarande objektet efter felsökningen. Manuella omkörningar av apply kräver också godkännande.

Bootstrap appliceras aldrig av pipelinen. PR-checkarna kör `init -backend=false` och `validate` mot `bootstrap/`, men ingen plan. En behörig administratör behöver granska en separat bootstrap-plan och applicera WIF-ändringen samordnat med workflow-ändringarna. En merge uppdaterar inte WIF i GCP. Att bootstrap ligger utanför pipelinen begränsar vilka steg den normalt kör; det begränsar inte i sig CI-kontots IAM-rättigheter.

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

CI/CD autentiserar mot GCP med Workload Identity Federation. Konfigurationen kräver rätt repository och numeriska repo-/organisations-ID:n, `refs/heads/main`, `deploy.yml` och händelsen `push` eller `workflow_dispatch`. Villkoret gäller först när bootstrap har applicerats. Det skyddar denna WIF-väg; granskning av `main`, andra vägar till servicekontot och begränsade IAM-roller behövs också. WIF kontrollerar inte att en människa har godkänt en merge.

Öppna fynd med lägre risk ligger kvar som issues: [#8](../../issues/8) till [#14](../../issues/14). Genomgången av nyckelrisken finns i [docs/service-account-nyckel.md](docs/service-account-nyckel.md).

## Arbetssätt

Issue, branch, PR, två godkännanden, merge. `main` är skyddad med branch protection, och `Format & Validate` är obligatorisk status check. Secret scanning och push protection är på.

Repot är publikt. Det är ett medvetet val: branch protection kräver det på GitHub Free, och exponeringen stängdes innan flippen.

## Team

Mattej Petrovic (Product Owner), Viktor (Scrum Master), Abdi, Adam, Armin.
