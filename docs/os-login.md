# OS Login för Team 5 (issue #12)

Alla fem användare får `roles/compute.osAdminLogin` på endast `team5-jumphost`
i `itsx25-lab`, zon `europe-north2-b`. Listan finns i `access/terraform.tfvars`.
Tilldelningen använder `google_compute_instance_iam_member`, som bevarar
andra användares befintliga tilldelningar. Projektets IAM ändras inte.

## Ordning vid införande

1. En administratör granskar och kör `access/` från denna branch **före merge**.
   Rotmodulen aktiverar OS Login automatiskt vid deploy efter merge. Kör inte
   rotmodulens apply innan tilldelningen är verifierad.
2. Administratören behöver `compute.instances.getIamPolicy` och
   `compute.instances.setIamPolicy` på jumphosten samt åtkomst till state-backenden.
   Deploykontots nuvarande Editor-roll saknar `compute.instances.setIamPolicy`.
   Därför har åtkomstmodulen separat state och körs aldrig med apply i CI.
3. Från repots rot, med administratörens egna inloggningsuppgifter:

   ```powershell
   gcloud auth application-default login
   terraform -chdir=access init
   terraform -chdir=access plan -out=access.tfplan
   # Granska: endast fem instansspecifika IAM-tilldelningar ska tillkomma.
   terraform -chdir=access apply access.tfplan
   gcloud compute instances get-iam-policy team5-jumphost --project=itsx25-lab --zone=europe-north2-b
   ```

   Kontrollera även `compute.projects.get` för användarnas CLI-inloggning.
   Om VM:n har ett servicekonto krävs också Service Account User på det kontot;
   användare från en annan organisation kan behöva OS Login External User.
   Dessa extra behörigheter delas inte ut av modulen.
4. Kontrollera att den anpassade Debian-imagen stöder OS Login och Secure Boot.
   Granska rotmodulens plan före merge: OS Login och Shielded VM är avsiktliga
   ändringar; oväntad ersättning av VM:n ska utredas. Planera för stopp/omstart.
5. Först därefter mergas ändringen så att deploy aktiverar OS Login och Shielded VM.
   Håll administratören tillgänglig tills alla fem har testat en ny inloggning:

   ```powershell
   gcloud compute ssh team5-jumphost --project=itsx25-lab --zone=europe-north2-b
   ```

   Kör `sudo whoami` på servern; svaret ska vara `root`.
   OS Login kan ge andra Linux-användarnamn och hemkataloger än tidigare.
   Kontrollera åtkomst till tidigare arbetsfiler separat.

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
