# Audit-loggar för SSH och OS Login

Detta dokument beskriver hur vi spårar vem som loggat in på **jumphost** och **primary**, vilket kommando som används och hur loggraderna ska tolkas. Se även [os-login.md](./os-login.md) för hur OS Login är konfigurerat.

---

## Behörighet som krävs

OS Login-anropen loggas som **Data Access-loggar** (private logs). För att se dem krävs rollen:

- `roles/logging.privateLogViewer`

Enbart `roles/logging.viewer` räcker **inte**. Med den rollen returneras noll rader, och det ser ut som att loggningen är avstängd fast den inte är det. Se [#116](https://github.com/Chas-Challenge-Team5/itsx25-infra/issues/116).

---

## Kommando: vem loggade in på vilken VM

Kommandot läser `CheckPolicy`-anropen mot OS Login-API:t, filtrerat på inloggningspolicyn och på våra två VM:ar. Det ger en rad per anrop med tidpunkt, användare och instans.

```text
gcloud logging read 'protoPayload.serviceName="oslogin.googleapis.com" protoPayload.methodName=~"CheckPolicy" protoPayload.request.policy="LOGIN" protoPayload.request.instance=~"team5-(jumphost|primary)"' \
  --format="table(timestamp, protoPayload.authenticationInfo.principalEmail:label=USER, protoPayload.request.instance:label=INSTANCE)" \
  --freshness=7d --limit=50
```

Samma filter (raderna inom citattecknen) kan klistras in direkt i Log Explorer.

---

## Tolka resultatet

- Kolumnen **USER** är kontot som anslöt, **INSTANCE** är VM:en (`jumphost` eller `primary`).
- Varje rad är en policykontroll för inloggning, alltså ett inloggningsförsök som OS Login har prövat. Den bekräftar inte i sig att en SSH-session öppnades.
- Flera rader nära i tid för samma användare och instans är normalt och behöver inte betyda flera separata inloggningar.

### Om `ListLoginProfiles`

`google.cloud.oslogin.v1.OsLoginService.ListLoginProfiles` loggas också vid anslutning, men det är profilsynk och bär inte `request.instance`. Det går därför inte att filtrera per VM, och det ger ungefär två rader per anslutning. Använd det inte för att svara på "vem loggade in var".

### Får du noll rader?

1. Kontrollera att du har `roles/logging.privateLogViewer` (se ovan).
2. Öka `--freshness` om ingen har loggat in den senaste veckan.
3. Kontrollera att instansnamnen i regexen fortfarande stämmer.
