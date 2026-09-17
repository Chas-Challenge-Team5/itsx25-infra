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
  med start 01:00 UTC och sparar den i 7 dagar i EU. Snapshots finns kvar även om
  disken raderas.

GCP tar snapshoten någon gång inom fyra timmar från starttiden, alltså mellan
01:00 och 05:00 UTC. `team5-daily-schedule` stänger av VM:n mellan 00:00 och
08:00 svensk tid, vilket är 22:00 till 06:00 UTC på sommaren och 23:00 till
07:00 UTC på vintern. Hela fönstret ligger därför inom stoppet. Headscale är
nedstängd och har skrivit klart sin WAL-fil, så databasen i snapshoten är hel.

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
# Kopiera databasen med WAL-filen. En manuell snapshot tas medan Headscale kör,
# och då ligger de senaste ändringarna i db.sqlite-wal. Globben måste expanderas
# av root, eftersom katalogen inte är läsbar för andra.
TMP=$(sudo mktemp -d)
sudo sh -c "cp -a /mnt/restore-test/var/lib/headscale/db.sqlite* $TMP/"
sudo python3 -c "import sqlite3; db = sqlite3.connect('$TMP/db.sqlite'); print(*db.execute('select id, given_name from nodes order by id'), sep='\n'); print('integrity', db.execute('pragma integrity_check').fetchone()[0])"
sudo rm -rf "$TMP"
sudo headscale nodes list
sudo umount /mnt/restore-test
```

Noderna i snapshoten ska stämma med `headscale nodes list`, förutom noder som
registrerats efter att snapshoten togs, och `integrity` ska vara `ok`. Städa sedan bort disken:

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
3. Installera Tailscale och Headscale med den sparade konfigurationen. `setup.py`
   och `policy.hujson` måste ligga bredvid varandra på jumphosten:

   ```bash
   sudo cp headscale/setup.py /root/setup.py
   sudo cp headscale/policy.hujson /root/policy.hujson
   sudo cp /mnt/restore-test/etc/headscale/config.yaml /root/headscale-config.yaml
   sudo python3 /root/setup.py install --config /root/headscale-config.yaml
   ```

   `setup.py` installerar också policyn till `/etc/headscale/policy.hujson` och
   vägrar om en befintlig policy skiljer sig från repots version. Den vägrar också
   installera när `/var/lib/headscale` redan har innehåll, så datan kopieras in
   först efter installationen.
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
