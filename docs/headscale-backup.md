# Backup och återställning av Headscale (issue #85)

Headscale kör på `team5-jumphost` och all data ligger på jumphostens bootdisk:

- `/var/lib/headscale/db.sqlite` med användare, noder och godkända rutter
- `/var/lib/headscale/noise_private.key`, serverns nyckel. Byts den måste alla
  klienter loggas ut och registreras om.
- `/etc/headscale/config.yaml`
- `/var/lib/tailscale/`, jumphostens egen nod i tailnätet

## Skydd

- `deletion_protection = true` på jumphosten. GCP vägrar radera instansen, även
  från konsolen eller gcloud, tills skyddet tas bort.
- `prevent_destroy` på jumphosten. En plan som vill ersätta eller radera
  instansen avbryts redan i CI, innan någon kan godkänna den.
- Resource policy `team5-jumphost-snapshots` tar en snapshot av disken varje dag
  kl 03:00 UTC och sparar den i 7 dagar i EU. Snapshots finns kvar även om
  disken raderas.

03:00 UTC ligger inom `team5-daily-schedule`, som stänger av VM:n mellan 00:00
och 08:00 svensk tid. Headscale är då nedstängd och har skrivit klart sin
WAL-fil, så databasen i snapshoten är hel.

Ska jumphosten ersättas med avsikt tas `prevent_destroy` bort i en egen PR, och
skyddet stängs av precis före apply:

```bash
gcloud compute instances update team5-jumphost --zone europe-north2-b --no-deletion-protection
```

## Hitta senaste snapshot

```bash
gcloud compute snapshots list \
  --filter="labels.purpose=headscale-backup" \
  --sort-by=~creationTimestamp \
  --format="table(name,creationTimestamp,diskSizeGb,storageBytes)"
```

## Provåterställning (utan att röra tailnätet)

Görs på en separat disk som monteras skrivskyddat på jumphosten. Disken
innehåller Headscales privata nyckel, så den kopplas inte till någon annan VM.

```bash
SNAP=<namn från listan ovan>
gcloud compute disks create team5-jumphost-restore-test \
  --zone europe-north2-b --source-snapshot "$SNAP"
gcloud compute instances attach-disk team5-jumphost \
  --zone europe-north2-b --disk team5-jumphost-restore-test \
  --device-name restore-test --mode ro
```

På jumphosten:

```bash
sudo mkdir -p /mnt/restore-test
sudo mount -o ro,noload /dev/disk/by-id/google-restore-test-part1 /mnt/restore-test
sudo ls -l /mnt/restore-test/var/lib/headscale
# Ingen utskrift betyder att nyckeln är samma som den som används nu.
sudo cmp /mnt/restore-test/var/lib/headscale/noise_private.key /var/lib/headscale/noise_private.key
sudo python3 -c "import sqlite3; db = sqlite3.connect('file:/mnt/restore-test/var/lib/headscale/db.sqlite?immutable=1', uri=True); print(*db.execute('select id, given_name from nodes'), sep='\n')"
sudo headscale nodes list
sudo umount /mnt/restore-test
```

Noderna i snapshoten ska stämma med `headscale nodes list`, förutom noder som
registrerats efter att snapshoten togs. Städa sedan bort disken:

```bash
gcloud compute instances detach-disk team5-jumphost --zone europe-north2-b --disk team5-jumphost-restore-test
gcloud compute disks delete team5-jumphost-restore-test --zone europe-north2-b
```

## Återställning efter att jumphosten har ersatts

Terraform skapar jumphosten med en ny disk från labbimagen. Datan kopieras
sedan in från snapshoten, så att instansen fortfarande hanteras av Terraform.

1. Låt deployen skapa den nya jumphosten. Kör `scripts/prepare-secure-boot.sh`
   innan Secure Boot slås på, eftersom labbimagen har en osignerad kärna (#63).
2. Skapa, koppla in och montera en disk från den senaste snapshoten precis som
   i provåterställningen.
3. Installera Tailscale och Headscale med den sparade konfigurationen:

   ```bash
   sudo cp /mnt/restore-test/etc/headscale/config.yaml /root/headscale-config.yaml
   sudo python3 headscale/setup.py install --config /root/headscale-config.yaml
   ```

   `setup.py` vägrar installera när `/var/lib/headscale` redan har innehåll, så
   datan kopieras in först efter installationen.
4. Stoppa tjänsterna, ersätt datan och starta igen:

   ```bash
   sudo systemctl stop headscale tailscaled
   for dir in headscale tailscale; do
     sudo find /var/lib/$dir -mindepth 1 -delete
     sudo cp -a /mnt/restore-test/var/lib/$dir/. /var/lib/$dir/
   done
   sudo systemctl start headscale tailscaled
   ```

5. Kontrollera med `sudo headscale nodes list` och `sudo headscale nodes list-routes`
   att alla noder finns och att `10.0.5.0/24` är godkänd. Klienterna ansluter
   igen av sig själva eftersom servernyckeln är densamma.
6. Avmontera, koppla bort och radera återställningsdisken som ovan.
