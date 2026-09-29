# Issue #117 – Headscale 0.29.3 → 0.29.4

## Omfattning

Validering och plan för produktionsuppgradering av Headscale till version 0.29.4.

Relaterade ärenden:
- Issue #117
- PR #114 – fastställd Headscale-version och SHA256
- Issue #85 – backup av Headscale

## Genomförd validering

### Paketuppgradering

Testmiljö: isolerad Debian 13 Docker-container med `--network none`.

- Headscale 0.29.3 installerades utan problem.
- Paketuppgraderingen till 0.29.4 genomfördes.
- `dpkg-query` rapporterade `install ok installed`.
- Headscale-binären rapporterade version `v0.29.4`.

### Återställning av snapshot

Den senast tillgängliga backupsnapshoten för Headscale återställdes till en separat disk på 20 GB och anslöts till jumphosten i READ_ONLY-läge.

Det återställda filsystemet monterades med `ro,noload`.

Snapshoten innehöll:
- Headscale-konfiguration och policy
- SQLite-databas
- Privat Noise-nyckel

SQLite-kontrollen `integrity_check` returnerade `ok`.

### Isolerad databasvalidering

En kopia av den återställda datan testades med Headscale 0.29.4. Originalkopian bevarades separat för rollback.

`configtest` med Headscale 0.29.4 genomfördes utan rapporterade fel.

Databasjämförelse:

| Kontroll | Original | Migrationstest | Rollbacktest |
|---|---|---|---|
| SQLite-integritet | OK | OK | OK |
| Användare | 7 | 7 | 7 |
| Noder | 6 | 6 | 6 |
| Användar-ID | 1–7 | 1–7 | 1–7 |
| Nod-ID | 1–6 | 1–6 | 1–6 |

### Validering av rollback

- Headscale 0.29.3 återinstallerades i testcontainern.
- En separat rollbackkopia skapades från den ursprungliga återställda datan.
- Version 0.29.3 klarade `configtest` mot rollbackkopian.
- Den migrerade databasen öppnades aldrig med den äldre binären.

Ingen Headscale-server startades under testerna och inga testklienter anslöts till produktionsmiljöns tailnet.

Tester­na verifierar paketinstallation, databasintegritet och konfigurationsinläsning, men inte aktiv klientanslutning.

## Förutsättningar inför produktionsuppgraderingen

- Bekräfta att samtliga Tailscale-klienter kör version 1.80.0 eller senare.
- Kom överens med teamet om ett underhållsfönster.
- Förhindra registrering av nya noder under underhållet.
- Verifiera att IAP-åtkomst fungerar oberoende av Tailscale.
- Fastställ ansvar för backup och rollback.
- Låt PR #114 förbli omergad fram till underhållsfönstret.

### Varför PR #114 måste mergas under samma underhållsfönster

Funktionen `reconfigure` i `headscale/setup.py` kräver att den installerade Headscale-versionen överensstämmer med `VERSION` i koden.

PR #114 ändrar `VERSION` till 0.29.4. Om PR:en mergas innan produktionsservern har uppgraderats från 0.29.3 uppstår en versionsskillnad. Det innebär att DNS-konfigurationen inte kan ändras via `reconfigure` från main förrän servern har uppgraderats.

Därför ska PR #114 inte mergas i förväg, utan samordnas med paketuppgraderingen under samma underhållsfönster.

## Plan för produktionsuppgradering

1. Dokumentera aktuell tjänstestatus, användare, noder, routes och DNS-konfiguration.
2. Stoppa Headscale och skapa en konsekvent, fullständig backup av `/etc/headscale` och `/var/lib/headscale` utanför bootdisken.
3. Bevara ägarskap, filbehörigheter, databasfiler och Noise-nyckeln.
4. Maskera tjänsten för att förhindra automatisk omstart under paketinstallationen.
5. Installera det verifierade Headscale-paketet version 0.29.4.
6. Samordna merge av PR #114 under samma underhållsfönster.
7. Avmaskera och starta Headscale efter kontroll av paket och konfiguration.
8. Verifiera tjänstestatus, loggar, användare, nod-ID:n, routes, DNS och klientanslutningar.

## Rollback

Om uppgraderingen misslyckas ska Headscale stoppas och den fullständiga backupen från före uppgraderingen återställas tillsammans med Headscale 0.29.3.

Kör aldrig den äldre binären mot en databas som redan har migrerats av version 0.29.4. Avinstallera inte paketet med `purge`.

Ändringar som gjorts efter backupen kan gå förlorade vid rollback.

## Status

Den isolerade valideringen är genomförd.

Produktionsuppgraderingen och efterföljande verifieringar återstår.

Issue #117 ska förbli öppet tills produktionsuppgraderingen har genomförts och verifierats.
