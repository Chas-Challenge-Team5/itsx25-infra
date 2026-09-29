# Backup och återställning av Headscale (#85, #129)

Backuperna innehåller kontrollplanets identitet: hela `/etc/headscale`, hela
`/var/lib/headscale` (inklusive Noise-nyckel och SQLite WAL-/SHM-filer) samt
`/var/lib/tailscale` för jumphostens nod. Publicera inte arkiv, databas, nycklar
eller råa tjänsteloggar i repo/Actions.

## Befintliga skydd

Terraform har `deletion_protection` och `prevent_destroy` för jumphosten.
`team5-jumphost-snapshots` tar dagliga snapshots av bootdisken med start 01:00 UTC,
sju dagars retention och lagring i EU. Snapshots behålls om ursprungsdisken raderas.

Snapshotfönstret är upp till fyra timmar och ligger normalt inom VM:ns planerade
stopp 00–08 Europe/Stockholm. Kontrollera att VM:n faktiskt var avstängd vid den
valda snapshoten; schemat garanterar inte en konsekvent applikationsbackup.
Inför paketbyte tas också en färsk, konsekvent backup med Headscale stoppad enligt
[uppdateringsrutinen](headscale-updates.md#uppgradera-headscale-kontrollerat).

Status READY bevisar inte att applikationen kan återställas. SQLite-integritet
är inte heller samma sak som en fungerande serverstart.

## Isolera återställningsprovet

Den 29 september 2026 satt en skrivskyddad bootdiskkopia kvar på jumphosten vid
start. EFI-fsck rapporterade `Read-only file system` och systemet gick till
emergency mode. Starten fungerade efter bortkoppling. Kopierade UUID/PARTUUID är
en stark förklaring, men exakt val av EFI-enhet har inte reproducerats.
Korruption är inte bekräftad. Fixen i #125 ändrar inte disk-ID:n.

**Anslut aldrig bootdiskkopian till produktionsjumphosten. Starta inte heller
test-VM:n från produktionssnapshoten.** Använd en ren Debian-VM i ett eget VPC
utan peering/NAT, publik IP, service account eller ingressregler och med blockerad
utgående trafik. Metadata är fortfarande åtkomlig för VM:n, men den får inga
service account-token eller produktionshemligheter via metadata.

Kopian ansluts som skrivskyddad datadisk först när den rena VM:n startat.
Montera via explicit `by-id` med `ro,noload,nodev,nosuid,noexec`, aldrig via
UUID, PARTUUID eller ett antaget `/dev/sdX`. Importera inte snapshotens fstab
eller systemd-enheter. Starta aldrig dess Tailscale-klient. Starta inte om
test-VM:n med kopian ansluten. Städning krävs även vid avbrutet prov.

## Förberedelser

Exemplen körs i Bash på en administrativ Linuxdator/Cloud Shell med `gcloud`,
Python 3 och `dpkg-deb`, från repot. Tillfälliga resurser kostar pengar och
skapas efter överenskommelse. Operatören behöver Compute-/nätverksbehörigheter
och läsåtkomst till snapshoten. Befintlig IAM ändras inte. Nätisolering skyddar
inte mot betrodda projektadministratörer med rätt att ändra VM:n/läsa diskar;
begränsa även vem som hanterar provet.

Välj en snapshot från **team5-jumphost**, kontrollera status, källa och tid:

```bash
gcloud compute snapshots list --project=itsx25-lab \
  --filter='labels.purpose=headscale-backup' --sort-by='~creationTimestamp' \
  --format='table(name,status,creationTimestamp,sourceDisk)'
```

Anteckna produktionsversion, VM-ID, disklista, UUID/PARTUUID och health som
läsande jämförelseunderlag. Välj nya lediga namn och spara skapade resursers ID:n
lokalt efter varje steg, så att även en halvfärdig körning kan städas.

```bash
set -euo pipefail
PROJECT=itsx25-lab
ZONE=europe-north2-b
REGION=europe-north2
LAB="team5-restore-129-$(date -u +%Y%m%d-%H%M%S)"
SNAP='REPLACE_WITH_VERIFIED_SNAPSHOT_NAME'
SOURCE_DISK="$LAB-source"
RUN="$PWD/local/$LAB"
umask 077
mkdir -m 700 "$RUN"
```

Hämta Headscale-paketet för **samma version som i snapshoten**, verifiera dess
SHA-256 mot granskad pin/release och packa upp med `dpkg-deb -x`. Beräkna SHA-256
för `usr/bin/headscale` och spara värdet som `BINARY_SHA`. Kör inte paketets
installationsscript. Aktuell main kan peka på en nyare version än backupen;
återställningsprovet ska inte samtidigt bli en migration.

Helpern jämför snapshotens binär med denna oberoende checksumma och avbryter vid
avvikelse. Ta alltså inte referenshashen från snapshoten själv.

## Skapa och kontrollera testmiljön

Kontrollera att resursnamnen inte redan finns. Vid kollision väljs nya namn;
återanvänd/radera inte andras resurser. Vid kommandofel: avbryt och städa det
som faktiskt skapats. Fortsätt inte genom att öppna nätet.

```bash
: "${BINARY_SHA:?Verify the package binary and set BINARY_SHA first}"
case "$LAB" in team5-restore-129-*) ;; *) exit 1 ;; esac
gcloud compute networks create "$LAB" --project="$PROJECT" --subnet-mode=custom
gcloud compute networks subnets create "$LAB" --project="$PROJECT" \
  --network="$LAB" --region="$REGION" --range=10.129.5.0/28 \
  --no-enable-private-ip-google-access
gcloud compute firewall-rules create "$LAB-deny-egress" --project="$PROJECT" \
  --network="$LAB" --direction=EGRESS --priority=0 \
  --action=DENY --rules=all --destination-ranges=0.0.0.0/0

gcloud compute instances create "$LAB" --project="$PROJECT" --zone="$ZONE" \
  --machine-type=e2-small --image-family=debian-13 --image-project=debian-cloud \
  --boot-disk-size=10GB --boot-disk-type=pd-standard \
  --subnet="$LAB" --no-address --no-service-account --no-scopes \
  --shielded-secure-boot --shielded-vtpm --shielded-integrity-monitoring \
  --labels=team=5,issue=129,purpose=restore-drill \
  --metadata="enable-oslogin=FALSE,block-project-ssh-keys=TRUE,enable-osconfig=FALSE,serial-port-enable=FALSE,restore-binary-sha256=$BINARY_SHA" \
  --metadata-from-file="startup-script=scripts/headscale-restore-startup.sh,restore-check=scripts/headscale-restore-check.py"
```

Ingen SSH-ingress eller ny IAM-tilldelning behövs. Provet startas via metadata
och resultatet läses med serial-output-API:t; interaktiv serial-inloggning är av.
Kontrollera även att ingen ärvd nätverkspolicy gör miljön mindre isolerad.

Läs loggen tills `RESTORE129_BOOT_READY` visas och anteckna upplöst Debian-image.
Kontrollera eget nät, ingen extern adress/tjänstekonto och endast ren bootdisk.
Jämför disk-ID:n med källans och avbryt vid överlapp. Scriptet väntar högst tio
minuter på datadisken.

```bash
gcloud compute instances get-serial-port-output "$LAB" --project="$PROJECT" \
  --zone="$ZONE" --port=1 > "$RUN/serial.log"
gcloud compute instances describe "$LAB" --project="$PROJECT" --zone="$ZONE" \
  --format=json > "$RUN/instance.json"
```

Först efter kontrollerna ansluts en nyskapad kopia:

```bash
gcloud compute disks create "$SOURCE_DISK" --project="$PROJECT" --zone="$ZONE" \
  --type=pd-standard --source-snapshot="$SNAP" \
  --labels=team=5,issue=129,purpose=restore-drill
gcloud compute instances attach-disk "$LAB" --project="$PROJECT" --zone="$ZONE" \
  --disk="$SOURCE_DISK" --device-name=restore-source --mode=ro
```

## Resultat och begränsningar

`headscale-restore-check.py` vägrar vanliga produktionsvärdnamn och skrivbar
källmontering. Den avvisar länkar/specialfiler och oväntade databas-/nyckel-/
policysökvägar. Katalogerna kopieras privat och filerna jämförs. SQLite får
hantera WAL på **kopian**, aldrig på den monterade snapshoten.

Den verifierade binären kör som en oprivilegierad användare i egna nätverks-/
PID-namnrymder. Endast loopback finns. Anrop till labbnät, tailnät, metadata och
internet måste misslyckas. Inga paket eller tjänster installeras.
Identitet, DNS och policy bevaras; lokala sökvägar/lyssningsadresser och DERP-karta
anpassas för provet. Externa DERP-hämtningar och versionskontroll stängs av.
Provet verifierar därför inte verklig klientanslutning, DNS/routing eller DERP.
Tailscale-state kopieras och jämförs, men klienten startas aldrig.

Kräv SQLite-integritet, HTTP 200/pass, fungerande API-läsning av användare/noder/
rutter samt oförändrade användar-/nod-ID:n, nycklar och godkända rutter. Ett andra
prov avbryter avsiktligt efter health och verifierar städning. Privata arbetskopior
tas bort och barnprocesser avslutas med PID-namnrymden. Kräv alla markörer:

```text
RESTORE129_NORMAL_PASS
RESTORE129_ABORT_PASS
RESTORE129_ALL_PASS
```

Spara bara aggregerade resultat för publicering. Saknad markör/felkod betyder
misslyckat prov. Ändra inte produktionen för att få det att passera. Om maskinen
avbryts hårt kan filer ligga kvar trots normal `finally`-städning; molnresurserna
ska därför alltid tas bort.

## Städning även efter avbrott

Kontrollera exakta namn och sparade ID:n, nät, etiketter `issue=129,purpose=restore-drill`,
diskens sourceSnapshot och users. Avbryt vid avvikelse. Radera inte produktion,
snapshots, den äldre `headscale-117-restore-test` eller andras resurser.

Vid normalt slut är datadisken avmonterad och testprocesserna avslutade. Vid ett
hängt test kan den isolerade VM:n raderas. Den rena bootdisken ska vara auto-delete;
datadisken bevaras tills ingen VM använder den.

```bash
gcloud compute instances delete "$LAB" --project="$PROJECT" --zone="$ZONE" --keep-disks=data
# Verifiera tom users-lista innan källdisken tas bort.
gcloud compute disks describe "$SOURCE_DISK" --project="$PROJECT" --zone="$ZONE" --format=json
gcloud compute disks delete "$SOURCE_DISK" --project="$PROJECT" --zone="$ZONE"
gcloud compute firewall-rules delete "$LAB-deny-egress" --project="$PROJECT"
gcloud compute networks subnets delete "$LAB" --project="$PROJECT" --region="$REGION"
gcloud compute networks delete "$LAB" --project="$PROJECT"
```

Verifiera att VM, båda diskarna, brandvägg, subnät och nät är borta. Kontrollera
produktions-VM:ns disklista/status och health igen. Ett lyckat delete-kommando
räcker inte som efterkontroll. Vid städproblem: dokumentera resurser/ansvarig och
behåll isoleringen tills de tas bort.

## Verklig produktionsåterställning

Provet ger underlag men inget tillstånd att byta VM eller skriva över data.
Skriv en målversions-/snapshot-specifik plan, samordna underhåll och verifiera
IAP-reservåtkomst. Återskapa via en granskad Terraform-plan; grundimagen kräver
signerad kärnförberedelse innan Secure Boot enligt #63:s rutin.

Håll Headscale/Tailscale maskerade/stoppade även under paketinstallation; paket-
script kan starta dem. Exportera endast nödvändiga filer från den isolerade
miljön via godkänd krypterad överföring. Bevara ägare/rättigheter, konfiguration,
policy, Noise-nyckel och alla databasfiler. Koppla inte hela bootdiskkopian till
produktion och importera inte dess fstab. Verifiera arkivinnehåll och checksumma.
Nedgradering kräver tidigare paket **och dess matchande data-/konfigurationsbackup**.

Starta först när gamla produktionsinstansen är förhindrad att återansluta.
Verifiera health, identiteter, båda godkända rutter, DNS, Spectre, appen,
klientåtkomst och IAP. Ange vilka ändringar efter snapshoten som gått förlorade
och måste återskapas. En SQLite-läsning ensam bevisar inte återställd produktion.

## Källor

- [Google Cloud: återställ disk från snapshot](https://docs.cloud.google.com/compute/docs/disks/restore-snapshot)
- [Google Cloud: säker hantering av snapshots](https://docs.cloud.google.com/compute/docs/disks/snapshot-best-practices)
- [Headscale: uppgradering och backup](https://headscale.net/stable/setup/upgrade/)
