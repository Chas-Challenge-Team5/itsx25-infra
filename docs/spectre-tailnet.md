# Spectre via tailnätet (issue #51)

Klienter i tailnätet når Spectre (`10.0.0.2`) och slår upp namn i
`itsx25.chas-lab.dev` genom jumphosten.

| Del | Var den finns | Vad den gör |
|---|---|---|
| Rutt `10.0.0.2/32` | Jumphostens Tailscale-inställningar och godkännande i Headscale | Skickar trafik till Spectre genom jumphosten |
| Masquerade | `templates/team-nat-firewall.sh.tftpl` | Trafik från `100.64.0.0/10` till Spectre får jumphostens adress, eftersom Spectre saknar returväg till tailnätet |
| dnsmasq | Startup-scriptet i `main.tf` | Lyssnar bara på `tailscale0` och skickar bara labbzonen vidare till GCP:s DNS (`169.254.169.254`). Andra namn besvaras inte. |
| Split DNS | `headscale/setup.py`, `configuration()` | Klienterna skickar frågor om `itsx25.chas-lab.dev` till jumphosten (`100.64.0.2`). MagicDNS (`team5.arpa`) påverkas inte. |

Spectres adress kommer från `headscale_proxy_cidr`, eftersom Spectre också är
Headscale-proxyn. Labbzonen kommer från `lab_dns_zone`.

Tailscales annonserade rutter sparas i tailscaled och finns kvar efter omstart,
så de ligger inte i startup-scriptet. `tailscale set --advertise-routes` ersätter
hela listan, så båda rutterna måste alltid anges tillsammans.

## Införande

Görs i den här ordningen. Split DNS slås på sist, annars skickas frågor om
labbzonen till en jumphost som ännu inte svarar.

1. Godkänn deployen efter merge. Planen ska bara ändra jumphostens
   startup-script, utan omstart.
2. Kör det nya startup-scriptet på jumphosten, så att hjälpscriptet och dnsmasq
   installeras:

   ```bash
   sudo google_metadata_script_runner startup
   sudo iptables -t nat -S POSTROUTING
   systemctl is-active dnsmasq
   sudo ss -lnup 'sport = :53'
   ```

   `POSTROUTING` ska ha regeln `-s 100.64.0.0/10 -d 10.0.0.2/32 -o ens4 -j MASQUERADE`
   och inte längre `-d 10.0.0.2/32 -j MASQUERADE`. dnsmasq ska lyssna på
   `100.64.0.2:53`.
3. Kontrollera rutterna och godkänn dem. `approve-routes` ersätter också hela
   listan:

   ```bash
   sudo tailscale debug prefs | grep -A3 AdvertiseRoutes
   # Om 10.0.0.2/32 saknas:
   sudo tailscale set --advertise-routes=10.0.5.0/24,10.0.0.2/32
   sudo headscale nodes approve-routes --identifier 2 --routes 10.0.5.0/24,10.0.0.2/32
   sudo headscale nodes list-routes
   ```

4. Slå på Split DNS. Kopiera `headscale/setup.py` från main till jumphosten och kör:

   ```bash
   python3 setup.py render \
     --server-url https://team5.itsx25.chas-lab.dev \
     --base-domain team5.arpa \
     --split-dns-resolver 100.64.0.2 \
     --output ~/headscale-config-51.json
   sudo python3 setup.py reconfigure --config ~/headscale-config-51.json
   ```

   `reconfigure` avbryter om något annat än Split DNS skiljer sig från den
   nuvarande filen. Den sparar den gamla filen som
   `/etc/headscale/config.yaml.<tid>.bak`, provar den nya som tjänstens
   användare och startar om Headscale. Går omstarten fel läggs den gamla filen
   tillbaka. Klienterna tappar inte sina anslutningar under omstarten.

## Verifiering

Från en ansluten klient som inte är jumphosten. På Linux krävs
`tailscale set --accept-routes`. På Windows och macOS tas rutter emot som standard.

```bash
ping 10.0.0.2
nslookup spectre.itsx25.chas-lab.dev 100.64.0.2
ping spectre.itsx25.chas-lab.dev
ping team5-jumphost.team5.arpa
curl -fsS https://team5.itsx25.chas-lab.dev/health
```

- `spectre.itsx25.chas-lab.dev` ska ge `10.0.0.2`.
- `nslookup example.com 100.64.0.2` ska avvisas (`REFUSED`), eftersom jumphosten
  bara svarar för labbzonen.
- MagicDNS och Headscales HTTPS-adress ska fortsätta fungera.

## Åtkomstpolicy (#52)

När ACL-policyn införs måste den tillåta UDP och TCP 53 till `100.64.0.2` och
trafiken till `10.0.0.2/32`, annars slutar Split DNS och Spectre att fungera.

## Återställning

```bash
# Split DNS
sudo cp /etc/headscale/config.yaml.<tid>.bak /etc/headscale/config.yaml
sudo systemctl restart headscale
# Rutten till Spectre
sudo headscale nodes approve-routes --identifier 2 --routes 10.0.5.0/24
sudo tailscale set --advertise-routes=10.0.5.0/24
# dnsmasq
sudo systemctl disable --now dnsmasq
```

Masquerade-regeln och dnsmasq-konfigurationen tas bort från main med en PR.
Hjälpscriptet tar inte bort regler som inte längre finns i mallen, så en borttagen
regel tas bort för hand med `iptables -t nat -D POSTROUTING ...`.
