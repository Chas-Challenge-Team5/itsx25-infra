# Uppdatering av Headscale och Tailscale (#89)

Tailscale på jumphosten uppdateras via Debians `unattended-upgrades` från
Tailscales stabila APT-källa. Headscale uppgraderas manuellt efter granskning,
med en färsk backup och plan för återställning. Detta gäller jumphosten;
teamets arbetsstationer omfattas inte av konfigurationsfilen.

Konfigurationen i `config/apt/52team5-tailscale-updates` införs separat enligt
nedan. Merge och Terraform-deploy aktiverar den inte. Den måste också införas
på nytt efter en VM-ersättning, tillsammans med återställningen av Headscale.

## Ansvar och releasebevakning

Ansvarig är den tilldelade personen i [#89](https://github.com/Chas-Challenge-Team5/itsx25-infra/issues/89)
(Viktor vid upprättandet). Vid överlämning dokumenteras ny ansvarig i ärendet.
Ansvarig kontrollerar varje måndag Headscales releaser och Tailscales
säkerhetsmeddelanden samt loggarna för automatiska uppdateringar. Aktivera även
GitHub **Watch → Custom → Releases** för `juanfont/headscale` på det egna kontot.
Prenumerationen måste bekräftas av ansvarig; dokumentet aktiverar den inte.

- [Headscale-releaser](https://github.com/juanfont/headscale/releases)
- [Tailscales säkerhetsmeddelanden](https://tailscale.com/security-bulletins)
- [Tailscales ändringslogg](https://tailscale.com/changelog)

Vid en relevant säkerhetsrättelse ska ansvarig samma arbetsdag bedöma påverkan
och skapa ett uppgraderingsärende med målversion, ansvarig och tid för införande.
Andra nya Headscale-versioner bedöms vid veckokontrollen. Dokumentera även
beslutet om en uppgradering skjuts upp. Kontrollera stödet för de Tailscale-
versioner som används; automatisk klientuppdatering ersätter inte underhåll av
Headscale-servern. Att en version är den senaste bevisar inte att den är fri från
sårbarheter.

## Förutsättningar före aktivering

1. [#85](https://github.com/Chas-Challenge-Team5/itsx25-infra/issues/85) ska vara
   införd och verifierad: raderingsskydd, minst en aktuell snapshot och ett
   dokumenterat återställningsprov. En merge av backupkoden räcker inte.
2. Använd SSH via IAP med fungerande sudo och samordna med teamet. En
   Tailscale-uppdatering kan starta om `tailscaled` och kort avbryta routing/DNS.
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

Kopiera den granskade konfigurationsfilen från main till jumphosten. Följande
kommandon körs där, från repokopian. Filen lägger till Tailscale utan att rensa
Debians befintliga origins och undantar Headscale från automatisk uppgradering.
Den ändrar inte APT:s schema eller inställningen för automatisk VM-omstart.

```bash
set -e
# Kontrollera att inget tidigare lokalt innehåll skrivs över.
if sudo test -e /etc/apt/apt.conf.d/52team5-tailscale-updates; then
  sudo cmp /etc/apt/apt.conf.d/52team5-tailscale-updates config/apt/52team5-tailscale-updates
fi
# Vid skillnad avbryts blocket: granska filen separat innan ett nytt försök.

# Endast unattended-upgrades ska installera Tailscale automatiskt.
sudo tailscale set --auto-update=false
sudo install -o root -g root -m 0644 config/apt/52team5-tailscale-updates /etc/apt/apt.conf.d/52team5-tailscale-updates
sudo apt-get update
sudo unattended-upgrade --dry-run --debug
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
   install` vägrar uppgradera en annan befintlig version; `reconfigure` är bara
   för Split DNS. Kringgå inte dessa skydd. Planen ska ange verifierad paketfil,
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
- Releasebevakningen är bekräftad av ansvarig och denna rutin är granskad.
- Aktiveringsresultat och efterkontroller finns i issue/PR. Merge eller grön CI
  innebär inte i sig att automatiken har aktiverats i drift.

## Källor

- [Unattended-upgrades: origins, tilläggsfiler, loggar och dry-run](https://github.com/mvo5/unattended-upgrades/blob/master/README.md)
- [Headscales uppgraderings- och backupguide](https://headscale.net/stable/setup/upgrade/)
- [Headscales klientstöd](https://headscale.net/stable/about/clients/)
- [Tailscales uppdateringsmetoder](https://tailscale.com/kb/1067/update)
