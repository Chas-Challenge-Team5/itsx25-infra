# Systemloggar i Cloud Logging (issue #92)

Jumphosten och primary skickar systemjournalen till Cloud Logging med Ops Agent.
Journalen innehåller bland annat sshd, sudo, headscale, tailscaled, dnsmasq och
startup-scriptet. Loggarna finns kvar om en VM ersätts eller om någon med root
rensar den lokala journalen.

| Del | Var |
|---|---|
| Rätt att skriva loggar | `bootstrap/`: `roles/logging.logWriter` för `team5-jumphost` och `team5-primary` |
| Konto på primary | `main.tf`: `team5-primary` med bara scopet `logging.write` |
| Åtkomst för OS Login | `access/`: `serviceAccountUser` på båda kontona |
| Installation | `templates/team-ops-agent.sh.tftpl`, körs av båda startup-scripten |
| Konfiguration | `templates/ops-agent-config.yaml`: bara journalen, inga mätvärden |

## Införande

Ordningen spelar roll. Primary kan inte få kontot innan det finns, och OS Login
på primary kräver `serviceAccountUser` så fort kontot är kopplat.

1. Applicera `bootstrap/` och sedan `access/` från main.
2. Merga PR:en för roten och godkänn deployen. Planen ska ändra primary på plats
   (stopp och start för kontot) och startup-scriptet på båda, utan ersättning.
3. Kör startup-scriptet på jumphosten, och på primary om den redan har startat
   innan jumphostens NAT var uppe:

   ```bash
   sudo google_metadata_script_runner startup
   systemctl is-active google-cloud-ops-agent google-cloud-ops-agent-fluent-bit
   ```

Agenten använder ungefär 100 MB minne. Paketet uppdateras inte automatiskt,
eftersom källan inte finns med i `unattended-upgrades` (#89).

## Läsa loggarna

```bash
# Inloggningar och sudo det senaste dygnet, båda maskinerna
gcloud logging read 'resource.type="gce_instance" AND logName:"journald" AND (jsonPayload.SYSLOG_IDENTIFIER="sshd-session" OR jsonPayload.SYSLOG_IDENTIFIER="sudo")' \
  --project itsx25-lab --freshness 1d --format 'table(timestamp, labels."compute.googleapis.com/resource_name", jsonPayload.MESSAGE)'

# Allt från Headscale
gcloud logging read 'resource.type="gce_instance" AND jsonPayload._SYSTEMD_UNIT="headscale.service"' \
  --project itsx25-lab --freshness 1h --format 'value(timestamp, jsonPayload.MESSAGE)'
```

I konsolen: Logging, Logs Explorer, filtrera på instansnamnet.

## Återställning

Ta bort anropet av `team-ops-agent` i startup-scripten med en PR och kör sedan
på maskinerna:

```bash
sudo systemctl disable --now google-cloud-ops-agent
sudo apt-get remove google-cloud-ops-agent
```

Kontot på primary och rollerna tas bort i `main.tf`, `access/` och `bootstrap/`,
i omvänd ordning mot införandet.
