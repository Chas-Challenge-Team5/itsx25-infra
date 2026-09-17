# Intern brandvägg och NAT

Ändringen begränsar tjänsterna som kan nås på jumphosten, samtidigt som interna klienter kan använda HTTP/HTTPS genom dess NAT. Regeln för Headscale samordnas med #48.

| Trafik | Källa | Tillåtelse |
|---|---|---|
| SSH till jumphost och primary | Teamets subnät och instruktörsnätet | TCP 22 |
| Testtjänst och ping till primary | Teamets subnät samt `100.64.0.0/10` | TCP 8000 och ICMP |
| SSH via IAP | `35.235.240.0/20` | TCP 22, befintlig separat regel |
| Spectres proxy till Headscale | `headscale_proxy_cidr`, normalt `10.0.0.2/32` | TCP 8080 |
| Trafik genom NAT | Teamets subnät | TCP 80/443 |
| Vidarebefordran via `tailscale0` | Tailscale-gränssnittet, in eller ut | Lämnas vidare till Tailscales egna regler och åtkomstpolicy |
| Tailnet till Spectre | `100.64.0.0/10` till `headscale_proxy_cidr` | MASQUERADE på jumphostens utgående gränssnitt (#51) |

Internregeln behåller SSH till både `jumphost` och `primary`. En separat regel tillåter TCP 8000 och ICMP enbart till `primary`, för #50. Källorna täcker både Tailscales standard-SNAT (jumphostens interna IP) och `--snat-subnet-routes=false` (klientens Tailscale-IP). Den befintliga returvägen `tailnet_via_jumphost` behålls. Regeln startar ingen primary-maskin; det görs i #50. Den breda UDP-öppningen tas bort, och andra portar tillåts inte generellt. Direkt SSH från internet återinförs inte; IAP och instruktörens separata SSH-regler behålls. OS Login och IAM ändras inte av #31.

GCP:s NAT-ingressregel kan även släppa fram trafik till jumphostens egna 80/443. Därför krävs värdfiltret i `templates/team-nat-firewall.sh.tftpl` innan de nya GCP-reglerna införs:

- `TEAM-NAT-INPUT` blockerar nya anslutningar från teamets subnät till jumphostens egna 80/443. Etablerad svarstrafik behålls. Övrig lokal trafik avgörs av GCP och befintliga värdregler; detta är ingen fristående fullständig INPUT-policy.
- `TEAM-NAT-FORWARD` lämnar trafik in eller ut via `tailscale0` vidare med `RETURN`, före vanliga regler för svarstrafik och NAT. För övrig trafik tillåts svarstrafik samt nya HTTP/HTTPS-anslutningar från teamets subnät; annan vidarebefordran blockeras.
- NAT-portarna definieras gemensamt i `local.nat_tcp_ports` för GCP-regeln och värdfiltret.

`team-nat-firewall.service` laddar filtret före `network-pre.target`. Startup-scriptet installerar hjälpscriptet och tjänsten, startar filtret och förbereder sedan MASQUERADE och IP-forwarding. Hjälpscriptet väntar på iptables-låset och tömmer bara sina egna kedjor. Upprepad körning lägger inte till fler identiska hopp eller NAT-regler. Äldre dubbletter från tidigare konfiguration rensas inte automatiskt.

Undantaget för `tailscale0` är avsiktligt ett `RETURN`, inte ett slutligt `ACCEPT`: Tailscales kedja måste fortfarande kunna märka paketen för subnet-SNAT och tillämpa sina regler. Det gäller även etablerade paket. Lösningen förutsätter normal Tailscale-hantering av brandväggen (`--netfilter-mode=on`); `off` eller `nodivert` kräver en separat granskad integration. Undantaget bygger på gränssnittet, inte enbart på en källadress i `100.64.0.0/10`. Det öppnar alltså inte vanlig LAN-trafik med en sådan källadress. Tailnet-åtkomstpolicyn förvaltas i #52. Se [Tailscales netfilter-lägen](https://tailscale.com/docs/reference/netfilter-modes) och [implementationen av märkning och SNAT](https://github.com/tailscale/tailscale/blob/main/util/linuxfw/iptables_runner.go).

TCP 80/443 är den vanliga internet-NAT som denna lösning stödjer. Extern DNS och QUIC/UDP för sådana klienter behöver separata beslut. GCP:s metadata-DNS kräver ingen generell intern UDP-öppning. Rutter, godkännanden och Split DNS hanteras i #49–51 och beskrivs i [spectre-tailnet.md](spectre-tailnet.md). Sedan #51 lägger hjälpscriptet även till en masquerade-regel för trafik från tailnätet till Spectre, eftersom Spectre saknar returväg till `100.64.0.0/10`. Regeln gäller bara den källan och den destinationen, så primary ser fortfarande klientens tailnet-adress. En tidigare handinlagd regel utan källa och gränssnitt (`-d 10.0.0.2/32 -j MASQUERADE`) tas bort när hjälpscriptet körs. Tillåten TCP 8080 bevisar inte att Headscale eller den publika proxyn fungerar.

## Kontroller utan GCP

```bash
terraform init -backend=false -lockfile=readonly
terraform validate
terraform test
sudo env "PATH=$PATH" python3 tests/network_firewall.py
```

Terraform-testerna använder mockad provider och kontrollerar tjänsteportar, källnät, måltaggar, IAP/instruktörsregler och avvisning av en bred eller ogiltig proxykälla.

Nätverkstesterna kräver Linux, root, Terraform, iproute2, iptables och ping. De renderar det riktiga hjälpscriptet med Terraform och skapar fyra isolerade nätverksnamnrymder för klient/primary, router, destination/Spectre och en simulerad tailnet-klient. De verifierar NAT-adressen och svarstrafik, blockerade portar mot kända lyssnare, otillåtet källnät, omladdning med kvarvarande anslutning, frånvaro av nya dubbletter samt selektiv återställning. Namnrymder och testprocesser städas bort. Värdens vanliga nätverksnamnrymd får inga brandväggs- eller routingändringar.

Tailscale-proven modellerar gränssnittet `tailscale0` och iptables-kedjorna för märkning, SNAT och stateful filtering. Ping och TCP 8000 till primary samt ping och HTTPS till Spectre provas med Tailscales kedja både före och efter vårt filter, med och utan subnet-SNAT samt efter omladdning. Spectres masquerade kommer från det renderade hjälpscriptet. Proven kontrollerar att Spectre ser jumphostens adress medan primary behåller klientens ursprungliga adress, och att den gamla breda regeln tas bort vid omladdning. Testerna kontrollerar även att efterföljande nekande regler får verkan och att en CGNAT-källadress på ett vanligt LAN-gränssnitt inte kringgår filtret. Detta är trafiktester av filterintegrationen, inte ett verkligt Headscale/Tailscale-test av registrering, ACL eller routedistribution. Tailscales fristående nftables-backend ingår inte i dessa prov; verifiera vald backend och FORWARD-policy vid införandet. GCP-reglerna kontrolleras med mockade Terraform-tester.

Testerna körs också i PR-jobbet utan GCP-autentisering. Återskapande av regler efter förlorat körtillstånd testas, men ersätter inte en riktig VM-omstart eller kontroll av GCP:s effektiva brandvägg.

## Funktionstest i GCP

Den 15 september 2026 verifierades den tidigare versionen före PR-granskningens komplettering för primary/Tailscale i en separat VPC med en testjumphost, en intern klient utan extern IP och en simulerad instruktörsproxy. Testet använde dåvarande branchens brandväggsblock, startup-script och filtertemplate, med separata resursnamn och separat state. De nya primary-reglerna och samspelet med verklig tailscaled har ännu inte testats i GCP.

SSH/sudo via IAP och från instruktörsnätet fungerade. Klientens HTTP/HTTPS gick genom NAT med verifierad källadressöversättning och giltig TLS-kontroll. Anslutningar till jumphostens egna 80/443 samt otillåtna TCP/UDP-portar blockerades mot kända lyssnande tjänster. TCP 8080 fungerade från proxyadressen men blockerades från klienten. SOCKS över IAP fungerade också.

Efter en riktig VM-omstart visade systemd-loggen att filtret laddades före nätverket. Samma trafiktester passerade igen, och inga dubbla kedjehopp eller NAT-regler tillkom. Detta verifierar brandväggslösningen i testmiljön; den verkliga Headscale-tjänsten och Spectres publika proxy behöver fortfarande verifieras vid deras införande.

Återställning provades genom att först återställa GCP-reglerna och sedan ta bort bara värdfiltrets egna kedjor och hopp. Tidigare åtkomst kom tillbaka, medan NAT och SSH fortsatte fungera.

## Införande i befintlig miljö

Synka med aktuell main och granska en färsk plan. OS Login från #64 ska behållas, Secure Boot ska inte aktiveras och ingen VM ska ersättas. En gammal plan får inte återanvändas efter en annan merge eller ändring i miljön. Andra ändringar som kan medföra stopp/start ska samordnas separat innan apply godkänns.

Metadataändringen kör inte automatiskt startup-scriptet på en redan startad VM. Terraform kan också skapa NAT-regeln innan värdfiltret är aktivt. En vanlig fullständig apply är därför inte ett tillräckligt införandeförfarande; `depends_on` bevisar inte att gästsystemets filter är laddat.

1. Samordna testfönster och deployer. Spara aktuell metadata, filter/NAT-regler och eventuella befintliga hjälpscript och systemd-enheter. Verifiera ny OS Login-SSH via IAP, sudo och proxy samt fungerande återställningsåtkomst.
2. Förbered värdfiltret separat efter godkännande. Installera exakt det Terraform-renderade hjälpscriptet och systemd-enheten från den granskade konfigurationen, medan den breda GCP-regeln finns kvar. Starta tjänsten. Undvik att köra en gammal rotplan som återställer SSH-nyckelmetadata.
3. Kontrollera aktiv/enabled `team-nat-firewall.service`, kedjehopp, INPUT/FORWARD-regler, MASQUERADE och IP-forwarding. Verifiera ny SSH-anslutning och SOCKS-proxy. Avbryt vid servicefel; godkänn inte NAT-ingressregeln om filtret inte fungerar.
4. Granska och applicera sedan en ny fullständig plan via det skyddade deployflödet. Den ska lägga till avgränsad NAT-ingress, Headscale-ingress och primary-regeln, begränsa internregeln och uppdatera startup-metadata.
5. Testa GCP:s effektiva regler från en intern klient utan extern IP: HTTP/HTTPS genom NAT ska fungera och nya anslutningar till jumphostens egna 80/443 ska blockeras. Använd kända lyssnare även vid negativa tester. Kontrollera otillåtna TCP/UDP-portar, instruktörens SSH och Headscale från Spectre. Headscale ska inte kunna nås från andra källor genom de nya reglerna.
6. I ett godkänt underhållsfönster: verifiera ny inloggning, filter, NAT och proxy efter omstart. Kontrollera därefter att en ny Terraform-plan inte återinför den breda regeln.

Samordna reglerna med den som genomför #49–51 före merge. När primary och Tailscale införs: verifiera ping och TCP 8000 från en riktig tailnet-klient med både standard-SNAT och bevarad klientadress. Verifiera Spectres ping/HTTPS och Split DNS med dess avsedda masquerade. Starta om/ladda om både vårt filter och tailscaled i båda ordningarna och kontrollera tillåten samt nekad trafik. Registrering, rutter och ACL måste fungera för att hela kedjan ska vara verifierad.

En omstart av den ordinarie jumphosten påverkar SSH, proxy och NAT. Prova helst hela införandet inklusive omstart på isolerade testresurser först. Lägg inte till taggen `jumphost` på en test-VM utan att granska vilka andra regler som då blir tillämpliga.

## Återställning

Om enbart värdfiltret har installerats medan den breda GCP-regeln finns kvar: återställ tidigare service/script, ta bort hoppen från INPUT/FORWARD till de två egna kedjorna och rensa bara dessa kedjor. Bevara NAT och andra brandväggskedjor. Stoppa inte vid enbart `systemctl stop`: en oneshot-tjänsts iptables-regler ligger kvar tills de uttryckligen tas bort.

Om de nya GCP-reglerna redan har applicerats: ta först bort den nya NAT-ingressregeln med en granskad återställningsplan medan värdfiltret finns kvar. Återställ därefter tidigare GCP-konfiguration och värdfilter under ett samordnat underhållsfönster. Att ta bort värdfiltret först kan exponera jumphostens 80/443 från teamets nät. Återställning av den breda internregeln innebär att den tidigare kända risken återkommer; dokumentera det och planera nytt införande.

Bevara OS Login, dess IAM-tilldelningar och Headscale-behovet vid återställning. Kör inte hela gamla main som återställning. Råa planer och säkerhetskopior kan innehålla känsliga uppgifter och ska inte publiceras.
