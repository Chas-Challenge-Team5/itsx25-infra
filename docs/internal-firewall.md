# Intern brandvägg och NAT (#31)

`allow_ssh` behåller befintliga `ssh_source_ranges` medan IAP-ändringen i #35 är pausad. `allow_internal` tillåter TCP 22 från teamets och instruktörens nät, endast till jumphosten. ICMP och generell UDP-åtkomst tas bort.

`allow_forwarded_nat` tillåter TCP 80/443 från teamets subnet till jumphostens nätverksgränssnitt. GCP-regeln gäller både trafik till servern och trafik som routas genom den. Därför installerar startup-scriptet kompletterande iptables-filter:

- `TEAM-NAT-INPUT` blockerar nya TCP-anslutningar från teamets subnet till jumphostens egna portar 80/443. Befintlig svarstrafik och övrig trafik lämnas till övriga värdregler och GCP-brandväggen. Det är inte en komplett fristående INPUT-policy.
- `TEAM-NAT-FORWARD` tillåter etablerad/relaterad trafik och nya TCP-anslutningar från teamets subnet till 80/443. Övrig vidarebefordrad trafik blockeras. Detta omfattar även eventuell Tailnet-trafik på andra portar.
- MASQUERADE behålls. Upprepad körning lägger inte till fler identiska hopp eller MASQUERADE-regler. Eventuella äldre dubbletter rensas inte automatiskt.

Filtret laddas av `team-nat-firewall.service` före `network-pre.target` vid efterföljande uppstarter. Startup-scriptet installerar och startar tjänsten. Inga befintliga globala filterkedjor töms; endast de två egna kedjorna ersätts.

## Införande och verifiering

TCP 80/443 är ett preliminärt behov för interna klienter, inte en verifierad komplett lista. Ingen intern klient har använts för funktionstest ännu. DNS via GCP:s metadata kräver inte en intern DNS-öppning; extern DNS och andra protokoll behöver separat behovsprövning.

**Gör ett stegvis införande.** Att uppdatera metadata garanterar inte att startup-scriptet körs direkt på en redan startad VM. Terraform kan dessutom skapa NAT-brandväggsregeln innan värdfiltret är aktivt. `depends_on` på VM-resursen bevisar inte att startup-scriptet har körts klart.

1. Granska Terraform-planen. Behåll nuvarande SSH-väg och en återställningsmöjlighet.
2. Installera först den nya metadata/startup-konfigurationen och kör startup-scriptet kontrollerat på jumphosten, medan den befintliga internregeln fortfarande gäller. En administratör kan använda en separat, granskad plan för VM-resursen som ett tillfälligt införandesteg.
3. Verifiera `systemctl status team-nat-firewall`, `iptables -S TEAM-NAT-INPUT`, `iptables -S TEAM-NAT-FORWARD`, kedjehoppen och NAT-regeln. Kontrollera ny SSH-inloggning och Firefox-proxy.
4. Applicera därefter den fullständiga granskade planen för GCP-reglerna. Öppna inte de nya transitportarna utan att värdfiltret är aktivt.
5. Testa från en intern klient utan extern IP och med taggen `no-external-ip`: avsedd HTTP/HTTPS genom NAT ska fungera, men nya anslutningar till jumphostens egna 80/443 ska blockeras. Kontrollera andra portar med en känd lyssnande testtjänst så att ett misslyckande inte bara beror på avsaknad av tjänst. Testa också instruktörens SSH och att oavsedd vidarebefordrad trafik blockeras.
6. Verifiera efter omstart att tjänsten, kedjehoppen och NAT fungerar. Kontrollera att upprepad körning inte skapar dubbletter och att en ny Terraform-plan inte återinför den breda regeln.

Funktionstester och plan mot GCP återstår innan #31 kan stängas. Inga liveändringar görs av att dessa filer redigeras lokalt.
