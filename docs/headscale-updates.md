# Uppdatering av Headscale och Tailscale (#89)

Tailscale på jumphosten uppdateras via Debians `unattended-upgrades` från
Tailscales stabila APT-källa. Headscale uppgraderas manuellt efter granskning,
med en färsk backup och plan för återställning. Detta gäller jumphosten;
teamets arbetsstationer omfattas inte av konfigurationsfilen.

Headscale är installerat från en fristående `.deb` och saknar paketkälla.
Blacklisten är ett extra skydd om en sådan källa skulle läggas till senare.

Konfigurationen i `config/apt/52team5-tailscale-updates` införs separat enligt
nedan. Merge och Terraform-deploy aktiverar den inte. Den måste också införas
på nytt efter en VM-ersättning, tillsammans med återställningen av Headscale.

## Ansvar och releasebevakning

Ansvarig är den tilldelade personen i [#89](https://github.com/Chas-Challenge-Team5/itsx25-infra/issues/89)
(Viktor vid upprättandet). Vid överlämning dokumenteras ny ansvarig i ärendet.
Headscales releasebevakning automatiseras av workflowen **Headscale release
monitor** (`.github/workflows/headscale-releases.yml`). Den kör dagligen cirka
07:23 UTC på main och kan startas manuellt med Run workflow på main. Schemalagda
GitHub-jobb kan fördröjas; detta är inte ett löfte om en exakt körtid.

Jobbet jämför stabila releaser med `VERSION` i `headscale/setup.py`. Först väljs
senaste patch i nuvarande minorversion, sedan senaste patch i nästa minorversion.
Prereleaser ignoreras. Saknad mellanversion eller ny majorversion kräver manuell
bedömning. Paketet för linux_amd64 laddas ned och SHA-256 kontrolleras mot
releasens `checksums.txt`; inget paket installeras eller körs av bevakningen.

Vid en ny version öppnas en PR från `automation/headscale-vVERSION` med endast
`VERSION` och `PACKAGE_SHA256` ändrade. Release notes och införandechecklista finns
i PR-texten. En öppen automations-PR lämnas för granskning innan nästa skapas.
En stängd PR för samma version återskapas inte: öppna den igen om beslutet ändras.
En avbruten publicering kan återupptas utan force-push; avvikande filändringar på
automationsbranchen skrivs inte över. Ingen automatisk merge eller installation.

Ansvarig följer upp PR:er och misslyckade/bevakningskörningar samt kontrollerar
Tailscales säkerhetsmeddelanden och uppdateringsloggar varje måndag. Slå på
GitHub-notiser för relevanta Actions-fel och PR:er. **Watch → Releases** för
Headscale är valfritt när automatiken är införd och verifierad. Ett jobb som
slutat köras skickar inte nödvändigtvis en felnotis: kontrollera även senaste
lyckade körning. I publika repo:n kan schemat inaktiveras efter 60 dagars inaktivitet.

### Aktivera och verifiera bevakningen

Workflowen börjar bevaka först när den finns på main. Den behöver `contents:
write` och `pull-requests: write`, samt repots inställning **Allow GitHub Actions
to create and approve pull requests**. Ingen egen PAT, GCP-behörighet, SSH-nyckel
eller molninloggning används. En administratör behöver kontrollera inställningen
om det vanliga kontot får 403. Bevakningen godkänner inte sina PR:er.

1. Kör lokala tester och en läsande kontroll före merge:

   ```bash
   python3 -m unittest discover -s tests/headscale_releases -v
   python3 scripts/headscale-release-monitor.py
   ```

   Läsningen använder `gh` med befintlig inloggning. `--output-dir` kan spara en
   lokal förhandsvisning i en ny katalog under `local/`, utan att ändra källfilen.
2. Efter merge: kör **Headscale release monitor** manuellt från main. Vid ny
   release ska exakt en PR skapas med två ändrade värden och rätt checksumma.
3. Kör igen: samma öppna PR ska återanvändas utan ny commit eller dubblett.
4. Kontrollera att PR-kontrollerna körs. PR:er skapade med `GITHUB_TOKEN` kan
   kräva **Approve workflows to run**; en person med skrivrättighet startar dem.
   Grön bevakning ersätter inte testerna mot den nya Headscale-binären.
5. Följ upp minst en ordinarie schemakörning och dokumentera körning/PR i #89.

Misslyckad API-läsning, saknade assets eller fel checksumma ska ge rött jobb;
tolka inte det som att ingen uppdatering behövs. Kontrollen av PR-publicering är
isolerat testad, men ett lokalt test bevisar inte repots faktiska tokenbehörighet.

- [Headscale-releaser](https://github.com/juanfont/headscale/releases)
- [Tailscales säkerhetsmeddelanden](https://tailscale.com/security-bulletins)
- [Tailscales ändringslogg](https://tailscale.com/changelog)

Vid en relevant säkerhetsrättelse ska ansvarig samma arbetsdag bedöma påverkan
och skapa ett uppgraderingsärende med målversion, ansvarig och tid för införande.
Andra nya Headscale-versioner bedöms via automations-PR:en. Dokumentera även
beslutet om en uppgradering skjuts upp. Kontrollera stödet för de Tailscale-
versioner som används; automatisk klientuppdatering ersätter inte underhåll av
Headscale-servern. Att en version är den senaste bevisar inte att den är fri från
sårbarheter.

## Förutsättningar före aktivering

1. [#85](https://github.com/Chas-Challenge-Team5/itsx25-infra/issues/85) ska vara
   införd och verifierad: raderingsskydd, minst en aktuell snapshot och ett
   dokumenterat återställningsprov. En merge av backupkoden räcker inte.
2. SSH fungerar även via tailnätet. Använd IAP med fungerande sudo vid detta
   införande, så att åtkomsten inte beror på Tailscale, och samordna med teamet.
   En Tailscale-uppdatering kan starta om `tailscaled` och kort avbryta routing/DNS.
3. Kontrollera paketkälla, timer, undantag och nuläge på `team5-jumphost`:

   ```bash
   hostname
   dpkg-query -W tailscale headscale unattended-upgrades
   apt-cache policy tailscale
   apt-cache policy
   apt-mark showhold
   apt-config dump | grep -E 'Origins-Pattern|Package-Blacklist|Package-Whitelist|APT::Periodic|Automatic-Reboot'
   systemctl is-enabled apt-daily.timer apt-daily-upgrade.timer
   systemctl is-active apt-daily.timer apt-daily-upgrade.timer
   sudo tailscale debug prefs | python3 -c 'import json,sys; p=json.load(sys.stdin); print({k:p.get(k) for k in ("AutoUpdate","AdvertiseRoutes","ControlURL")})'
   sudo headscale nodes list-routes
   ```

   Tailscale ska komma från `https://pkgs.tailscale.com/stable/debian` för
   aktuell Debian-utgåva, signerad med Tailscales separata `signed-by`-nyckel.
   Kontrollera källfilen i `/etc/apt/sources.list.d/`. Ingen `unstable`-källa får
   vara aktiverad. Origin-regeln matchar metadata och värdnamn, inte URL-sökvägen;
   den kan därför inte ensam skilja två kanaler med samma metadata.
   Inga holds, blacklist- eller whitelist-regler får hindra `tailscale`.
   Båda APT-timers ska vara enabled/active och de två periodiska värdena
   `Update-Package-Lists` och `Unattended-Upgrade` ska vara `1`.
   Stoppa införandet vid avvikelse och utred den innan aktivering.

   Annonserade rutter ska bevaras: `10.0.5.0/24` och `10.0.0.2/32`.
   Serveradressen ska fortsatt vara `https://team5.itsx25.chas-lab.dev`.

## Aktivera Tailscale-uppdatering efter godkänd backup

Efter merge: kör följande **på den egna datorn**, från en uppdaterad lokal
repokopia av main. Kopiera endast konfigurationsfilen till hemkatalogen på
jumphosten och öppna sedan SSH via IAP; någon repokopia på jumphosten behövs inte.

```bash
gcloud compute scp config/apt/52team5-tailscale-updates team5-jumphost:52team5-tailscale-updates --tunnel-through-iap --zone=europe-north2-b --project=itsx25-lab
gcloud compute ssh team5-jumphost --tunnel-through-iap --zone=europe-north2-b --project=itsx25-lab
```

Följande block körs **i SSH-sessionen på jumphosten**. Underskalet avbryter vid
fel utan att stänga den omgivande SSH-sessionen. Filen lägger till Tailscale utan
att rensa Debians befintliga origins och undantar Headscale från automatisk
uppgradering. Den ändrar inte APT:s schema eller inställningen för automatisk
VM-omstart.

```bash
(
  set -e
  test -f "$HOME/52team5-tailscale-updates"
  # Kontrollera att inget tidigare lokalt innehåll skrivs över.
  if sudo test -e /etc/apt/apt.conf.d/52team5-tailscale-updates; then
    sudo cmp /etc/apt/apt.conf.d/52team5-tailscale-updates "$HOME/52team5-tailscale-updates"
  fi
  # Vid skillnad avbryts blocket: granska filen separat innan ett nytt försök.

  # Endast unattended-upgrades ska installera Tailscale automatiskt.
  sudo tailscale set --auto-update=false
  sudo install -o root -g root -m 0644 "$HOME/52team5-tailscale-updates" /etc/apt/apt.conf.d/52team5-tailscale-updates
  sudo apt-get update
  sudo unattended-upgrade --dry-run --debug
)
```

Installationen av filen gör paketkällan tillåten redan för nästa timerkörning.
Aktivera därför inte före backupkontrollen. Dry-run ska visa Tailscale bland
tillåtna origins och Headscale i blacklist, utan att installera paket.
Granska hela resultatet för blockerade uppdateringar och konfigurationsfel.
Om samma Tailscale-version redan är installerad är noll uppgraderingar väntat;
det bevisar då inte att en verklig versionsuppgradering har genomförts.

APT:s befintliga timers är beständiga och kan ta igen missade körningar när
VM:n startar. Räkna därför inte med att uppdatering sker medan VM:n är avstängd.
Kontrollera nästa körning och utfallet efter en ordinarie körning:

```bash
systemctl list-timers apt-daily.timer apt-daily-upgrade.timer
sudo journalctl -u apt-daily-upgrade.service --since '2 days ago' --no-pager
sudo tail -n 100 /var/log/unattended-upgrades/unattended-upgrades.log
dpkg-query -W tailscale
systemctl is-active tailscaled headscale dnsmasq
```

Efter en faktisk uppdatering körs klientkontrollerna i
[Spectre-guiden](spectre-tailnet.md#verifiering): både direkt DNS-fråga till
jumphosten och klientens vanliga namnuppslag, MagicDNS, Spectre och Headscales
HTTPS-health. Kontrollera även åtkomst till primary och att båda annonserade
och godkända rutterna finns kvar. Spara version före/efter och resultat i ärendet.

### Stäng av automatiken

```bash
sudo rm -- /etc/apt/apt.conf.d/52team5-tailscale-updates
sudo tailscale set --auto-update=false
apt-config dump | grep -E 'Origins-Pattern|Package-Blacklist'
```

Detta återgår till APT-policyn före införandet; Debians uppdateringar fortsätter.
Om filen ersatte en tidigare granskad lokal variant återställs den i stället.
Kontrollera att ingen annan APT-fil tillåter Tailscales källa. Ändringen stoppar
inte en redan pågående paketinstallation och nedgraderar inte klienten.
Vid regression används IAP-åtkomst och en separat granskad återställning av
tidigare paketversion eller backup. Kör inte `tailscale logout` eller en ny
registrering som rutinåtgärd.

## Uppgradera Headscale kontrollerat

1. Läs målversionens release notes, konfigurationsändringar och klientstöd.
   Följ Headscales uppgraderingsordning: senaste patch i varje mellanliggande
   minorversion, utan att hoppa över minorversioner. Dokumentera varje steg.
2. Ändra `VERSION` och `PACKAGE_SHA256` i `headscale/setup.py` via en granskad PR.
   Hämta checksumma för rätt `linux_amd64.deb` från målreleasens publicerade
   checksummor och verifiera det hämtade paketet. Spara även tidigare verifierat
   paket för återställning. Anpassa `configuration()` och tester om versionen
   kräver det; bevara serveradress, MagicDNS, Split DNS och säkerhetsinställningar.
3. Kör `sudo python3 headscale/check.py` i isolerad Linuxmiljö. Prova därefter
   uppgradering och återställning med en kopia av aktuell databas, nyckel och
   konfiguration i en isolerad miljö utan produktionsklienter. Publicera inte
   datakopior eller nycklar. En tom testdatabas bevisar inte att migrationen av
   befintlig data fungerar.
4. Samordna ett underhållstillfälle och verifiera färsk backup enligt #85.
   Spara version, användar-/nod-ID:n, godkända rutter och konfiguration som
   jämförelseunderlag. Stoppa Headscale och ta dessutom en konsekvent kopia av
   **hela** `/etc/headscale` och `/var/lib/headscale`, inklusive Noise-nyckeln
   och eventuella SQLite WAL-/SHM-filer. Bevara ägare och filrättigheter. Förvara
   en verifierad, åtkomstskyddad kopia utanför VM:ns bootdisk innan paketet byts.
5. Kör uppgraderingen enligt den separat granskade planen. Installern `setup.py
   install` vägrar uppgradera en annan befintlig version; `reconfigure` är för
   tillåtna DNS-ändringar och kräver den pinnade versionen. Efter en versions-PR
   kan därför aktuell main inte användas för reconfigure på den gamla versionen:
   använd motsvarande äldre revision tills uppgraderingen är genomförd.
   Kringgå inte dessa skydd. Planen ska ange verifierad paketfil,
   konfigurationsdiff och hur tjänsten hålls stoppad under paketbytet. `.deb`-
   paketets installationsscript kan starta tjänsten: inspektera dem och använd
   ett verifierat tillfälligt systemd-maskeringsförfarande under bytet, som vid
   första installationen. Säkerställ att eventuell maskering tas bort även vid fel.
6. Validera målversionens konfiguration som användaren `headscale` med samma
   restriktiva umask som tjänsten (`0077`) innan normal start. `configtest` kan
   skriva nyckel/databas och migrera data; det är inte en skrivskyddad kontroll.
   Starta sedan Headscale och kontrollera health, loggar, bevarad Noise-nyckel,
   användar-/nod-ID:n, godkända rutter och klienttesterna ovan. Kontrollera att
   konfigurationen motsvarar den granskade koden och filägarskapet är korrekt.
7. Vid fel: stoppa tjänsten, bevara felunderlaget privat och återställ både
   tidigare paket och den matchande konfigurations-/datakopian från före
   migrationen. Starta inte den gamla binären mot en migrerad databas. Upprepa
   verifieringen och dokumentera resultatet. Återläsning förlorar ändringar som
   gjorts efter backupen; registrera därför inga nya noder under underhållet.

Den konkreta uppgraderingsplanen skrivs för den aktuella målversionen och ska
innehålla testade kommandon för paketbyte, maskering och återläsning. Denna rutin
gör ingen uppgradering och ändrar inte den låsta Headscale-versionen.

## Underlag för att stänga #89

- #85:s backup och återställningsprov är verifierade.
- Tailscale-policyn är installerad på jumphosten; stabil källa, timers,
  APT-policy och dry-run är kontrollerade. Minst en ordinarie körning är granskad.
  Ange uttryckligen om en faktisk versionsuppgradering ännu inte kunnat provas.
- Releasebevakningen finns på main, faktisk PR-publicering och dubblettskydd är
  verifierade, och minst en schemakörning har följts upp. Ansvarig följer upp
  PR:er och fel; installations-/återställningsrutinen är granskad.
- Aktiveringsresultat och efterkontroller finns i issue/PR. Merge eller grön CI
  innebär inte i sig att automatiken har aktiverats i drift.

## Källor

- [Unattended-upgrades: origins, tilläggsfiler, loggar och dry-run](https://github.com/mvo5/unattended-upgrades/blob/master/README.md)
- [Headscales uppgraderings- och backupguide](https://headscale.net/stable/setup/upgrade/)
- [Headscales klientstöd](https://headscale.net/stable/about/clients/)
- [Tailscales uppdateringsmetoder](https://tailscale.com/kb/1067/update)
- [GitHub Actions: PR-behörigheter](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-github-actions-settings-for-a-repository)
- [GitHub Actions: händelser från GITHUB_TOKEN](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow)
- [GitHub Actions: schemalagda körningar](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
